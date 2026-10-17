"""The same cross-computer billing scenarios run locally and against real Atlas."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pymongo.errors import AutoReconnect

from mobile.server import create_app, Store
from mobile.tests.support import MemoryAccounts

ORIGIN = {'Origin': 'http://localhost:8787'}
PASSWORD = 'shared points test password'


class SharedPointsTest(unittest.TestCase):
    def make_accounts(self):
        return MemoryAccounts()

    def second_accounts(self):
        return self.accounts

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.accounts = self.make_accounts()
        self.apps = [create_app(self.root / str(i), self.root / f'output{i}', runner=lambda *args: [],
                                settings_path=self.root / f'settings{i}.json', accounts=accounts)
                     for i, accounts in enumerate((self.accounts, self.second_accounts()))]
        self.owner = TestClient(self.apps[0], base_url='http://localhost:8787')
        code = (self.root / '0/access-code.txt').read_text()
        login = self.owner.post('/api/login', headers=ORIGIN, json={'code': code}).json()
        self.owner_headers = ORIGIN | {'X-Qianmi-CSRF': login['csrf']}
        result = self.owner.post('/api/membership/bootstrap', headers=self.owner_headers,
                                 json=dict(email='admin@example.com', name='管理員', password=PASSWORD))
        self.assertEqual(result.status_code, 200, result.text)
        self.member_id = result.json()['id']
        self.clients, self.headers = [], []
        for app in self.apps:
            client = TestClient(app, base_url='http://localhost:8787')
            response = client.post('/api/membership/login', headers=ORIGIN, json=dict(email='admin@example.com', password=PASSWORD))
            self.assertEqual(response.status_code, 200, response.text)
            self.clients.append(client)
            self.headers.append(ORIGIN | {'X-Qianmi-CSRF': response.json()['csrf']})

    def tearDown(self):
        for client in [self.owner, *self.clients]:
            client.close()
        self.temp.cleanup()

    def fund(self, amount, request_id=None, computer=0):
        response = self.clients[computer].post('/api/admin/members/' + self.member_id + '/credits', headers=self.headers[computer],
                                                json=dict(amount=amount, reason='儲值單號', request_id=request_id or secrets.token_hex(16)))
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def submit(self, computer=0, request_id=None, prompt='test'):
        return self.clients[computer].post('/api/jobs', headers=self.headers[computer],
                                           json=dict(prompt=prompt, workflow='quick', request_id=request_id or secrets.token_hex(16)))

    def balances(self):
        return [client.get('/api/membership/me').json()['member']['balance'] for client in self.clients]

    def test_two_computers_share_balances_and_admin_adjustment_key(self):
        key = secrets.token_hex(16)
        self.fund(12, key)
        self.fund(12, key, computer=1)
        self.assertEqual(self.balances(), [12, 12])
        self.assertEqual(self.submit(0).status_code, 200)
        self.assertEqual(self.submit(1).status_code, 200)
        self.assertEqual(self.balances(), [6, 6])
        entries = [client.get('/api/membership/ledger').json()['items'] for client in self.clients]
        self.assertEqual(entries[0], entries[1])
        self.assertEqual(len(entries[0]), 3)
        self.assertEqual(self.owner.post('/api/admin/members/' + self.member_id + '/credits', headers=self.owner_headers,
                                        json=dict(amount=100, reason='unauthorized', request_id=secrets.token_hex(16))).status_code, 403)

    def test_concurrent_computers_cannot_overdraw(self):
        self.fund(3)
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(lambda i: self.submit(i).status_code, (0, 1))), [200, 402])
        self.assertEqual(self.balances(), [0, 0])
        self.assertEqual(self.accounts.points.requests.count_documents({'state': 'reserved'}), 1)

    def test_duplicate_request_cross_computer_and_payload_conflict(self):
        self.fund(9)
        key = secrets.token_hex(16)
        first = self.submit(request_id=key)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.submit(request_id=key).json()['id'], first.json()['id'])
        self.assertEqual(self.submit(request_id=key, prompt='changed').status_code, 409)
        self.assertEqual(self.submit(1, key).status_code, 409)
        self.assertEqual(self.balances(), [6, 6])
        self.assertEqual(self.accounts.points.movements.count_documents({'reason': '生成預扣'}), 1)

    def test_ambiguous_charge_and_refund_acknowledgements_retry_after_restart(self):
        self.fund(10)
        store = self.apps[0].state.store
        points, key = self.accounts.points, secrets.token_hex(16)
        reserve = points.reserve
        def charged_then_disconnected(*args):
            reserve(*args)
            raise AutoReconnect('private connection data')
        with patch.object(points, 'reserve', side_effect=charged_then_disconnected):
            response = self.submit(request_id=key)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private connection data', response.text)
        self.assertEqual(self.balances(), [7, 7])
        retried = self.submit(request_id=key)
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(self.balances(), [7, 7])
        job_id = retried.json()['id']
        settle = points.settle
        def refunded_then_disconnected(*args):
            settle(*args)
            raise AutoReconnect('uncertain acknowledgement')
        with patch.object(points, 'settle', side_effect=refunded_then_disconnected):
            store.update(job_id, 'cancelled', '取消')
        self.assertFalse(store.job(job_id)['settled'])
        restored = Store(store.state, store.output, accounts=self.accounts)
        restored.reconcile_points()
        self.assertTrue(restored.job(job_id)['settled'])
        self.assertEqual(self.balances(), [10, 10])
        self.assertEqual(points.movements.count_documents({'reason': '未完成輸出退點'}), 1)

    def test_pending_charge_cancel_prevents_delayed_debit(self):
        self.fund(10)
        points, store = self.accounts.points, self.apps[0].state.store
        with patch.object(points, 'reserve', side_effect=AutoReconnect('offline')):
            self.assertEqual(self.submit().status_code, 503)
        with store.connect() as db:
            job_id = db.execute('SELECT id FROM jobs').fetchone()[0]
        response = self.clients[0].post('/api/jobs/' + job_id + '/cancel', headers=self.headers[0])
        self.assertEqual(response.json()['status'], 'cancelled')
        self.assertEqual(points.reserve(store.billing_job(store.job(job_id)), store.members.host_id)['state'], 'settled')
        self.assertEqual(self.balances(), [10, 10])
        self.assertEqual(points.movements.count_documents({'reason': '生成預扣'}), 0)

    def test_partial_completion_refund_once_and_reject_changed_settlement(self):
        self.fund(10)
        job = self.submit().json()
        store, points = self.apps[0].state.store, self.accounts.points
        with patch.object(points, 'settle', side_effect=AutoReconnect('offline')):
            store.update(job['id'], 'failed', '失敗')
        self.assertFalse(store.job(job['id'])['settled'])
        self.assertEqual(self.balances(), [7, 7])
        store.reconcile_points(); store.reconcile_points()
        self.assertEqual(self.balances(), [10, 10])
        with self.assertRaises(HTTPException):
            points.settle(store.billing_job(store.job(job['id'])), store.members.host_id, 1)

    def test_legacy_history_copied_to_two_computers_is_imported_once(self):
        self.fund(50)
        points = self.accounts.points
        job_id, request_id = secrets.token_hex(16), secrets.token_hex(16)
        history = [dict(member_id=self.member_id, amount=10, reason='舊儲值', actor=None, operation_key='old-credit', job_id=None, created=1),
                   dict(member_id=self.member_id, amount=-3, reason='生成預扣', actor=self.member_id,
                        operation_key='reserve:' + job_id, job_id=job_id, created=2)]
        jobs = [dict(member_id=self.member_id, id=job_id, request_id=request_id, reserved_points=3, unit_points=3,
                     billing_fingerprint='legacy:' + job_id, workflow='quick', settled=0, created=2)]
        for host in ('original', 'copied'):
            points.migrate([dict(id=self.member_id, balance=7)], history, jobs, host)
        self.assertEqual(self.balances(), [57, 57])
        billing = dict(member_id=self.member_id, job_id=job_id, request_id=request_id, reserved_points=3, unit_points=3,
                       fingerprint='legacy:' + job_id, workflow='quick', auth_version=0)
        points.settle(billing, 'original', 0); points.settle(billing, 'original', 0)
        points.migrate([dict(id=self.member_id, balance=7)], history, jobs, 'copied')
        self.assertEqual(self.balances(), [60, 60])
        with self.assertRaises(HTTPException):
            points.settle(billing, 'copied', 0)

    def test_concurrent_retries_charge_and_partial_refund_once(self):
        self.fund(20)
        store = self.apps[0].state.store
        job = dict(member_id=self.member_id, job_id=secrets.token_hex(16), request_id=secrets.token_hex(16),
                   fingerprint='batch', reserved_points=9, unit_points=3, auth_version=0, workflow='quick')
        points = [app.state.store.members.points for app in self.apps]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: points[i % 2].reserve(job, store.members.host_id), range(4)))
        self.assertEqual(self.balances(), [11, 11])
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: points[i % 2].settle(job, store.members.host_id, 1), range(4)))
        self.assertEqual(self.balances(), [17, 17])
        self.assertEqual(points[0].movements.count_documents({'job_id': job['job_id']}), 2)

    def test_fee_rules_are_shared_and_reserved_price_does_not_change(self):
        self.fund(20)
        response = self.clients[0].put('/api/admin/membership', headers=self.headers[0],
                                       json=dict(registration_open=True, image_points=4, video_points=12))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.clients[1].get('/api/membership').json()['image_points'], 4)
        key = secrets.token_hex(16)
        self.assertEqual(self.submit(request_id=key).json()['reserved_points'], 4)
        self.clients[1].put('/api/admin/membership', headers=self.headers[1],
                            json=dict(registration_open=True, image_points=6, video_points=12))
        self.assertEqual(self.submit(request_id=key).json()['reserved_points'], 4)
        self.assertEqual(self.submit(1).json()['reserved_points'], 6)
        self.assertEqual(self.balances(), [10, 10])

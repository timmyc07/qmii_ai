"""Membership authorization and point accounting across the real HTTP queue."""
from concurrent.futures import ThreadPoolExecutor
import io
from pathlib import Path
import secrets
import tempfile
import threading
import time
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from mobile.server import create_app

ORIGIN = {'Origin': 'http://localhost:8787'}
PASSWORD = 'test password 12345'


class MembershipTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.release = threading.Event()
        self.started = threading.Event()
        self.fail_run = False
        self.partial = False

        def runner(payload, sources, output, progress):
            self.started.set()
            self.release.wait(5)
            payload['_control'].check()
            if self.fail_run:
                raise RuntimeError('private upstream detail')
            ext = 'mp4' if payload['workflow'] in ('h3_image', 'svi_image') else 'png'
            count = 1 if payload['workflow'] in ('reference', 'svi_image') else max(1, len(sources))
            results = []
            for index in range(count):
                name = f'{index}.{ext}'
                (output / name).write_bytes(b'result')
                results.append(name)
                progress('completed output', list(results))
                if self.partial:
                    raise RuntimeError('failed after first output')
            return results

        self.app = create_app(self.root / 'state', self.root / 'output', runner=runner,
                              settings_path=self.root / 'settings.json')
        self.owner = TestClient(self.app, base_url='http://localhost:8787')
        self.owner.__enter__()
        self.clients = []
        code = (self.root / 'state/access-code.txt').read_text()
        response = self.owner.post('/api/login', json={'code': code}, headers=ORIGIN)
        self.owner_headers = ORIGIN | {'X-Qianmi-CSRF': response.json()['csrf']}
        self.admin_id = self.owner.post('/api/membership/bootstrap', headers=self.owner_headers,
                                        json=dict(email='admin@example.com', name='管理員', password=PASSWORD)).json()['id']

    def tearDown(self):
        self.release.set()
        self.owner.__exit__(None, None, None)
        for client in self.clients:
            client.close()
        self.temp.cleanup()

    def register(self, email='member@example.com'):
        client = TestClient(self.app, base_url='http://localhost:8787')
        self.clients.append(client)
        response = client.post('/api/membership/register', headers=ORIGIN,
                               json=dict(email=email, name='會員 <名稱>', password=PASSWORD))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        value = response.json()
        return client, ORIGIN | {'X-Qianmi-CSRF': value['csrf']}, value['member']['id']

    def fund(self, member_id, amount=100, request_id=None):
        return self.owner.post(f'/api/admin/members/{member_id}/credits', headers=self.owner_headers,
                               json=dict(amount=amount, reason='測試儲值', request_id=request_id or secrets.token_hex(16)))

    def job(self, client, headers, **overrides):
        value = dict(prompt='private prompt', workflow='quick', images=[], request_id=secrets.token_hex(16))
        return client.post('/api/jobs', headers=headers, json=value | overrides)

    def upload(self, client, headers):
        data = io.BytesIO()
        Image.new('RGB', (32, 32), 'purple').save(data, format='PNG')
        response = client.post('/api/uploads', headers=headers, content=data.getvalue())
        self.assertEqual(response.status_code, 200)
        return response.json()['id']

    def balance(self, client):
        return client.get('/api/membership/me').json()['member']['balance']

    def wait_job(self, client, job_id):
        for _ in range(100):
            job = client.get('/api/jobs/' + job_id).json()
            if job['status'] in ('completed', 'failed', 'cancelled'):
                return job
            time.sleep(.03)
        self.fail('queue did not finish')

    def test_registration_security_roles_and_validation(self):
        client, headers, member_id = self.register(' Member@EXAMPLE.com ')
        self.assertEqual(self.balance(client), 0)
        member = client.get('/api/membership/me').json()['member']
        self.assertEqual(member['email'], 'member@example.com')
        self.assertNotIn('password', member)
        for path in ('/api/admin/members', '/api/admin/audit', '/api/storage', '/api/drive', '/api/health'):
            self.assertEqual(client.get(path).status_code, 403, path)
        self.assertEqual(client.put('/api/settings', headers=headers, json={}).status_code, 403)
        self.assertEqual(self.fund(member_id, True).status_code, 422)
        self.assertEqual(self.job(client, headers).status_code, 402)
        self.assertEqual(client.post('/api/membership/password', headers=ORIGIN,
                                     json=dict(current_password=PASSWORD, password='new secure password')).status_code, 403)
        self.assertEqual(client.post('/api/membership/register', headers=ORIGIN,
                                     json=dict(email='another@example.com', name='a', password=PASSWORD, role='admin')).status_code, 422)
        self.assertEqual(self.owner.post('/api/membership/bootstrap', headers=self.owner_headers,
                                        json=dict(email='a@b.com', name='admin', password=PASSWORD)).status_code, 409)
        with self.app.state.store.connect() as db:
            self.assertNotIn(PASSWORD, db.execute('SELECT password FROM members WHERE id=?', (member_id,)).fetchone()[0])

    def test_atomic_precharge_idempotency_success_and_adjustment_replay(self):
        client, headers, member_id = self.register()
        request_id = secrets.token_hex(16)
        self.assertEqual(self.fund(member_id, 3, request_id).status_code, 200)
        self.assertEqual(self.fund(member_id, 3, request_id).status_code, 200)
        self.assertEqual(self.fund(member_id, 4, request_id).status_code, 409)
        job_request = secrets.token_hex(16)
        first = self.job(client, headers, request_id=job_request)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['reserved_points'], 3)
        self.assertEqual(self.job(client, headers, request_id=job_request).json()['id'], first.json()['id'])
        self.assertEqual(self.balance(client), 0)
        self.assertEqual(self.job(client, headers).status_code, 402)
        self.release.set()
        finished = self.wait_job(client, first.json()['id'])
        self.assertTrue(finished['settled'])
        self.assertEqual(finished['status'], 'completed')
        self.assertEqual(self.balance(client), 0)
        self.assertEqual(len(client.get('/api/membership/ledger').json()['items']), 2)

    def test_concurrent_submissions_cannot_overdraw(self):
        client, headers, member_id = self.register()
        self.fund(member_id, 3)
        # Share only the cookie, with independent clients and one lifespan/worker.
        def request(_):
            other = TestClient(self.app, base_url='http://localhost:8787', cookies=dict(client.cookies))
            try:
                return self.job(other, headers).status_code
            finally:
                other.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(request, range(2))), [200, 402])
        self.assertEqual(self.balance(client), 0)

    def test_batch_reference_and_video_prices(self):
        client, headers, member_id = self.register()
        self.fund(member_id, 100)
        images = [self.upload(client, headers) for _ in range(3)]
        for workflow, sources, expected in [('quick', images, 9), ('reference', images, 3), ('h3_image', images[:2], 20)]:
            response = self.job(client, headers, workflow=workflow, images=sources)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['reserved_points'], expected)
        self.assertEqual(self.balance(client), 68)
        self.owner.put('/api/admin/membership', headers=self.owner_headers,
                       json=dict(registration_open=True, image_points=4, video_points=12))
        self.release.set()
        self.assertEqual(self.wait_job(client, response.json()['id'])['status'], 'completed')
        self.assertEqual(self.balance(client), 68)

    def test_partial_failure_refunds_only_missing_outputs_once(self):
        client, headers, member_id = self.register()
        self.fund(member_id, 30)
        images = [self.upload(client, headers) for _ in range(3)]
        self.partial = True
        response = self.job(client, headers, images=images).json()
        self.assertEqual(self.balance(client), 21)
        self.release.set()
        finished = self.wait_job(client, response['id'])
        self.assertEqual(finished['status'], 'failed')
        self.assertEqual(len(finished['results']), 1)
        self.assertEqual(self.balance(client), 27)
        self.app.state.store.update(response['id'], 'failed', 'retry settlement')
        self.assertEqual(self.balance(client), 27)

    def test_failure_and_queued_cancel_refund(self):
        client, headers, member_id = self.register()
        self.fund(member_id, 9)
        self.fail_run = True
        first = self.job(client, headers).json()
        self.assertTrue(self.started.wait(2))
        second = self.job(client, headers).json()
        self.assertEqual(self.balance(client), 3)
        cancelled = client.post('/api/jobs/' + second['id'] + '/cancel', headers=headers)
        self.assertEqual(cancelled.json()['status'], 'cancelled')
        self.assertEqual(self.balance(client), 6)
        self.release.set()
        self.assertEqual(self.wait_job(client, first['id'])['status'], 'failed')
        self.assertEqual(self.balance(client), 9)

    def test_cross_account_jobs_uploads_results_library_and_request_replay(self):
        first, first_headers, first_id = self.register()
        second, second_headers, second_id = self.register('other@example.com')
        self.fund(first_id)
        self.fund(second_id)
        image = self.upload(first, first_headers)
        request_id = secrets.token_hex(16)
        response = self.job(first, first_headers, images=[image], request_id=request_id).json()
        self.assertEqual(second.get('/api/uploads/' + image).status_code, 404)
        self.assertEqual(self.job(second, second_headers, images=[image]).status_code, 422)
        self.assertEqual(second.get('/api/jobs/' + response['id']).status_code, 404)
        self.assertEqual(self.job(second, second_headers, request_id=request_id).status_code, 404)
        self.assertEqual(second.post('/api/jobs/' + response['id'] + '/cancel', headers=second_headers).status_code, 404)
        self.assertEqual(second.get('/api/jobs').json()['jobs'], [])
        self.release.set()
        finished = self.wait_job(first, response['id'])
        self.assertEqual(second.get(finished['results'][0]).status_code, 404)
        artwork = first.get('/api/library').json()['items'][0]
        self.assertEqual(second.get('/api/library').json()['items'], [])
        self.assertEqual(second.get(artwork['url']).status_code, 404)

    def test_password_reset_is_single_use_expires_and_revokes_sessions(self):
        client, headers, member_id = self.register()
        issued = self.owner.post(f'/api/admin/members/{member_id}/reset', headers=self.owner_headers).json()
        with self.app.state.store.connect() as db:
            self.assertNotEqual(db.execute('SELECT reset_hash FROM members WHERE id=?', (member_id,)).fetchone()[0], issued['token'])
        value = dict(token=issued['token'], password='replacement password')
        self.assertEqual(client.post('/api/membership/reset', headers=ORIGIN, json=value).status_code, 200)
        self.assertEqual(client.get('/api/session').status_code, 401)
        self.assertEqual(client.post('/api/membership/reset', headers=ORIGIN, json=value).status_code, 400)
        login = client.post('/api/membership/login', headers=ORIGIN, json=dict(email='member@example.com', password=value['password']))
        self.assertEqual(login.status_code, 200)
        headers['X-Qianmi-CSRF'] = login.json()['csrf']
        self.assertEqual(client.post('/api/membership/password', headers=headers,
                                     json=dict(current_password=value['password'], password=PASSWORD)).status_code, 200)
        self.assertEqual(client.get('/api/session').status_code, 401)
        token = self.owner.post(f'/api/admin/members/{member_id}/reset', headers=self.owner_headers).json()['token']
        with self.app.state.store.connect() as db:
            db.execute('UPDATE members SET reset_expires=0 WHERE id=?', (member_id,))
        self.assertEqual(client.post('/api/membership/reset', headers=ORIGIN,
                                     json=dict(token=token, password=PASSWORD)).status_code, 400)

    def test_disable_registration_last_admin_and_bruteforce(self):
        client, headers, member_id = self.register()
        self.assertEqual(self.owner.put(f'/api/admin/members/{self.admin_id}', headers=self.owner_headers,
                                        json=dict(role='member', active=False)).status_code, 409)
        self.assertEqual(self.owner.put(f'/api/admin/members/{member_id}', headers=self.owner_headers,
                                        json=dict(role='member', active=False)).status_code, 200)
        self.assertEqual(client.get('/api/jobs').status_code, 401)
        self.owner.put('/api/admin/membership', headers=self.owner_headers,
                       json=dict(registration_open=False, image_points=3, video_points=10))
        self.assertEqual(client.post('/api/membership/register', headers=ORIGIN,
                                     json=dict(email='new@example.com', name='new', password=PASSWORD)).status_code, 403)
        for _ in range(20):
            result = client.post('/api/membership/login', headers=ORIGIN,
                                 json=dict(email='member@example.com', password='wrong password'))
        self.assertEqual(result.status_code, 429)

    def test_restart_settles_interrupted_reservation(self):
        client, headers, member_id = self.register()
        self.fund(member_id, 10)
        store = self.app.state.store
        job_id = secrets.token_hex(16)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            store.members.adjust(db, member_id, -3, '生成預扣', member_id, 'reserve:' + job_id, job_id)
            db.execute('INSERT INTO jobs(id,request_id,status,message,prompt,workflow,sources,results,created,updated,member_id,reserved_points,unit_points) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (job_id, job_id, 'running', '', 'test', 'quick', '[]', '[]', time.time(), time.time(), member_id, 3, 3))
        app = create_app(self.root / 'state', self.root / 'output', runner=lambda *args: [], settings_path=self.root / 'settings.json')
        with TestClient(app, base_url='http://localhost:8787'):
            self.assertEqual(store.job(job_id)['status'], 'failed')
            self.assertEqual(store.members.member(member_id)['balance'], 10)


if __name__ == '__main__':
    unittest.main()

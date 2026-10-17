"""Explicit Atlas integration checks. Only a unique qianmi_ai_test_* database is removed."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import secrets
import sqlite3
import tempfile
import unittest

from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from mobile.accounts import MongoAccounts, connection_uri
from mobile.membership import password_hash
from mobile.server import create_app, Store


ORIGIN = {'Origin': 'http://localhost:8787'}
PASSWORD = 'isolated test password'


class AtlasTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.name = 'qianmi_ai_test_' + secrets.token_hex(8)
        self.mongo = MongoClient(connection_uri(), tls=True, serverSelectionTimeoutMS=5000, timeoutMS=15000)
        self.accounts = MongoAccounts(self.mongo[self.name])
        self.app = create_app(self.root / 'state', self.root / 'output', accounts=self.accounts,
                              runner=lambda *args: [], settings_path=self.root / 'settings.json')
        self.client = TestClient(self.app, base_url='http://localhost:8787')
        code = (self.root / 'state/access-code.txt').read_text()
        login = self.client.post('/api/login', json={'code': code}, headers=ORIGIN).json()
        self.headers = ORIGIN | {'X-Qianmi-CSRF': login['csrf']}

    def tearDown(self):
        self.client.close()
        assert self.name.startswith('qianmi_ai_test_') and len(self.name) == len('qianmi_ai_test_') + 16
        self.mongo.drop_database(self.name)
        self.mongo.close()
        self.temp.cleanup()

    def bootstrap(self, email='admin@example.com'):
        response = self.client.post('/api/membership/bootstrap', headers=self.headers,
                                    json=dict(email=email, password=PASSWORD, name='測試管理員'))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_persistent_accounts_unique_email_and_literal_search(self):
        admin = self.bootstrap()
        record = self.accounts.get(admin['id'])
        self.assertNotEqual(record['password'], PASSWORD)
        self.assertNotIn('password', admin)
        response = self.client.post('/api/membership/register', headers=ORIGIN,
                                    json=dict(email='Member@Example.com', password=PASSWORD, name='<使用者>'))
        self.assertEqual(response.status_code, 200)
        member_id = response.json()['member']['id']
        self.assertEqual(self.client.post('/api/membership/register', headers=ORIGIN,
                                         json=dict(email='member@example.com', password=PASSWORD, name='duplicate')).status_code, 409)
        with MongoClient(connection_uri(), tls=True, timeoutMS=15000) as second_client:
            second = MongoAccounts(second_client[self.name])
            self.assertEqual(second.get(member_id)['email'], 'member@example.com')
            self.assertEqual(second.list('.*'), [])
            self.assertEqual(len(second.list('<使用者>')), 1)
        login = self.client.post('/api/membership/login', headers=ORIGIN,
                                 json=dict(email='member@example.com', password=PASSWORD))
        self.assertEqual(login.status_code, 200)
        self.assertIsNotNone(self.accounts.get(member_id)['last_login_at'])
        self.accounts.update(member_id, 'member', False)
        self.assertEqual(self.client.get('/api/session').status_code, 401)

    def test_atomic_bootstrap_prevents_two_first_administrators(self):
        def register(index):
            from fastapi import HTTPException
            from mobile.membership import Registration
            try:
                self.app.state.store.members.register(Registration(email=f'admin{index}@example.com', name='管理員', password=PASSWORD), bootstrap=True)
                return 200
            except HTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(register, range(2))), [200, 409])
        self.assertEqual(self.accounts.collection.count_documents({'role': 'admin'}), 1)

    def test_password_reset_once_and_last_admin_protection(self):
        from fastapi import HTTPException
        admin = self.bootstrap()
        with self.assertRaises(HTTPException):
            self.accounts.update(admin['id'], 'member', False)
        token_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
        self.accounts.issue_reset(admin['id'], token_hash)
        changed = self.accounts.reset_password(token_hash, password_hash('changed test password'))
        self.assertEqual(changed['auth_version'], 1)
        with self.assertRaises(HTTPException):
            self.accounts.reset_password(token_hash, password_hash(PASSWORD))
        self.assertNotIn('reset_hash', self.accounts.get(admin['id']))

    def test_concurrent_demotions_keep_one_active_administrator(self):
        from fastapi import HTTPException
        first = self.bootstrap()
        row = self.accounts.get(first['id'])
        row.update(id='b' * 32, email='second@example.com')
        self.accounts.create(row)
        def demote(member_id):
            try:
                self.accounts.update(member_id, 'member', False)
                return 200
            except HTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(demote, [first['id'], row['id']])), [200, 409])
        self.assertEqual(self.accounts.collection.count_documents({'role': 'admin', 'active': True}), 1)

    def test_legacy_migration_keeps_ids_wallet_and_hash_without_overwriting_cloud(self):
        state = self.root / 'legacy'; state.mkdir()
        member_id, encoded = 'a' * 32, password_hash(PASSWORD)
        with sqlite3.connect(state / 'mobile.sqlite3') as db:
            db.execute('CREATE TABLE members(id TEXT PRIMARY KEY,email TEXT,name TEXT,password TEXT,role TEXT,active INTEGER,balance INTEGER,created REAL,reset_hash TEXT,reset_expires REAL)')
            db.execute('INSERT INTO members VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (member_id, 'legacy@example.com', '舊會員', encoded, 'admin', 1, 24, 1, None, None))
        db.close()
        store = Store(state, self.root / 'legacy_output', accounts=self.accounts)
        self.assertEqual(self.accounts.get(member_id)['password'], encoded)
        self.assertEqual(store.members.member(member_id)['balance'], 24)
        self.accounts.collection.update_one({'_id': member_id}, {'$set': {'name': '雲端名稱'}})
        Store(state, self.root / 'legacy_output', accounts=self.accounts)
        self.assertEqual(self.accounts.get(member_id)['name'], '雲端名稱')
        self.assertEqual(store.members.member(member_id)['balance'], 24)


class RedactedResult(unittest.TextTestResult):
    def _exc_info_to_string(self, err, test):
        if issubclass(err[0], PyMongoError):
            import traceback
            location = traceback.extract_tb(err[2])[-1]
            details = err[1].details or {} if hasattr(err[1], 'details') else {}
            return f'MongoDB integration failure: {err[0].__name__}, code={getattr(err[1], "code", None)}, name={details.get("codeName", "unknown")}, at {Path(location.filename).name}:{location.lineno} (connection details redacted)\n'
        return super()._exc_info_to_string(err, test)


if __name__ == '__main__':
    unittest.main(testRunner=unittest.TextTestRunner(resultclass=RedactedResult, verbosity=2))

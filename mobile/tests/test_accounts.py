"""Local secret loading, offline failure behavior and account migration checks."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

from mobile.accounts import MongoAccounts, connection_uri
from mobile.membership import password_hash
from mobile.tests.support import MemoryAccounts, Store, create_app


class AccountTest(unittest.TestCase):
    def test_env_is_data_and_environment_takes_precedence(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {}, clear=True):
            path = Path(folder) / '.env'
            path.write_text('# private configuration\nMONGODB_URI="mongodb+srv://user:password@example.invalid/"\nIGNORED=$(anything)\n')
            self.assertEqual(connection_uri(path), 'mongodb+srv://user:password@example.invalid/')
            with patch.dict('os.environ', {'MONGODB_URI': 'mongodb://env.example.invalid/'}):
                self.assertEqual(connection_uri(path), 'mongodb://env.example.invalid/')
            path.write_text('MONGODB_URI=do not execute this\n')
            with self.assertRaisesRegex(RuntimeError, 'MONGODB_URI'):
                connection_uri(path)

    def test_connection_failure_does_not_expose_uri(self):
        with patch('mobile.accounts.connection_uri', return_value='mongodb://user:private-password@example.invalid/'), \
                patch('mobile.accounts.MongoClient', side_effect=ServerSelectionTimeoutError('private-password')):
            with self.assertRaises(RuntimeError) as result:
                MongoAccounts.from_env()
        self.assertNotIn('private-password', str(result.exception))

    def test_moves_identity_once_preserving_wallet_and_password_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = root / 'state'; state.mkdir()
            encoded = password_hash('migration password')
            with sqlite3.connect(state / 'mobile.sqlite3') as db:
                db.execute('CREATE TABLE members(id TEXT PRIMARY KEY,email TEXT,name TEXT,password TEXT,role TEXT,active INTEGER,balance INTEGER,created REAL,reset_hash TEXT,reset_expires REAL)')
                db.execute('INSERT INTO members VALUES (?,?,?,?,?,?,?,?,?,?)',
                           ('a' * 32, 'admin@example.com', '管理員', encoded, 'admin', 1, 12, 1, None, None))
            db.close()
            store = Store(state, root / 'output')
            member = store.members.member('a' * 32)
            self.assertEqual(member['password'], encoded)
            self.assertEqual(member['balance'], 12)
            self.assertTrue((state / 'members-before-mongodb.sqlite3').is_file())
            with sqlite3.connect(state / 'members-before-mongodb.sqlite3') as backup:
                self.assertEqual(backup.execute('SELECT value FROM host_identity WHERE id=1').fetchone()[0], store.members.host_id)
            backup.close()
            with store.connect() as db:
                self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name IN ('members','member_wallets','point_ledger')").fetchone())
            store.members.points.adjust(member['id'], -3, '測試', member['id'], 'test', store.members.host_id)
            self.assertEqual(Store(state, root / 'output').members.member(member['id'])['balance'], 9)

    def test_cloud_revocation_guard_does_not_block_independent_settlement(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            accounts = MemoryAccounts()
            app = create_app(root / 'state', root / 'output', runner=lambda *args: [],
                             settings_path=root / 'settings.json', accounts=accounts)
            client = TestClient(app, base_url='http://localhost:8787')
            origin = {'Origin': 'http://localhost:8787'}
            code = (root / 'state/access-code.txt').read_text()
            result = client.post('/api/login', json={'code': code}, headers=origin).json()
            owner_headers = origin | {'X-Qianmi-CSRF': result['csrf']}
            admin = client.post('/api/membership/bootstrap', headers=owner_headers,
                                json=dict(email='admin@example.com', name='管理員', password='test password 123')).json()
            login = client.post('/api/membership/login', headers=origin, json=dict(email='admin@example.com', password='test password 123')).json()
            headers = origin | {'X-Qianmi-CSRF': login['csrf']}
            client.post('/api/admin/members/' + admin['id'] + '/credits', headers=headers,
                        json=dict(amount=10, reason='測試', request_id='a' * 32))
            job = client.post('/api/jobs', headers=headers, json=dict(prompt='test', workflow='quick', request_id='b' * 32)).json()
            with patch.object(accounts, 'get', side_effect=ServerSelectionTimeoutError('mongodb://private-secret@host')):
                response = client.get('/api/session')
                self.assertEqual(response.status_code, 503)
                self.assertNotIn('private-secret', response.text)
                app.state.store.update(job['id'], 'cancelled', '退點')
                self.assertEqual(app.state.store.members.points.balance(admin['id']), 10)
            accounts.collection.update_one({'_id': admin['id']}, {'$inc': {'auth_version': 1}})
            self.assertEqual(client.get('/api/session').status_code, 401)
            client.close()

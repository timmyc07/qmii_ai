"""Explicit account injection keeps ordinary tests away from the real Atlas database."""
from copy import deepcopy
from pathlib import Path
import threading
import time

from fastapi import HTTPException
from mobile.server import Store as ServerStore, create_app as server_app


class MemoryAccounts:
    def __init__(self):
        self.records = {}
        self.lock = threading.RLock()

    def close(self):
        pass

    def get(self, member_id):
        with self.lock:
            return deepcopy(self.records.get(member_id))

    def by_email(self, email):
        with self.lock:
            return next((deepcopy(row) for row in self.records.values() if row['email'] == email), None)

    def initialized(self):
        return bool(self.records)

    def create(self, member, bootstrap=False):
        with self.lock:
            if bootstrap and self.records:
                raise HTTPException(409, '管理員已建立。')
            if not bootstrap and not self.records:
                raise HTTPException(403, '請先建立管理員。')
            if self.by_email(member['email']):
                raise HTTPException(409, '電子郵件已註冊。')
            self.records[member['id']] = deepcopy(member)
        return member

    def import_members(self, rows):
        with self.lock:
            for row in rows:
                self.records.setdefault(row['id'], {k: v for k, v in row.items() if k != 'balance'} |
                                        {'auth_version': 0, 'updated_at': row['created'], 'last_login_at': None})

    def list(self, search='', offset=0):
        with self.lock:
            rows = [deepcopy(row) for row in self.records.values() if search.lower() in row['email'].lower() or search.lower() in row['name'].lower()]
            return sorted(rows, key=lambda row: (-row['created'], row['id']))[offset:offset + 100]

    def update(self, member_id, role, active):
        with self.lock:
            member = self.records.get(member_id)
            if not member:
                raise HTTPException(404, '找不到會員。')
            if member['role'] == 'admin' and member['active'] and (not active or role != 'admin'):
                if sum(row['role'] == 'admin' and row['active'] for row in self.records.values()) <= 1:
                    raise HTTPException(409, '必須保留管理員。')
            member.update(role=role, active=active, auth_version=member['auth_version'] + 1, updated_at=time.time())
            member.pop('reset_hash', None); member.pop('reset_expires', None)

    def login(self, member):
        with self.lock:
            current = self.records.get(member['id'])
            if not current or not current['active'] or any(current[key] != member[key] for key in ('password', 'auth_version')):
                raise HTTPException(401, '登入已失效。')
            current['last_login_at'] = time.time()
            return deepcopy(current)

    def change_password(self, member, encoded):
        with self.lock:
            current = self.records[member['id']]
            if current['password'] != member['password'] or not current['active']:
                raise HTTPException(409, '帳號狀態已變更。')
            current.update(password=encoded, auth_version=current['auth_version'] + 1, updated_at=time.time())
            current.pop('reset_hash', None); current.pop('reset_expires', None)

    def issue_reset(self, member_id, token_hash):
        with self.lock:
            if member_id not in self.records:
                raise HTTPException(404, '找不到會員。')
            self.records[member_id].update(reset_hash=token_hash, reset_expires=time.time() + 1800)

    def reset_password(self, token_hash, encoded):
        with self.lock:
            member = next((row for row in self.records.values() if row.get('reset_hash') == token_hash and
                           row.get('reset_expires', 0) > time.time() and row['active']), None)
            if not member:
                raise HTTPException(400, '重設碼無效或已過期。')
            self.change_password(deepcopy(member), encoded)
            return deepcopy(member)


_accounts = {}


def accounts_for(state):
    return _accounts.setdefault(str(Path(state).resolve()), MemoryAccounts())


def Store(state, output):
    return ServerStore(state, output, accounts=accounts_for(state))


def create_app(*args, **kwargs):
    state = args[0] if args else kwargs.get('state_dir')
    assert state is not None, 'Tests must provide an isolated state directory'
    kwargs.setdefault('accounts', accounts_for(state))
    return server_app(*args, **kwargs)

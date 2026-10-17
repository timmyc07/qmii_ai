"""MongoDB is the authority for account identity, credentials and session revocation."""
import os
from pathlib import Path
import re
import time

from fastapi import HTTPException
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from .points import MongoPoints

ROOT = Path(__file__).resolve().parents[1]


def connection_uri(path=None):
    uri = os.environ.get('MONGODB_URI', '')
    if not uri:
        source = Path(path or ROOT / '.env')
        if source.is_file():
            for line in source.read_text(encoding='utf-8-sig').splitlines():
                key, separator, value = line.strip().partition('=')
                if separator and key.strip() == 'MONGODB_URI':
                    uri = value.strip()
                    if len(uri) >= 2 and uri[0] == uri[-1] and uri[0] in ('"', "'"):
                        uri = uri[1:-1]
    if not uri.startswith(('mongodb://', 'mongodb+srv://')) or any(c in uri for c in '\r\n<>'):
        raise RuntimeError('請在專案 .env 設定有效的 MONGODB_URI。')
    return uri


class MongoAccounts:
    def __init__(self, database):
        self.database = database
        self.collection = database.members
        self.state = database.account_state
        self.collection.create_index('email', unique=True, name='unique_email')
        self.state.update_one({'_id': 'members'}, {'$setOnInsert': {'revision': 0}}, upsert=True)
        self.points = MongoPoints(database)

    @classmethod
    def from_env(cls):
        client = None
        try:
            client = MongoClient(connection_uri(), appname='QianmiAI', tls=True,
                                 tlsAllowInvalidCertificates=False, tlsAllowInvalidHostnames=False,
                                 serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
                                 socketTimeoutMS=10000, timeoutMS=15000)
            client.admin.command('ping')
            return cls(client.get_default_database('qianmi_ai'))
        except (PyMongoError, ValueError, OSError):
            if client is not None:
                client.close()
            raise RuntimeError('MongoDB 連線失敗，請檢查主機 .env、Atlas 網路白名單與資料庫權限。') from None

    def close(self):
        self.database.client.close()

    @staticmethod
    def document(row):
        if row is None:
            return None
        return {**{key: value for key, value in row.items() if key != '_id'}, 'id': row['_id']}

    def get(self, member_id):
        return self.document(self.collection.find_one({'_id': member_id}))

    def by_email(self, email):
        return self.document(self.collection.find_one({'email': email}))

    def initialized(self):
        return self.collection.find_one({}, {'_id': 1}) is not None

    def transaction(self, callback):
        with self.database.client.start_session() as session:
            def run(transaction):
                # Serialize bootstrap and administrator changes to prevent write skew.
                self.state.update_one({'_id': 'members'}, {'$inc': {'revision': 1}}, session=transaction)
                return callback(transaction)
            return session.with_transaction(run)

    def create(self, member, bootstrap=False):
        def insert(session):
            exists = self.collection.find_one({}, {'_id': 1}, session=session)
            if bootstrap and exists:
                raise HTTPException(409, '管理員已建立，請使用會員登入。')
            if not bootstrap and not exists:
                raise HTTPException(403, '請先由主機建立管理員。')
            self.collection.insert_one({key: value for key, value in member.items() if key != 'id'} | {'_id': member['id']}, session=session)
        try:
            self.transaction(insert)
        except DuplicateKeyError:
            raise HTTPException(409, '此電子郵件已註冊。') from None
        return member

    def import_members(self, rows):
        def migrate(session):
            for row in rows:
                self.collection.update_one({'_id': row['id']}, {'$setOnInsert': {
                    key: value for key, value in row.items() if key not in ('id', 'balance')
                } | {'active': bool(row['active']), 'auth_version': 0, 'updated_at': row['created'], 'last_login_at': None}}, upsert=True, session=session)
        try:
            self.transaction(migrate)
        except DuplicateKeyError:
            raise RuntimeError('既有會員與 MongoDB 電子郵件衝突，已停止移轉並保留本機資料。') from None

    def list(self, search='', offset=0):
        query = {'$or': [{'email': {'$regex': re.escape(search), '$options': 'i'}},
                         {'name': {'$regex': re.escape(search), '$options': 'i'}}]} if search else {}
        return [self.document(row) for row in self.collection.find(query).sort([('created', -1), ('_id', 1)]).skip(offset).limit(100)]

    def update(self, member_id, role, active):
        def change(session):
            member = self.collection.find_one({'_id': member_id}, session=session)
            if not member:
                raise HTTPException(404, '找不到會員。')
            if member['role'] == 'admin' and member['active'] and (not active or role != 'admin'):
                if self.collection.count_documents({'role': 'admin', 'active': True}, session=session) <= 1:
                    raise HTTPException(409, '必須保留至少一位啟用的管理員。')
            self.collection.update_one({'_id': member_id}, {'$set': {'role': role, 'active': active, 'updated_at': time.time()},
                                       '$unset': {'reset_hash': '', 'reset_expires': ''}, '$inc': {'auth_version': 1}}, session=session)
        self.transaction(change)

    def login(self, member):
        row = self.collection.find_one_and_update({'_id': member['id'], 'password': member['password'],
                                                  'auth_version': member['auth_version'], 'active': True},
                                                 {'$set': {'last_login_at': time.time()}}, return_document=ReturnDocument.AFTER)
        if not row:
            raise HTTPException(401, '帳號狀態已變更，請重新登入。')
        return self.document(row)

    def change_password(self, member, encoded):
        result = self.collection.update_one({'_id': member['id'], 'password': member['password'], 'active': True},
                                            {'$set': {'password': encoded, 'updated_at': time.time()},
                                             '$unset': {'reset_hash': '', 'reset_expires': ''}, '$inc': {'auth_version': 1}})
        if not result.matched_count:
            raise HTTPException(409, '帳號狀態已變更，請重新登入。')

    def issue_reset(self, member_id, token_hash):
        result = self.collection.update_one({'_id': member_id}, {'$set': {'reset_hash': token_hash, 'reset_expires': time.time() + 1800}})
        if not result.matched_count:
            raise HTTPException(404, '找不到會員。')

    def reset_password(self, token_hash, encoded):
        row = self.collection.find_one_and_update({'reset_hash': token_hash, 'reset_expires': {'$gt': time.time()}, 'active': True},
                                                 {'$set': {'password': encoded, 'updated_at': time.time()},
                                                  '$unset': {'reset_hash': '', 'reset_expires': ''}, '$inc': {'auth_version': 1}},
                                                 return_document=ReturnDocument.AFTER)
        if not row:
            raise HTTPException(400, '重設碼無效或已過期。')
        return self.document(row)

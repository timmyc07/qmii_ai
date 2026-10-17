"""Ordinary tests use MongoDB-compatible in-memory collections, never the real Atlas."""
from pathlib import Path
import threading

import mongomock
from mobile.accounts import MongoAccounts
from mobile.points import MongoPoints
from mobile.server import Store as ServerStore, create_app as server_app


class MemoryPoints(MongoPoints):
    def __init__(self, database, lock):
        super().__init__(database)
        self.lock = lock

    def transaction(self, member_id, callback):
        # Atlas integration tests cover actual transaction rollback and cross-client conflicts.
        with self.lock:
            self.wallets.update_one({'_id': member_id}, {'$setOnInsert': {'balance': 0}}, upsert=True)
            return callback(None)


class MemoryAccounts(MongoAccounts):
    def __init__(self):
        self.lock = threading.RLock()
        super().__init__(mongomock.MongoClient().qianmi_test)
        self.points = MemoryPoints(self.database, self.lock)

    def transaction(self, callback):
        with self.lock:
            return callback(None)

    def close(self):
        pass


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

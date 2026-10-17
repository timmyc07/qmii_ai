"""Run shared-wallet scenarios with two real independent Atlas clients."""
import secrets
import unittest
from unittest.mock import patch

from pymongo import MongoClient
from pymongo.errors import OperationFailure
from mobile.accounts import MongoAccounts, connection_uri
from mobile.tests.test_points import SharedPointsTest as PointScenarios
from tools.test_accounts_mongo import RedactedResult


class AtlasPointsTest(PointScenarios):
    def make_accounts(self):
        self.name = 'qianmi_points_test_' + secrets.token_hex(6)
        self.mongo = MongoClient(connection_uri(), tls=True, timeoutMS=15000)
        return MongoAccounts(self.mongo[self.name])

    def second_accounts(self):
        self.second_mongo = MongoClient(connection_uri(), tls=True, timeoutMS=15000)
        return MongoAccounts(self.second_mongo[self.name])

    def tearDown(self):
        super().tearDown()
        assert self.name.startswith('qianmi_points_test_') and len(self.name) == len('qianmi_points_test_') + 12
        self.mongo.drop_database(self.name)
        self.second_mongo.close()
        self.mongo.close()

    def test_failed_transaction_rolls_back_balance_and_ledger(self):
        self.fund(10)
        points, store = self.accounts.points, self.apps[0].state.store
        with patch.object(points.requests, 'insert_one', side_effect=OperationFailure('forced rollback')):
            response = self.submit()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.balances(), [10, 10])
        self.assertEqual(points.movements.count_documents({'reason': '生成預扣'}), 0)
        with store.connect() as db:
            job_id = db.execute('SELECT id FROM jobs').fetchone()[0]
        store.confirm_billing(job_id)
        self.assertEqual(self.balances(), [7, 7])


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AtlasPointsTest)
    result = unittest.TextTestRunner(resultclass=RedactedResult, verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())

"""Shared MongoDB wallets, immutable movements and idempotent generation reservations."""
import hashlib
import json
import time

from fastapi import HTTPException
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


class MongoPoints:
    def __init__(self, database):
        self.database = database
        self.wallets = database.point_wallets
        self.movements = database.point_ledger
        self.requests = database.point_requests
        self.movements.create_index([('member_id', 1), ('created', -1), ('_id', 1)])

    def transaction(self, member_id, callback):
        initial = {'$setOnInsert': {'balance': 0, 'revision': 0}}
        try:
            self.wallets.update_one({'_id': member_id}, initial, upsert=True)
        except DuplicateKeyError:
            self.wallets.update_one({'_id': member_id}, initial, upsert=True)
        with self.database.client.start_session() as session:
            def run(transaction):
                # Write the wallet first so concurrent requests retry with a fresh snapshot.
                self.wallets.update_one({'_id': member_id}, {'$inc': {'revision': 1}}, session=transaction)
                return callback(transaction)
            return session.with_transaction(run, read_concern=ReadConcern('snapshot'), write_concern=WriteConcern('majority'))

    def balance(self, member_id):
        row = self.wallets.find_one({'_id': member_id}, {'balance': 1})
        return row['balance'] if row else 0

    def initialize_settings(self, value):
        self.database.membership_settings.update_one({'_id': 'membership'}, {'$setOnInsert': value}, upsert=True)

    def settings(self):
        row = self.database.membership_settings.find_one({'_id': 'membership'})
        return {key: row[key] for key in ('registration_open', 'image_points', 'video_points')}

    def save_settings(self, value, actor):
        def save(session):
            if not self.database.members.find_one({'_id': actor, 'role': 'admin', 'active': True}, session=session):
                raise HTTPException(403, '共用使用規則需要會員管理員登入。')
            self.database.membership_settings.update_one({'_id': 'membership'}, {'$set': value}, session=session)
        self.transaction(actor, save)

    def movement(self, session, member_id, amount, reason, actor, key, job_id=None, host_id=None, created=None):
        signature = fingerprint([member_id, amount, reason, actor, job_id])
        previous = self.movements.find_one({'_id': key}, session=session)
        if previous:
            if previous['fingerprint'] != signature:
                raise HTTPException(409, '交易編號已用於不同內容，請重新操作。')
            return previous
        wallet = self.wallets.find_one_and_update({'_id': member_id, 'balance': {'$gte': max(0, -amount)}},
                                                  {'$inc': {'balance': amount}}, session=session,
                                                  return_document=ReturnDocument.AFTER)
        if not wallet:
            raise HTTPException(402, '點數不足，請聯絡管理員儲值。')
        entry = dict(_id=key, member_id=member_id, amount=amount, balance=wallet['balance'], reason=reason,
                     actor=actor, job_id=job_id, host_id=host_id, created=created if created is not None else time.time(),
                     fingerprint=signature)
        self.movements.insert_one(entry, session=session)
        return entry

    def adjust(self, member_id, amount, reason, actor, key, host_id):
        def change(session):
            admin = self.database.members.find_one({'_id': actor, 'role': 'admin', 'active': True}, session=session)
            if not admin:
                raise HTTPException(403, '共用點數調整需要會員管理員登入。')
            if not self.database.members.find_one({'_id': member_id}, {'_id': 1}, session=session):
                raise HTTPException(404, '找不到會員。')
            return self.movement(session, member_id, amount, reason, actor, key, host_id=host_id)
        return self.transaction(member_id, change)

    @staticmethod
    def request_key(job):
        return job['member_id'] + ':' + job['request_id']

    @staticmethod
    def verify(previous, job, host_id):
        if any(previous[key] != job[key] for key in ('member_id', 'job_id', 'fingerprint', 'reserved_points', 'unit_points', 'workflow')):
            raise HTTPException(409, '此請求編號已用於不同的生成內容。')
        if previous['host_id'] != host_id:
            raise HTTPException(409, '此請求已由其他電腦受理，請回原電腦查看，勿重複提交。')

    def reserve(self, job, host_id):
        if job['unit_points'] <= 0 or job['reserved_points'] <= 0 or job['reserved_points'] % job['unit_points']:
            raise HTTPException(422, '生成點數格式錯誤。')
        key = self.request_key(job)
        def charge(session):
            previous = self.requests.find_one({'_id': key}, session=session)
            if previous:
                self.verify(previous, job, host_id)
                return previous
            member = self.database.members.find_one({'_id': job['member_id'], 'active': True,
                                                      'auth_version': job['auth_version']}, {'_id': 1}, session=session)
            if not member:
                raise HTTPException(401, '會員登入已失效，請重新登入。')
            settings = self.database.membership_settings.find_one({'_id': 'membership'}, session=session)
            expected = settings['video_points' if job['workflow'] in ('h3_image', 'svi_image') else 'image_points']
            if job['unit_points'] != expected:
                raise HTTPException(409, '費率已更新，請重新提交生成任務。')
            self.movement(session, job['member_id'], -job['reserved_points'], '生成預扣', job['member_id'],
                          'reserve:' + job['job_id'], job['job_id'], host_id)
            record = {key: job[key] for key in ('member_id', 'job_id', 'fingerprint', 'reserved_points', 'unit_points', 'workflow')}
            record.update(_id=key, host_id=host_id, state='reserved', created=time.time())
            self.requests.insert_one(record, session=session)
            return record
        return self.transaction(job['member_id'], charge)

    def settle(self, job, host_id, completed):
        if not 0 <= completed * job['unit_points'] <= job['reserved_points']:
            raise HTTPException(409, '輸出數量與預扣點數不符，請聯絡管理員。')
        key = self.request_key(job)
        def refund(session):
            record = self.requests.find_one({'_id': key}, session=session)
            if record:
                self.verify(record, job, host_id)
                if record['state'] == 'settled':
                    if record['completed'] != completed:
                        raise HTTPException(409, '任務已結算，輸出數量不可變更。')
                    return record
                amount = record['reserved_points'] - completed * record['unit_points']
                if amount:
                    self.movement(session, job['member_id'], amount, '未完成輸出退點', None,
                                  'refund:' + job['job_id'], job['job_id'], host_id)
                self.requests.update_one({'_id': key}, {'$set': {'state': 'settled', 'completed': completed,
                                                               'refund': amount, 'settled_at': time.time()}}, session=session)
            else:
                if completed:
                    raise HTTPException(409, '找不到任務預扣紀錄，拒絕無依據的退點。')
                # A cancellation tombstone prevents a delayed reserve from charging later.
                record = {field: job[field] for field in ('member_id', 'job_id', 'fingerprint', 'reserved_points', 'unit_points', 'workflow')}
                record.update(_id=key, host_id=host_id, state='settled', completed=0, refund=0, settled_at=time.time())
                self.requests.insert_one(record, session=session)
            return self.requests.find_one({'_id': key}, session=session)
        return self.transaction(job['member_id'], refund)

    def ledger(self, member_id=None, offset=0, limit=50):
        query = {'member_id': member_id} if member_id is not None else {}
        return [{key: row.get(key) for key in ('member_id', 'amount', 'balance', 'reason', 'actor', 'job_id', 'host_id', 'created')} |
                {'id': row['_id']} for row in self.movements.find(query).sort([('created', -1), ('_id', 1)]).skip(offset).limit(limit)]

    def migrate(self, wallets, ledger, jobs, host_id):
        for wallet in wallets:
            member_id = wallet['id']
            history = [row for row in ledger if row['member_id'] == member_id]
            opening = wallet['balance'] - sum(row['amount'] for row in history)
            def transfer(session):
                if opening:
                    self.movement(session, member_id, opening, '舊點數期初移轉', None, 'opening:' + member_id, host_id=host_id)
                for row in history:
                    self.movement(session, member_id, row['amount'], row['reason'], row['actor'], row['operation_key'],
                                  row['job_id'], host_id, row['created'])
                for job in jobs:
                    if job['member_id'] != member_id or not job['reserved_points']:
                        continue
                    record = dict(member_id=member_id, request_id=job['request_id'] or job['id'], job_id=job['id'],
                                  fingerprint=job['billing_fingerprint'], reserved_points=job['reserved_points'], unit_points=job['unit_points'], workflow=job['workflow'])
                    key = self.request_key(record)
                    previous = self.requests.find_one({'_id': key}, session=session)
                    if previous:
                        self.verify(previous, record, previous['host_id'])
                        continue
                    refund = next((row['amount'] for row in history if row['operation_key'] == 'refund:' + job['id']), 0)
                    record.update(_id=key, host_id=host_id, state='settled' if job['settled'] else 'reserved', created=job['created'])
                    if job['settled']:
                        record.update(completed=(job['reserved_points'] - refund) // job['unit_points'], refund=refund)
                    self.requests.insert_one(record, session=session)
            self.transaction(member_id, transfer)

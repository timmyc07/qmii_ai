"""Membership API and migration into shared MongoDB accounts and wallets."""
import hashlib
import hmac
import re
import secrets
import time
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)


class Registration(Credentials):
    name: str = Field(min_length=1, max_length=80)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=10, max_length=128)


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(min_length=20, max_length=128)
    password: str = Field(min_length=10, max_length=128)


class MemberUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['member', 'admin']
    active: bool = Field(strict=True)


class CreditAdjustment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    amount: int = Field(strict=True, ge=-1_000_000, le=1_000_000)
    reason: str = Field(min_length=1, max_length=200)
    request_id: str = Field(pattern='^[a-f0-9]{32}$')


class MembershipSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    registration_open: bool = Field(default=True, strict=True)
    image_points: int = Field(default=3, strict=True, ge=1, le=10_000)
    video_points: int = Field(default=10, strict=True, ge=1, le=10_000)


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=3, maxmem=64 * 1024**2).hex()
    return salt + ':' + digest


def check_password(password, encoded):
    return hmac.compare_digest(password_hash(password, encoded.split(':')[0]), encoded)


def email_address(value):
    value = value.strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
        raise HTTPException(422, '請輸入有效的電子郵件。')
    return value


class Members:
    def __init__(self, connect, accounts):
        self.connect = connect
        self.accounts = accounts
        self.points = accounts.points
        with connect() as db:
            old_settings = db.execute("SELECT 1 FROM sqlite_master WHERE name='membership_settings'").fetchone()
            if old_settings:
                row = dict(db.execute('SELECT * FROM membership_settings WHERE id=1').fetchone())
                initial = {key: row[key] for key in ('registration_open', 'image_points', 'video_points')}
                initial['registration_open'] = bool(initial['registration_open'])
            else:
                initial = MembershipSettings().model_dump()
            self.points.initialize_settings(initial)
            db.executescript('''
                CREATE TABLE IF NOT EXISTS member_audit (
                    id INTEGER PRIMARY KEY, actor TEXT, member_id TEXT, action TEXT NOT NULL, created REAL NOT NULL);
            ''')
            self.host_id = db.execute('SELECT value FROM host_identity WHERE id=1').fetchone()[0]
            for table, fields in {
                'sessions': [('member_id', 'TEXT'), ('auth_version', 'INTEGER NOT NULL DEFAULT 0')], 'uploads': [('member_id', 'TEXT')],
                'jobs': [('member_id', 'TEXT'), ('reserved_points', 'INTEGER NOT NULL DEFAULT 0'),
                         ('unit_points', 'INTEGER NOT NULL DEFAULT 0'), ('settled', 'INTEGER NOT NULL DEFAULT 0')],
            }.items():
                columns = {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}
                for name, definition in fields:
                    if name not in columns:
                        db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(jobs)')}
            for name, definition in [('billing_fingerprint', "TEXT NOT NULL DEFAULT ''"),
                                     ('billing_status', "TEXT NOT NULL DEFAULT 'pending'"),
                                     ('billing_error', 'INTEGER'), ('billing_auth_version', 'INTEGER NOT NULL DEFAULT 0')]:
                if name not in columns:
                    db.execute(f'ALTER TABLE jobs ADD COLUMN {name} {definition}')
            db.execute("UPDATE jobs SET billing_fingerprint='legacy:'||id WHERE billing_fingerprint=''")
            db.execute("UPDATE jobs SET billing_status='exempt' WHERE member_id IS NULL")
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='members'").fetchone():
                rows = [dict(row) for row in db.execute('SELECT * FROM members')]
                if rows:
                    accounts.import_members(rows)
                db.execute('CREATE TABLE IF NOT EXISTS member_wallets(id TEXT PRIMARY KEY,balance INTEGER NOT NULL)')
                for row in rows:
                    db.execute('INSERT OR IGNORE INTO member_wallets(id,balance) VALUES (?,?)', (row['id'], row['balance']))
                db.execute('DROP TABLE members')
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'member_wallets' in tables:
                wallets = [dict(row) for row in db.execute('SELECT * FROM member_wallets')]
                ledger = [dict(row) for row in db.execute('SELECT * FROM point_ledger ORDER BY id')] if 'point_ledger' in tables else []
                jobs = [dict(row) for row in db.execute('SELECT * FROM jobs WHERE member_id IS NOT NULL')]
                self.points.migrate(wallets, ledger, jobs, self.host_id)
                db.execute("UPDATE jobs SET billing_status=CASE WHEN settled=1 THEN 'settled' ELSE 'reserved' END WHERE member_id IS NOT NULL AND reserved_points>0")
                db.execute('DROP TABLE member_wallets')
            if 'point_ledger' in tables:
                db.execute('DROP TABLE point_ledger')
            if old_settings:
                db.execute('DROP TABLE membership_settings')

    @staticmethod
    def public(row):
        return {key: row[key] for key in ('id', 'email', 'name', 'role', 'active', 'balance', 'created', 'updated_at', 'last_login_at')}

    @staticmethod
    def audit(db, actor, member_id, action):
        db.execute('INSERT INTO member_audit(actor,member_id,action,created) VALUES (?,?,?,?)',
                   (actor, member_id, action, time.time()))

    def settings(self):
        return self.points.settings()

    def member(self, member_id):
        row = self.accounts.get(member_id)
        if not row:
            raise HTTPException(404, '找不到會員。')
        return row | {'balance': self.points.balance(member_id)}

    def register(self, value, bootstrap=False):
        email = email_address(value.email)
        name = value.name.strip()
        if not name:
            raise HTTPException(422, '請填寫會員名稱。')
        encoded = password_hash(value.password)
        if not bootstrap and not self.settings()['registration_open']:
            raise HTTPException(403, '目前未開放註冊，請聯絡管理員。')
        member_id, now = secrets.token_hex(16), time.time()
        self.accounts.create(dict(id=member_id, email=email, name=name, password=encoded,
                                  role='admin' if bootstrap else 'member', active=True, auth_version=0,
                                  created=now, updated_at=now, last_login_at=None), bootstrap)
        with self.connect() as db:
            self.audit(db, member_id, member_id, '建立管理員' if bootstrap else '會員註冊')
            return self.member(member_id)

    def authenticate(self, value):
        email = email_address(value.email)
        row = self.accounts.by_email(email)
        # Use the same expensive operation when an account does not exist.
        valid = check_password(value.password, row['password']) if row else check_password(value.password, '00' * 16 + ':' + '00' * 64)
        if not valid or not row or not row['active']:
            raise HTTPException(401, '帳號或密碼錯誤，或帳號已停用。')
        return self.accounts.login(row)

    def quote(self, session, value):
        if session['member_id'] is None:
            return 0, 0  # The private host administrator is not a billable member.
        member = self.member(session['member_id'])
        if not member['active'] or member['auth_version'] != session['auth_version']:
            raise HTTPException(401, '會員登入已失效，請重新登入。')
        video = value.workflow in ('h3_image', 'svi_image')
        settings = self.settings()
        unit = settings['video_points' if video else 'image_points']
        count = 1 if value.workflow in ('reference', 'svi_image') else max(1, len(value.images))
        amount = unit * count
        return amount, unit


def install_membership(app, store, parse_json, public_url):
    members = store.members
    attempts = {}

    def limited(request):
        now = time.monotonic()
        key = request.client.host if request.client else 'local'
        for address in list(attempts):
            attempts[address] = [t for t in attempts[address] if t > now - 300]
            if not attempts[address]:
                del attempts[address]
        values = attempts.setdefault(key, [])
        if len(values) >= 15:
            raise HTTPException(429, '操作過於頻繁，請五分鐘後再試。')
        values.append(now)

    def admin(request, mutate=False, allow_owner=True):
        session = store.session(request, mutate)
        if session['member_id'] is None and not allow_owner:
            raise HTTPException(403, '共用會員與帳務管理需要會員管理員登入。')
        if session['member_id'] and members.member(session['member_id'])['role'] != 'admin':
            raise HTTPException(403, '需要管理員權限。')
        return session

    store.admin = admin

    def signed_in(request, member):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = members.member(member['id'])
            if not current['active'] or ('auth_version' in member and member['auth_version'] != current['auth_version']):
                raise HTTPException(401, '帳號狀態已變更，請重新登入。')
            db.execute('DELETE FROM sessions WHERE id=?', (hashlib.sha256(request.cookies.get('qianmi_session', '').encode()).hexdigest(),))
            db.execute('INSERT INTO sessions(id,csrf,expires,member_id,auth_version) VALUES (?,?,?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(), csrf, time.time() + 7 * 86400, member['id'], current['auth_version']))
        response = JSONResponse({'csrf': csrf, 'member': members.public(current)})
        response.set_cookie('qianmi_session', token, httponly=True, samesite='strict', max_age=7 * 86400,
                            secure=bool(public_url) and request.url.hostname not in ('127.0.0.1', 'localhost'), path='/')
        return response

    @app.get('/api/membership')
    def config():
        initialized = members.accounts.initialized()
        return dict(initialized=initialized, **members.settings())

    @app.post('/api/membership/bootstrap')
    async def bootstrap(request: Request):
        session = admin(request, True)
        if session['member_id'] is not None or request.url.hostname not in ('localhost', '127.0.0.1'):
            raise HTTPException(403, '請由主機桌面建立第一位管理員。')
        limited(request)
        return members.public(members.register(await parse_json(request, Registration), bootstrap=True))

    @app.post('/api/membership/register')
    async def register(request: Request):
        limited(request)
        member = members.register(await parse_json(request, Registration))
        return signed_in(request, member)

    @app.post('/api/membership/login')
    async def login(request: Request):
        limited(request)
        return signed_in(request, members.authenticate(await parse_json(request, Credentials)))

    @app.get('/api/membership/me')
    def me(request: Request):
        session = store.session(request)
        return dict(csrf=session['csrf'], member=members.public(members.member(session['member_id'])) if session['member_id'] else None,
                    owner=session['member_id'] is None, **members.settings())

    @app.get('/api/membership/ledger')
    def ledger(request: Request, offset: int = 0):
        session = store.session(request)
        if offset < 0:
            raise HTTPException(422, '頁碼無效。')
        return dict(items=members.points.ledger(session['member_id'], offset) if session['member_id'] else [])

    @app.post('/api/membership/password')
    async def change_password(request: Request):
        session = store.session(request, True)
        limited(request)
        value = await parse_json(request, PasswordChange)
        encoded = password_hash(value.password)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            member = members.member(session['member_id'])
            if not check_password(value.current_password, member['password']):
                raise HTTPException(403, '目前密碼不正確。')
            members.accounts.change_password(member, encoded)
            db.execute('DELETE FROM sessions WHERE member_id=?', (member['id'],))
            members.audit(db, member['id'], member['id'], '修改密碼並登出全部設備')
        return {'ok': True}

    @app.post('/api/membership/reset')
    async def reset_password(request: Request):
        limited(request)
        value = await parse_json(request, PasswordReset)
        encoded = password_hash(value.password)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            member = members.accounts.reset_password(hashlib.sha256(value.token.encode()).hexdigest(), encoded)
            db.execute('DELETE FROM sessions WHERE member_id=?', (member['id'],))
            members.audit(db, member['id'], member['id'], '使用重設碼變更密碼')
        return {'ok': True}

    @app.get('/api/admin/members')
    def list_members(request: Request, search: str = '', offset: int = 0):
        admin(request, allow_owner=False)
        if len(search) > 100 or offset < 0:
            raise HTTPException(422, '搜尋條件無效。')
        rows = members.accounts.list(search, offset)
        return dict(items=[members.public(row | {'balance': members.points.balance(row['id'])}) for row in rows])

    @app.put('/api/admin/members/{member_id}')
    async def update_member(member_id: str, request: Request):
        session = admin(request, True, allow_owner=False)
        value = await parse_json(request, MemberUpdate)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            members.accounts.update(member_id, value.role, value.active)
            db.execute('DELETE FROM sessions WHERE member_id=?', (member_id,))
            members.audit(db, session['member_id'], member_id, f'設定角色 {value.role}，啟用 {value.active}')
        return {'ok': True}

    @app.post('/api/admin/members/{member_id}/credits')
    async def credits(member_id: str, request: Request):
        session = admin(request, True, allow_owner=False)
        value = await parse_json(request, CreditAdjustment)
        if not value.amount or not value.reason.strip():
            raise HTTPException(422, '請填寫非零點數與調整原因。')
        members.points.adjust(member_id, value.amount, value.reason.strip(), session['member_id'], 'admin:' + value.request_id, members.host_id)
        return members.public(members.member(member_id))

    @app.post('/api/admin/members/{member_id}/reset')
    def issue_reset(member_id: str, request: Request):
        session = admin(request, True, allow_owner=False)
        token = secrets.token_urlsafe(32)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            members.accounts.issue_reset(member_id, hashlib.sha256(token.encode()).hexdigest())
            members.audit(db, session['member_id'], member_id, '發出 30 分鐘單次密碼重設碼')
        return dict(token=token, expires_in=1800)

    @app.get('/api/admin/audit')
    def audit(request: Request, offset: int = 0):
        admin(request, allow_owner=False)
        if offset < 0:
            raise HTTPException(422, '頁碼無效。')
        with store.connect() as db:
            rows = db.execute('SELECT id,member_id,actor,action,created FROM member_audit ORDER BY id DESC LIMIT 100 OFFSET ?', (offset,)).fetchall()
        return dict(items=[dict(row) for row in rows], ledger=members.points.ledger(offset=offset, limit=100))

    @app.put('/api/admin/membership')
    async def save_config(request: Request):
        session = admin(request, True, allow_owner=False)
        value = await parse_json(request, MembershipSettings)
        members.points.save_settings(value.model_dump(), session['member_id'])
        with store.connect() as db:
            members.audit(db, session['member_id'], None, f'更新會員設定：圖片 {value.image_points}、影片 {value.video_points}，註冊 {value.registration_open}')
        return value.model_dump()

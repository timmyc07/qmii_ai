"""Authenticated membership gateway for the local GPU workstation."""
from contextlib import asynccontextmanager, closing, contextmanager
from datetime import datetime
import hashlib
import hmac
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlsplit
import warnings

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pymongo.errors import PyMongoError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .settings import Settings, SettingsStore, source_revision
from .parameters import Parameters, validate_parameters, validate_h3_sources, validate_svi_sources
from .cancellation import CancellationFailed, TaskControl
from .drive import Drive, DriveSettings
from .maintenance import CleanupInput, Maintenance, health, workflow_check
from .recipes import RecipeInput, Recipes
from .membership import Members, install_membership
from .accounts import MongoAccounts
from .points import fingerprint

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).parent / 'static'
MAX_IMAGE = 12 * 1024 * 1024
MAX_UPLOAD_PIXELS = 20_000_000
# Full V1's reviewed 4669² output is larger than the upload budget. Keep the
# upload cap explicit before decoding so it does not affect trusted output.
Image.MAX_IMAGE_PIXELS = 24_000_000
LOG = logging.getLogger('qianmi.mobile')


class Login(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str = Field(min_length=1, max_length=128)


class JobOrigin(BaseModel):
    model_config = ConfigDict(extra='forbid')
    platform: str = Field(default='未記錄', min_length=1, max_length=100)
    device: str = Field(default='未命名設備', min_length=1, max_length=100)
    device_id: str = Field(default='', max_length=64, pattern='^[a-zA-Z0-9-]*$')
    user: str = Field(default='未命名使用者', min_length=1, max_length=100)


class JobInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    prompt: str = Field(min_length=1, max_length=8000)
    workflow: str = Field(pattern='^(quick|reference|superduper|nsfw_adv|h3_image|svi_image)$')
    parameters: Parameters | None = None
    precise_mode: bool = False
    origin: JobOrigin = Field(default_factory=JobOrigin)
    images: list[str] = Field(default_factory=list, max_length=4)
    last_image: str | None = Field(default=None, pattern='^[a-f0-9]{32}$')
    request_id: str = Field(pattern='^[a-f0-9]{32}$')


def identifier(value):
    if not re.fullmatch('[a-f0-9]{32}', value):
        raise HTTPException(404, '找不到項目。')
    return value


async def body(request, limit):
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > limit:
            raise HTTPException(413, '上傳內容太大。')
        chunks.extend(chunk)
    return bytes(chunks)


async def parse_json(request, model, limit=40_000):
    if request.headers.get('content-type', '').split(';')[0] != 'application/json':
        raise HTTPException(415, '請使用 JSON 格式。')
    try:
        return model.model_validate_json(await body(request, limit))
    except ValidationError:
        raise HTTPException(422, '輸入格式錯誤，請檢查提示詞與圖片數量。') from None


class Store:
    def __init__(self, state, output, accounts=None):
        self.state, self.output = Path(state), Path(output)
        self.state.mkdir(parents=True, exist_ok=True)
        self.output.mkdir(parents=True, exist_ok=True)
        (self.state / 'uploads').mkdir(exist_ok=True)
        self.database = self.state / 'mobile.sqlite3'
        code_path = self.state / 'access-code.txt'
        if not code_path.exists():
            code_path.write_text(secrets.token_urlsafe(24), encoding='utf-8')
        self.code_hash = hashlib.sha256(code_path.read_text(encoding='utf-8').strip().encode()).digest()
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, csrf TEXT, expires REAL);
                CREATE TABLE IF NOT EXISTS uploads (id TEXT PRIMARY KEY, created REAL);
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, request_id TEXT UNIQUE,
                    status TEXT, message TEXT, prompt TEXT, workflow TEXT, sources TEXT,
                    results TEXT, created REAL, updated REAL, precise_mode INTEGER NOT NULL DEFAULT 0);
            ''')
            # Add history fields once without discarding existing jobs.
            columns = {row['name'] for row in db.execute('PRAGMA table_info(jobs)')}
            for name, definition in [('origin', "TEXT NOT NULL DEFAULT '{}'"),
                                     ('started', 'REAL'), ('finished', 'REAL'),
                                     ('parameters', "TEXT NOT NULL DEFAULT '{}'") ,
                                     ('precise_mode', 'INTEGER NOT NULL DEFAULT 0'), ('last_image', 'TEXT')]:
                if name not in columns:
                    db.execute(f'ALTER TABLE jobs ADD COLUMN {name} {definition}')
                    if name == 'last_image':
                        db.execute("""UPDATE jobs SET last_image=json_extract(sources,'$[1]'),
                                      sources=json_remove(sources,'$[1]') WHERE workflow='h3_image'
                                      AND json_extract(parameters,'$.end_frame')='custom'""")
            if db.execute('PRAGMA user_version').fetchone()[0] < 1:
                for row in db.execute('SELECT * FROM jobs').fetchall():
                    directory = self.output / 'mobile' / row['id']
                    if not directory.is_dir():
                        directory = self.output / row['id']
                    day = datetime.fromtimestamp(row['started'] or row['created'] or time.time()).strftime('%Y-%m-%d')
                    results = self.publish_results(row['id'], directory, json.loads(row['results']), day, {})
                    db.execute('UPDATE jobs SET results=? WHERE id=?', (json.dumps(results), row['id']))
                    if directory.is_dir() and not any(directory.iterdir()):
                        directory.rmdir()
                legacy = self.output / 'mobile'
                if legacy.is_dir() and not any(legacy.iterdir()):
                    legacy.rmdir()
                db.execute('PRAGMA user_version=1')
        account_store = accounts if accounts is not None else MongoAccounts.from_env()
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS host_identity (id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL)')
            db.execute('INSERT OR IGNORE INTO host_identity VALUES (1,?)', (secrets.token_hex(16),))
            db.commit()
            backup = self.state / 'members-before-mongodb.sqlite3'
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='members'").fetchone() and not backup.exists():
                with closing(sqlite3.connect(backup)) as destination:
                    db.backup(destination)
            points_backup = self.state / 'points-before-mongodb.sqlite3'
            if db.execute("SELECT 1 FROM sqlite_master WHERE name IN ('member_wallets','point_ledger')").fetchone() and not points_backup.exists():
                with closing(sqlite3.connect(points_backup)) as destination:
                    db.backup(destination)
        self.members = Members(self.connect, account_store)

    def publish_results(self, job_id, directory, results, day, published):
        paths = []
        for name in results:
            if Path(name).name != name:
                raise ValueError('輸出檔名無效。')
            if name in published:
                paths.append(published[name])
                continue
            relative = f'{day}/{job_id}_{name}'
            source, target = directory / name, self.output / relative
            if source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise FileExistsError('輸出檔案已存在，拒絕覆蓋。')
                source.rename(target)
            published[name] = relative
            paths.append(relative)
        return paths

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def update(self, job_id, status, message, results=None):
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("""UPDATE jobs SET status=?,message=?,updated=?,
                          started=CASE WHEN ?='running' THEN COALESCE(started,?) ELSE started END,
                          finished=CASE WHEN ? IN ('completed','failed','cancelled') THEN ? ELSE finished END,
                          results=COALESCE(?,results) WHERE id=?""",
                       (status, message, now, status, now, status, now,
                        json.dumps(results) if results is not None else None, job_id))
        if status in ('completed', 'failed', 'cancelled'):
            self.settle(job_id)

    @staticmethod
    def billing_job(row):
        return dict(member_id=row['member_id'], request_id=row['request_id'] or row['id'], job_id=row['id'],
                    fingerprint=row['billing_fingerprint'], reserved_points=row['reserved_points'],
                    unit_points=row['unit_points'], auth_version=row['billing_auth_version'], workflow=row['workflow'])

    def confirm_billing(self, job_id):
        row = self.job(job_id)
        if not row['member_id']:
            return
        if row['billing_error']:
            raise HTTPException(row['billing_error'], row['message'])
        if row['status'] in ('completed', 'failed', 'cancelled'):
            self.settle(job_id)
            return
        try:
            record = self.members.points.reserve(self.billing_job(row), self.members.host_id)
        except HTTPException as exc:
            with self.connect() as db:
                db.execute("UPDATE jobs SET status='failed',message=?,billing_status='rejected',billing_error=?,settled=1,finished=? WHERE id=?",
                           (exc.detail, exc.status_code, time.time(), job_id))
            raise
        with self.connect() as db:
            db.execute("UPDATE jobs SET billing_status=? WHERE id=?",
                       ('settled' if record['state'] == 'settled' else 'reserved', job_id))
            if record['state'] == 'settled':
                db.execute("UPDATE jobs SET status='cancelled',settled=1,message='此請求已結算，請勿重複執行。',finished=? WHERE id=? AND status='queued'", (time.time(), job_id))
        row = self.job(job_id)
        if row['status'] in ('completed', 'failed', 'cancelled'):
            self.settle(job_id)

    def settle(self, job_id):
        row = self.job(job_id)
        if row['settled']:
            return
        if row['member_id']:
            extension = '.mp4' if row['workflow'] in ('h3_image', 'svi_image') else '.png'
            count = len({name for name in json.loads(row['results']) if name.endswith(extension)})
            try:
                self.members.points.settle(self.billing_job(row), self.members.host_id, count)
            except (PyMongoError, HTTPException) as exc:
                LOG.warning('Point settlement pending job=%s exception=%s', job_id, type(exc).__name__)
                return
        with self.connect() as db:
            db.execute("UPDATE jobs SET settled=1,billing_status='settled' WHERE id=?", (job_id,))

    def reconcile_points(self):
        with self.connect() as db:
            rows = db.execute("SELECT id FROM jobs WHERE status IN ('completed','failed','cancelled') AND settled=0 LIMIT 30").fetchall()
        for row in rows:
            self.settle(row['id'])

    def session(self, request, mutate=False):
        token = request.cookies.get('qianmi_session', '')
        session_id = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            row = db.execute('SELECT * FROM sessions WHERE id=? AND expires>?', (session_id, time.time())).fetchone()
        if not row:
            raise HTTPException(401, '請先登入會員或主機管理員。')
        if row['member_id']:
            member = self.members.accounts.get(row['member_id'])
            if not member or not member['active'] or row['auth_version'] != member['auth_version']:
                raise HTTPException(401, '會員登入已失效，請重新登入或聯絡管理員。')
        if mutate and not hmac.compare_digest(request.headers.get('x-qianmi-csrf', ''), row['csrf']):
            raise HTTPException(403, '工作階段驗證失敗，請重新整理。')
        return row

    def privileged(self, session):
        if session['member_id'] is None:
            return True
        member = self.members.accounts.get(session['member_id'])
        return bool(member and member['active'] and member['role'] == 'admin')

    def authorize_job(self, job_id, session):
        row = self.job(job_id)
        if row['member_id'] != session['member_id'] and not self.privileged(session):
            raise HTTPException(404, '找不到任務。')
        return row

    def job(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (identifier(job_id),)).fetchone()
        if not row:
            raise HTTPException(404, '找不到任務。')
        return row

    @staticmethod
    def public_job(row):
        sources = json.loads(row['sources'])
        results = json.loads(row['results'])
        return dict(id=row['id'], status=row['status'], message=row['message'], created=row['created'],
                    prompt=row['prompt'], workflow=row['workflow'], parameters=json.loads(row['parameters']),
                    precise_mode=bool(row['precise_mode']),
                    reserved_points=row['reserved_points'], settled=bool(row['settled']),
                    billing_status=row['billing_status'],
                    updated=row['updated'], started=row['started'], finished=row['finished'],
                    origin=json.loads(row['origin']),
                    sources=[f'/api/uploads/{value}' for value in sources], result_files=results,
                    last_image=f'/api/uploads/{row["last_image"]}' if row['last_image'] else None,
                    results=[f'/api/jobs/{row["id"]}/images/{i}' for i in range(len(results))])

    def cleanup(self):
        cutoff = time.time() - 7 * 86400
        with self.connect() as db:
            active = {value for row in db.execute("SELECT sources FROM jobs WHERE status IN ('queued','running','cancelling')")
                      for value in json.loads(row['sources'])}
            active.update(row['last_image'] for row in db.execute("SELECT last_image FROM jobs WHERE status IN ('queued','running','cancelling')")
                          if row['last_image'])
            for row in db.execute('SELECT id FROM uploads WHERE created<?', (cutoff,)).fetchall():
                if row['id'] not in active:
                    (self.state / 'uploads' / f'{row["id"]}.png').unlink(missing_ok=True)
                    db.execute('DELETE FROM uploads WHERE id=?', (row['id'],))
            # Finished jobs and artwork are permanent host data. Only temporary
            # uploads and expired sessions are eligible for automatic cleanup.
            db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))


def create_app(state_dir=None, output_dir=None, runner=None, public_url=None, settings_path=None, library_dir=None, accounts=None):
    revision = source_revision()
    store = Store(state_dir or ROOT / '.runtime' / 'mobile', output_dir or ROOT / 'output', accounts)
    drive = Drive(store.state, store.output)
    settings = SettingsStore(settings_path)
    maintenance = Maintenance(store)
    recipes = Recipes(store.state / 'recipes.json')
    library = Path(library_dir or (ROOT / 'output' if output_dir is None else output_dir)).resolve()

    def artworks():
        found = []
        for path in library.rglob('*'):
            if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.mp4') or not path.is_file():
                continue
            if not path.resolve().is_relative_to(library) or path.is_symlink():
                continue
            key = hashlib.sha256(path.relative_to(library).as_posix().encode()).hexdigest()
            found.append((key, path, path.stat().st_mtime))
        return sorted(found, key=lambda item: (-item[2], item[0]))

    def member_artworks(session):
        files = artworks()
        if store.privileged(session):
            return files
        with store.connect() as db:
            allowed = {name for row in db.execute('SELECT results FROM jobs WHERE member_id=?', (session['member_id'],))
                       for name in json.loads(row['results'])}
        return [item for item in files if item[1].relative_to(library).as_posix() in allowed]
    public_url = (public_url or os.environ.get('QIANMI_PUBLIC_URL', '')).rstrip('/')
    if public_url and (urlsplit(public_url).scheme != 'https' or not urlsplit(public_url).hostname):
        raise ValueError('QIANMI_PUBLIC_URL must be an HTTPS origin')
    origins = {'http://127.0.0.1:8787', 'http://localhost:8787'}
    hosts = ['127.0.0.1', 'localhost']
    if public_url:
        origins.add(public_url)
        hosts.append(urlsplit(public_url).hostname)
    stop = threading.Event()
    wake = threading.Event()
    attempts = []
    controls = {}
    control_lock = threading.Lock()

    def worker():
        last_cleanup = time.monotonic()
        while not stop.is_set():
            store.reconcile_points()
            with control_lock:
                with store.connect() as db:
                    row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                if row:
                    try:
                        store.confirm_billing(row['id'])
                    except PyMongoError:
                        row = None
                    except HTTPException:
                        continue
                    if row:
                        row = store.job(row['id'])
                        if row['status'] != 'queued':
                            continue
                if row:
                    if row['member_id']:
                        try:
                            member = store.members.accounts.get(row['member_id'])
                        except PyMongoError:
                            member = None
                            row = None  # Keep the reservation queued while the account authority is unavailable.
                        if row and (not member or not member['active']):
                            store.update(row['id'], 'cancelled', '會員帳號已停用，任務已取消，未完成輸出將退點。')
                            continue
                if row:
                    control = controls[row['id']] = TaskControl()
                    store.update(row['id'], 'running', '正在準備電腦…')
            if not row:
                if time.monotonic() - last_cleanup > 3600:
                    try:
                        store.cleanup()
                    except OSError:
                        LOG.warning('Retention cleanup postponed')
                    last_cleanup = time.monotonic()
                wake.wait(1)
                wake.clear()
                continue
            job_id = row['id']
            output = store.state / 'results' / job_id
            published = {}
            LOG.info('Job started id=%s workflow=%s', job_id, row['workflow'])
            try:
                payload = dict(prompt=row['prompt'], workflow=row['workflow'], parameters=json.loads(row['parameters']),
                               precise_mode=bool(row['precise_mode']), _control=control)
                if row['last_image']:
                    payload['last_image'] = store.state / 'uploads' / f'{row["last_image"]}.png'
                sources = [store.state / 'uploads' / f'{value}.png' for value in json.loads(row['sources'])]
                output.mkdir(parents=True, exist_ok=True)
                def progress(message, results=None):
                    if results is not None:
                        results = store.publish_results(job_id, output, results, datetime.now().strftime('%Y-%m-%d'), published)
                    store.update(job_id, 'cancelling' if control.cancelled.is_set() else 'running', message, results)
                    if results:
                        drive.wake.set()
                    control.check()
                if runner is None:
                    from .generation import generate
                    results = generate(payload, sources, output, progress)
                else:
                    results = runner(payload, sources, output, progress)
                results = store.publish_results(job_id, output, results, datetime.now().strftime('%Y-%m-%d'), published)
                drive.wake.set()
                with control_lock:
                    cancelled = control.cancelled.is_set()
                    store.update(job_id, 'cancelled' if cancelled else 'completed',
                                 '任務已終止，已完成的輸出仍保留。' if cancelled else
                                 '影片完成，生成資源已釋放，可以播放與下載了。' if row['workflow'] == 'svi_image' else
                                 '影片完成，可以播放與下載了。' if row['workflow'].startswith('h3_') else '圖片完成，可以下載了。', results)
                LOG.info('Job finished id=%s count=%s cancelled=%s', job_id, len(results), cancelled)
            except Exception as exc:
                # Upstream errors can contain prompts; log only the exception class.
                from .superduper import ComfyWorkflowError
                with control_lock:
                    if isinstance(exc, CancellationFailed):
                        stop.set()
                    cancelled = control.cancelled.is_set() and not isinstance(exc, CancellationFailed)
                    message = '任務已終止，已完成的輸出仍保留。' if cancelled else str(exc) if isinstance(exc, (ComfyWorkflowError, CancellationFailed)) else '生成失敗，請確認電腦的模型服務與顯示卡狀態。'
                    if isinstance(exc, CancellationFailed):
                        message += '佇列已停止，請確認模型停止後重新啟動工作室。'
                    store.update(job_id, 'cancelled' if cancelled else 'failed', message)
                if cancelled:
                    LOG.info('Job cancelled id=%s', job_id)
                else:
                    LOG.error('Job failed id=%s exception=%s', job_id, type(exc).__name__)
            finally:
                with control_lock:
                    controls.pop(job_id, None)
                if output.is_dir() and not any(output.iterdir()):
                    output.rmdir()
            try:
                store.cleanup()
            except OSError:
                LOG.warning('Retention cleanup postponed')

    @asynccontextmanager
    async def lifespan(app):
        with store.connect() as db:
            interrupted = db.execute("SELECT id FROM jobs WHERE status IN ('running','cancelling')").fetchall()
        for row in interrupted:
            store.update(row['id'], 'failed', '電腦服務已重新啟動，未完成輸出將自動退點，請重新提交。')
        store.cleanup()
        thread = threading.Thread(target=worker, daemon=True, name='qianmi-gpu-worker')
        app.state.worker = thread
        thread.start()
        upload_thread = threading.Thread(target=drive.run, args=(stop,), daemon=True, name='qianmi-drive-upload')
        upload_thread.start()
        LOG.info('Mobile service ready')
        yield
        stop.set()
        wake.set()
        drive.wake.set()
        thread.join()
        upload_thread.join()
        store.members.accounts.close()
        LOG.info('Mobile service stopped')

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.drive = drive
    install_membership(app, store, parse_json, public_url)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts, www_redirect=False)

    @app.exception_handler(PyMongoError)
    async def account_unavailable(request, exc):
        LOG.warning('Account database unavailable exception=%s', type(exc).__name__)
        return JSONResponse({'detail': '會員資料庫暫時無法連線，請稍後重試。'}, status_code=503)

    @app.middleware('http')
    async def security(request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('origin') not in origins:
            return JSONResponse({'detail': '不允許跨站請求。'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api/') else 'no-cache'
        return response

    @app.post('/api/login')
    async def login(request: Request):
        now = time.monotonic()
        attempts[:] = [value for value in attempts if value > now - 300]
        if len(attempts) >= 10:
            raise HTTPException(429, '登入嘗試過多，請五分鐘後再試。')
        value = await parse_json(request, Login)
        if not hmac.compare_digest(hashlib.sha256(value.code.strip().encode()).digest(), store.code_hash):
            attempts.append(now)
            LOG.warning('Pairing denied')
            raise HTTPException(401, '連線碼不正確。')
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with store.connect() as db:
            db.execute('INSERT INTO sessions(id,csrf,expires) VALUES (?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(), csrf, time.time() + 7 * 86400))
        response = JSONResponse({'csrf': csrf})
        response.set_cookie('qianmi_session', token, httponly=True,
                            secure=bool(public_url) and request.url.hostname not in ('127.0.0.1', 'localhost'),
                            samesite='strict', max_age=7 * 86400, path='/')
        LOG.info('Device paired')
        return response

    @app.get('/api/session')
    def session(request: Request):
        row = store.session(request)
        return dict(csrf=row['csrf'], api_version=8, source_revision=revision,
                    member=store.members.public(store.members.member(row['member_id'])) if row['member_id'] else None,
                    owner=row['member_id'] is None, **settings.read())

    @app.get('/api/settings')
    def read_settings(request: Request):
        store.session(request)
        return settings.read()

    @app.put('/api/settings')
    async def save_settings(request: Request):
        store.admin(request, mutate=True)
        value = await parse_json(request, Settings, 4_000_000)
        try:
            return settings.save(value.model_dump())
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get('/api/drive')
    def drive_status(request: Request):
        store.admin(request)
        return drive.status()

    @app.get('/api/health')
    def workflow_health(request: Request):
        store.admin(request)
        return health()

    @app.get('/api/storage')
    def storage_status(request: Request):
        store.admin(request)
        return maintenance.storage()

    @app.post('/api/storage/preview')
    async def preview_cleanup(request: Request):
        store.admin(request, mutate=True)
        value = await parse_json(request, CleanupInput)
        return maintenance.preview(value.days)

    @app.post('/api/storage/cleanup')
    async def cleanup_storage(request: Request):
        store.admin(request, mutate=True)
        value = await parse_json(request, CleanupInput)
        try:
            return maintenance.cleanup(value.token)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get('/api/recipes')
    def read_recipes(request: Request):
        store.session(request)
        return dict(recipes=recipes.read())

    @app.post('/api/recipes')
    async def save_recipe(request: Request):
        store.admin(request, mutate=True)
        value = await parse_json(request, RecipeInput, 160_000)
        try:
            return recipes.change(recipe=value)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.delete('/api/recipes/{recipe_id}')
    def delete_recipe(recipe_id: str, request: Request):
        store.admin(request, mutate=True)
        return recipes.change(recipe_id=identifier(recipe_id))

    @app.put('/api/drive')
    async def save_drive(request: Request):
        store.admin(request, mutate=True)
        value = await parse_json(request, DriveSettings)
        return drive.save(value)

    @app.get('/api/library')
    def list_library(request: Request, offset: int = 0):
        session = store.session(request)
        if offset < 0:
            raise HTTPException(422, '作品頁碼無效。')
        files = member_artworks(session)
        return dict(items=[dict(id=key, url=f'/api/library/{key}', created=created,
                               media_type='video' if path.suffix.lower() == '.mp4' else 'image')
                           for key, path, created in files[offset:offset + 40]],
                    next=offset + 40 if len(files) > offset + 40 else None)

    @app.get('/api/library/{artwork_id}')
    def library_image(artwork_id: str, request: Request):
        session = store.session(request)
        if not re.fullmatch('[a-f0-9]{64}', artwork_id):
            raise HTTPException(404, '找不到作品。')
        for key, path, _ in member_artworks(session):
            if key == artwork_id:
                return FileResponse(path, filename=f'千迷AI-{key[:12]}{path.suffix.lower()}',
                                    content_disposition_type='inline')
        raise HTTPException(404, '找不到作品。')

    @app.post('/api/logout')
    def logout(request: Request):
        row = store.session(request, mutate=True)
        with store.connect() as db:
            db.execute('DELETE FROM sessions WHERE id=?', (row['id'],))
        response = JSONResponse({'ok': True})
        response.delete_cookie('qianmi_session')
        return response

    @app.post('/api/uploads')
    async def upload(request: Request):
        session = store.session(request, mutate=True)
        with store.connect() as db:
            count = db.execute('SELECT COUNT(*) FROM uploads WHERE created>?', (time.time() - 86400,)).fetchone()[0]
        if count >= 200:
            raise HTTPException(429, '今日圖片上傳量已達上限。')
        if sum(file.stat().st_size for file in (store.state / 'uploads').glob('*.png')) > 2 * 1024**3:
            raise HTTPException(429, '暫存圖片空間已滿，請在電腦清理舊圖片。')
        data = await body(request, MAX_IMAGE)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    if image.format not in ('PNG', 'JPEG', 'WEBP', 'BMP'):
                        raise ValueError('format')
                    if image.width * image.height > MAX_UPLOAD_PIXELS:
                        raise ValueError('pixels')
                    image.load()
                    clean = ImageOps.exif_transpose(image).convert('RGB')
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise HTTPException(422, '請上傳有效的 JPG、PNG、WebP 或 BMP，最多 2000 萬像素。') from None
        upload_id = secrets.token_hex(16)
        clean.save(store.state / 'uploads' / f'{upload_id}.png', format='PNG')
        with store.connect() as db:
            db.execute('INSERT INTO uploads(id,created,member_id) VALUES (?,?,?)', (upload_id, time.time(), session['member_id']))
        return {'id': upload_id, 'url': f'/api/uploads/{upload_id}'}

    @app.get('/api/uploads/{upload_id}')
    def uploaded_image(upload_id: str, request: Request):
        session = store.session(request)
        with store.connect() as db:
            row = db.execute('SELECT * FROM uploads WHERE id=?', (identifier(upload_id),)).fetchone()
        if not row or (row['member_id'] != session['member_id'] and not store.privileged(session)):
            raise HTTPException(404, '找不到圖片。')
        path = store.state / 'uploads' / f'{identifier(upload_id)}.png'
        if not path.is_file():
            raise HTTPException(404, '找不到圖片。')
        return FileResponse(path, media_type='image/png')

    @app.post('/api/jobs')
    async def submit(request: Request):
        session = store.session(request, mutate=True)
        if stop.is_set():
            raise HTTPException(503, '電腦服務已停止接收任務，請檢查主機狀態後重新連線。')
        value = await parse_json(request, JobInput, limit=160_000)
        if not value.prompt.strip():
            raise HTTPException(422, '請輸入提示詞。')
        if value.workflow == 'reference' and len(value.images) < 2:
            raise HTTPException(422, '多圖參考生成至少需要 2 張參考圖片。')
        try:
            defaults = settings.read()['generation'].get(value.workflow, {})
            parameters = validate_parameters(value.parameters.model_dump(exclude_none=True) if value.parameters is not None
                                             else {k: v for k, v in defaults.items() if v is not None}, value.workflow)
            if value.workflow == 'h3_image':
                validate_h3_sources(parameters, value.images, value.last_image)
            elif value.workflow == 'svi_image':
                validate_svi_sources(parameters, value.images, value.last_image)
                from .svi import validate_loras
                validate_loras(parameters)
                if value.precise_mode:
                    raise ValueError('高耗能影片模式使用三段提示詞，不套用圖片精準模式。')
            elif value.last_image is not None:
                raise ValueError('尾幀圖片僅適用於圖片生影片模式。')
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        reserved, unit = store.members.quote(session, value)
        job_id = hashlib.sha256((session['member_id'] + ':' + value.request_id).encode()).hexdigest()[:32] if session['member_id'] else secrets.token_hex(16)
        now = time.time()
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM jobs WHERE request_id=?', (value.request_id,)).fetchone()
            if previous:
                store.authorize_job(previous['id'], session)
            if not previous and runner is None:
                check = workflow_check(value.workflow, parameters, bool(value.images))
                if not check['ready']:
                    raise HTTPException(409, '此工作流尚未就緒：' + '、'.join(check['missing']) + '。' + check['repair'])
            count = db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running','cancelling')").fetchone()[0]
            if count >= 8 and not previous:
                raise HTTPException(429, '電腦目前排隊已滿，請稍後再試。')
            for upload_id in value.images + ([value.last_image] if value.last_image else []):
                identifier(upload_id)
                upload = db.execute('SELECT * FROM uploads WHERE id=?', (upload_id,)).fetchone()
                if not upload or (upload['member_id'] != session['member_id'] and not store.privileged(session)):
                    raise HTTPException(422, '找不到上傳圖片，請重新選擇。')
            hashes = [hashlib.sha256((store.state / 'uploads' / f'{key}.png').read_bytes()).hexdigest()
                      for key in value.images + ([value.last_image] if value.last_image else [])]
            signature = fingerprint([value.workflow, value.prompt, parameters, value.precise_mode, hashes])
            if previous:
                if previous['billing_fingerprint'] != signature:
                    raise HTTPException(409, '此請求編號已用於不同的生成內容。')
                job_id = previous['id']
            else:
                if session['member_id']:
                    value.origin.user = store.members.accounts.get(session['member_id'])['name']
                db.execute('INSERT INTO jobs (id,request_id,status,message,prompt,workflow,sources,results,created,updated,origin,parameters,precise_mode,last_image,member_id,reserved_points,unit_points,billing_fingerprint,billing_auth_version,billing_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (job_id, value.request_id, 'queued', '已排隊，正在確認共用點數…', value.prompt,
                            value.workflow, json.dumps(value.images), '[]', now, now, json.dumps(value.origin.model_dump()),
                            json.dumps(parameters), int(value.precise_mode), value.last_image, session['member_id'], reserved, unit,
                            signature, session['auth_version'], 'pending' if session['member_id'] else 'exempt'))
        with control_lock:
            store.confirm_billing(job_id)
        wake.set()
        LOG.info('Job queued id=%s', job_id)
        return store.public_job(store.job(job_id))

    @app.get('/api/jobs')
    def jobs(request: Request):
        session = store.session(request)
        with store.connect() as db:
            rows = db.execute('SELECT * FROM jobs WHERE ? OR member_id=? ORDER BY created DESC LIMIT 30',
                              (store.privileged(session), session['member_id'])).fetchall()
        return {'jobs': [store.public_job(row) for row in reversed(rows)]}

    @app.get('/api/jobs/{job_id}')
    def job(job_id: str, request: Request):
        session = store.session(request)
        return store.public_job(store.authorize_job(job_id, session))

    @app.post('/api/jobs/{job_id}/cancel')
    def cancel_job(job_id: str, request: Request):
        session = store.session(request, mutate=True)
        with control_lock:
            row = store.authorize_job(job_id, session)
            if row['status'] == 'queued':
                store.update(job_id, 'cancelled', '任務已終止，未開始生成。')
            elif row['status'] in ('running', 'cancelling') and job_id in controls:
                store.update(job_id, 'cancelling', '正在強制終止，等待模型停止…')
                controls[job_id].cancelled.set()
        return store.public_job(store.job(job_id))

    @app.get('/api/jobs/{job_id}/images/{index}')
    def result(job_id: str, index: int, request: Request):
        session = store.session(request)
        row = store.authorize_job(job_id, session)
        results = json.loads(row['results'])
        if not 0 <= index < len(results):
            raise HTTPException(404, '圖片尚未完成。')
        path = store.output / results[index]
        return FileResponse(path, media_type='video/mp4' if path.suffix == '.mp4' else 'image/png', filename=f'千迷AI-{job_id[:8]}-{index + 1}{path.suffix}',
                            content_disposition_type='inline')

    @app.get('/')
    def home():
        return FileResponse(STATIC / 'index.html')

    @app.post('/api/control/drain')
    def drain(request: Request):
        supplied = hashlib.sha256(request.headers.get('x-qianmi-control', '').encode()).digest()
        if request.url.hostname not in ('127.0.0.1', 'localhost') or not hmac.compare_digest(supplied, store.code_hash):
            raise HTTPException(403, '不允許此操作。')
        stop.set()
        wake.set()
        drive.wake.set()
        shutdown = getattr(app.state, 'request_shutdown', None)
        if shutdown and not getattr(app.state, 'shutdown_started', False):
            app.state.shutdown_started = True
            shutdown()
        return {'busy': app.state.worker.is_alive()}

    @app.get('/sw.js')
    def service_worker():
        return FileResponse(STATIC / 'sw.js', media_type='application/javascript')

    @app.get('/static/membership.js')
    def membership_script():
        return FileResponse(ROOT / 'src' / 'membership.js', media_type='application/javascript')

    @app.get('/static/membership.css')
    def membership_style():
        return FileResponse(ROOT / 'src' / 'membership.css', media_type='text/css')

    app.mount('/static', StaticFiles(directory=STATIC), name='static')
    return app


def main():
    import uvicorn
    state = ROOT / '.runtime' / 'mobile'
    state.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(state / 'server.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    LOG.setLevel(logging.INFO)
    LOG.addHandler(handler)
    # shortcut: exactly one process owns this personal workstation queue.
    from .gpu import gpu_lock
    with gpu_lock(timeout=0, path=state / 'server-instance.lock'):
        application = create_app()
        server = uvicorn.Server(uvicorn.Config(application, host='127.0.0.1', port=8787, workers=1,
                                              access_log=False, proxy_headers=True,
                                              forwarded_allow_ips='127.0.0.1', log_level='warning'))
        def request_shutdown():
            def finish():
                application.state.worker.join()
                server.should_exit = True
            threading.Thread(target=finish, daemon=True).start()
        application.state.request_shutdown = request_shutdown
        server.run()


if __name__ == '__main__':
    main()

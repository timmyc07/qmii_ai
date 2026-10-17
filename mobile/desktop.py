"""Private stdin/stdout bridge: desktop submits through the studio API too."""
import getpass
import platform
import uuid
import http.cookiejar
import json
import re
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

from .settings import ROOT, SettingsStore, source_revision

URL = 'http://127.0.0.1:8787'


def service_script(name, public=False):
    args = ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(ROOT / 'tools' / name)]
    if public:
        args.append('-Public')
    result = subprocess.run(args, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('工作室服務更新失敗，請檢查主機連線日誌。')


def restart_service():
    saved = ROOT / '.runtime' / 'mobile' / 'processes.json'
    if not saved.is_file():
        raise RuntimeError('工作室服務未登記，請先在「手機連線」停止後重新開啟。')
    public = bool(json.loads(saved.read_text(encoding='utf-8-sig')).get('publicUrl'))
    service_script('stop-mobile.ps1')
    service_script('start-mobile.ps1', public=public)


def desktop_origin():
    host = platform.node()
    return dict(platform=f'{platform.system()} 桌面', device=host[:100] or '本機電腦',
                device_id=uuid.uuid5(uuid.NAMESPACE_DNS, host).hex, user=getpass.getuser()[:100])


class StudioClient:
    def __init__(self, url=URL, code_path=None, member=False):
        self.url = url
        self.member = member
        self.code_path = Path(code_path or ROOT / '.runtime' / 'mobile' / 'access-code.txt')
        self.cookies = http.cookiejar.LWPCookieJar(str(self.code_path.parent / 'desktop-session.cookies')) if member else http.cookiejar.CookieJar()
        if member and Path(self.cookies.filename).is_file():
            self.cookies.load(ignore_discard=True)
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.csrf = ''

    def request(self, path, value=None, raw=None, method=None):
        data = raw if raw is not None else (json.dumps(value).encode() if value is not None else None)
        request = urllib.request.Request(self.url + path, data=data, method=method,
                                         headers={'Origin': URL, 'X-Qianmi-CSRF': self.csrf,
                                                  'Content-Type': 'application/octet-stream' if raw is not None else 'application/json'})
        try:
            with self.opener.open(request, timeout=120 if path == '/api/storage' else 15) as response:
                value = json.load(response)
                if self.member and path in ('/api/membership/login', '/api/membership/register', '/api/logout'):
                    self.cookies.save(ignore_discard=True)
                return value
        except urllib.error.HTTPError as exc:
            try:
                detail = json.load(exc).get('detail', '工作室請求失敗。')
            except (ValueError, OSError):
                detail = '工作室請求失敗。'
            raise RuntimeError(detail) from None

    def connect(self):
        try:
            with urllib.request.urlopen(self.url, timeout=2):
                pass
        except OSError:
            # The existing lifecycle script registers ownership for safe drain
            # and can subsequently be restarted with the HTTPS tunnel enabled.
            service_script('start-mobile.ps1')
        if self.member:
            session = self.request('/api/session')
            if session.get('api_version') != 8 or session.get('source_revision') != source_revision():
                raise RuntimeError('工作室服務版本已變更，請先在手機連線中重新啟動服務。')
            self.csrf = session['csrf']
            return
        code = self.code_path.read_text(encoding='utf-8').strip()
        self.csrf = self.request('/api/login', {'code': code})['csrf']
        session = self.request('/api/session')
        if session.get('api_version') != 8 or session.get('source_revision') != source_revision():
            self.request('/api/logout', method='POST')
            self.csrf = ''
            if self.url != URL or self.code_path != ROOT / '.runtime' / 'mobile' / 'access-code.txt':
                raise RuntimeError('工作室服務仍是舊版本，請在「手機連線」先停止，再重新開啟服務。')
            restart_service()
            self.csrf = self.request('/api/login', {'code': code})['csrf']
            session = self.request('/api/session')
            if session.get('api_version') != 8 or session.get('source_revision') != source_revision():
                raise RuntimeError('工作室服務版本未更新，請檢查主機連線日誌。')


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def main():
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    action = sys.argv[1]
    if action == 'load_settings':
        emit(SettingsStore().read())
        return
    payload = json.load(sys.stdin) if action in ('save_settings', 'generate', 'cancel', 'import_svi_lora', 'connect_drive', 'save_drive', 'studio_tools', 'membership') else {}
    if action == 'save_settings':
        emit(SettingsStore().save(payload))
        return
    if action == 'import_svi_lora':
        from .svi import import_lora
        emit({'name': import_lora(payload['path'])})
        return
    if action == 'connect_drive':
        from .drive import Drive
        emit(Drive(ROOT / '.runtime/mobile', ROOT / 'output').connect(payload['path']))
        return
    if action == 'membership':
        membership_action(payload)
        return
    client = StudioClient(member=True) if action in ('generate', 'jobs', 'cancel') else StudioClient()
    client.connect()
    try:
        if action == 'studio_tools':
            routes = {'health': ('GET', '/api/health'), 'storage': ('GET', '/api/storage'),
                      'preview': ('POST', '/api/storage/preview'), 'cleanup': ('POST', '/api/storage/cleanup'),
                      'recipes': ('GET', '/api/recipes'), 'save_recipe': ('POST', '/api/recipes'),
                      'delete_recipe': ('DELETE', '/api/recipes/' + payload.get('value', {}).get('id', ''))}
            if payload['action'] not in routes:
                raise ValueError('不支援的工作室管理操作。')
            method, path = routes[payload['action']]
            emit(client.request(path, payload.get('value', {}) if method == 'POST' else None, method=method))
            return
        if action in ('drive_status', 'save_drive'):
            emit(client.request('/api/drive', payload if action == 'save_drive' else None,
                                method='PUT' if action == 'save_drive' else 'GET'))
            return
        if action == 'cancel':
            emit(client.request('/api/jobs/' + payload['job_id'] + '/cancel', {}, method='POST'))
            return
        if action == 'jobs':
            value = client.request('/api/jobs')
            for job in value['jobs']:
                job['results'] = [str(ROOT / 'output' / name) for name in job['result_files']]
            emit(value)
            return
        images = []
        last_image = None
        for name in payload['images'] + ([payload['last_image']] if payload.get('last_image') else []):
            path = Path(name)
            if path.stat().st_size > 12 * 1024 * 1024:
                raise RuntimeError('單張圖片不可超過 12 MB。')
            images.append(client.request('/api/uploads', raw=path.read_bytes())['id'])
        if payload.get('last_image'):
            last_image = images.pop()
        job = client.request('/api/jobs', dict(prompt=payload['prompt'], workflow=payload['workflow'],
                                             parameters=payload.get('parameters', {}),
                                             precise_mode=payload.get('precise_mode', False), images=images, last_image=last_image,
                                             request_id=secrets.token_hex(16), origin=desktop_origin()))
        seen = 0
        total = 1 if payload['workflow'] == 'reference' else max(1, len(images))
        while True:
            for index in range(seen, len(job['results'])):
                name = job['result_files'][index]
                video = name.endswith('.mp4')
                path = str(ROOT / 'output' / name)
                emit(dict(index=index + 1, total=total, message='影片完成' if video else '圖片完成', done=False, error=None,
                          image=None if video else path, video=path if video else None))
            seen = len(job['results'])
            done = job['status'] in ('completed', 'failed', 'cancelled')
            emit(dict(index=seen, total=total, message=job['message'], done=done, image=None,
                      jobId=job['id'],
                      error=job['message'] if job['status'] == 'failed' else None))
            if done:
                break
            time.sleep(1)
            # Switching the local studio to HTTPS safely drains and restarts
            # the same persistent queue. Allow the lifecycle operation to finish.
            for attempt in range(30):
                try:
                    job = client.request('/api/jobs/' + job['id'])
                    break
                except (OSError, RuntimeError):
                    if attempt == 29:
                        raise RuntimeError('主機連線中斷，請在共用任務中確認結果，避免重複提交。') from None
                    time.sleep(1)
    finally:
        if action not in ('generate', 'jobs', 'cancel'):
            client.request('/api/logout', method='POST')


def membership_action(payload):
    action, value = payload['action'], dict(payload.get('value', {}))
    routes = {'config': ('GET', '/api/membership'), 'me': ('GET', '/api/membership/me'),
              'login': ('POST', '/api/membership/login'), 'register': ('POST', '/api/membership/register'),
              'logout': ('POST', '/api/logout'), 'password': ('POST', '/api/membership/password'),
              'reset': ('POST', '/api/membership/reset'), 'ledger': ('GET', '/api/membership/ledger'),
              'members': ('GET', '/api/admin/members'), 'audit': ('GET', '/api/admin/audit'),
              'settings': ('PUT', '/api/admin/membership'), 'bootstrap': ('POST', '/api/membership/bootstrap')}
    member_id = value.pop('id', '')
    if action in ('update', 'credits', 'issue_reset'):
        if not re.fullmatch('[a-f0-9]{32}', member_id):
            raise ValueError('會員編號無效。')
        routes[action] = ('PUT' if action == 'update' else 'POST', '/api/admin/members/' + member_id +
                          {'update': '', 'credits': '/credits', 'issue_reset': '/reset'}[action])
    if action not in routes:
        raise ValueError('不支援的會員操作。')
    method, path = routes[action]
    client = StudioClient(member=action not in ('bootstrap', 'config'))
    if action not in ('login', 'register', 'reset'):
        client.connect()
    if method == 'GET' and value:
        path += '?' + urlencode(value)
    try:
        emit(client.request(path, value if method != 'GET' else None, method=method))
    finally:
        if action in ('bootstrap', 'config'):
            client.request('/api/logout', method='POST')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Only bounded user-facing errors; never echo upstream prompts or tokens.
        print(str(exc) if isinstance(exc, (RuntimeError, ValueError)) else '無法連接工作室，請檢查主機狀態。', file=sys.stderr)
        raise SystemExit(1)

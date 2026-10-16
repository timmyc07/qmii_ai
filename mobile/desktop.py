"""Private stdin/stdout bridge: desktop submits through the studio API too."""
import getpass
import platform
import uuid
import http.cookiejar
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request

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
    def __init__(self, url=URL, code_path=None):
        self.url = url
        self.code_path = Path(code_path or ROOT / '.runtime' / 'mobile' / 'access-code.txt')
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = ''

    def request(self, path, value=None, raw=None, method=None):
        data = raw if raw is not None else (json.dumps(value).encode() if value is not None else None)
        request = urllib.request.Request(self.url + path, data=data, method=method,
                                         headers={'Origin': URL, 'X-Qianmi-CSRF': self.csrf,
                                                  'Content-Type': 'application/octet-stream' if raw is not None else 'application/json'})
        try:
            with self.opener.open(request, timeout=15) as response:
                return json.load(response)
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
    payload = json.load(sys.stdin) if action in ('save_settings', 'generate') else {}
    if action == 'save_settings':
        emit(SettingsStore().save(payload))
        return
    client = StudioClient()
    client.connect()
    try:
        if action == 'jobs':
            value = client.request('/api/jobs')
            for job in value['jobs']:
                job['results'] = [str(ROOT / 'output' / 'mobile' / job['id'] / f'{i}.png')
                                  for i in range(len(job['results']))]
            emit(value)
            return
        images = []
        for name in payload['images']:
            path = Path(name)
            if path.stat().st_size > 12 * 1024 * 1024:
                raise RuntimeError('單張圖片不可超過 12 MB。')
            images.append(client.request('/api/uploads', raw=path.read_bytes())['id'])
        job = client.request('/api/jobs', dict(prompt=payload['prompt'], workflow=payload['workflow'],
                                             parameters=payload.get('parameters', {}),
                                             precise_mode=payload.get('precise_mode', False), images=images,
                                             request_id=secrets.token_hex(16), origin=desktop_origin()))
        seen = 0
        total = 1 if payload['workflow'] == 'reference' else max(1, len(images))
        while True:
            for index in range(seen, len(job['results'])):
                emit(dict(index=index + 1, total=total, message='圖片完成', done=False, error=None,
                          image=str(ROOT / 'output' / 'mobile' / job['id'] / f'{index}.png')))
            seen = len(job['results'])
            done = job['status'] in ('completed', 'failed')
            emit(dict(index=seen, total=total, message=job['message'], done=done, image=None,
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
        client.request('/api/logout', method='POST')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Only bounded user-facing errors; never echo upstream prompts or tokens.
        print(str(exc) if isinstance(exc, (RuntimeError, ValueError)) else '無法連接工作室，請檢查主機狀態。', file=sys.stderr)
        raise SystemExit(1)

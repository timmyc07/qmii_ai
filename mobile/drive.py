"""Upload finished, date-grouped artwork through rclone's Google Drive backend."""
import configparser
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from urllib.request import urlopen
import zipfile

from pydantic import BaseModel, ConfigDict, Field

from .gpu import gpu_lock

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'v1.75.2'
ARCHIVE = f'rclone-{VERSION}-windows-amd64.zip'
SHA256 = '8a9db2bad1dc79a65b3348fd857069598e2aab7cf4d118b77b1df23055aff818'
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def ensure_rclone():
    directory = ROOT / '.runtime' / 'rclone'
    executable = directory / 'rclone.exe'
    with gpu_lock(path=directory / 'install.lock', timeout=120):
        if executable.is_file():
            return executable
        archive = directory / 'download.zip'
        temporary = directory / 'rclone.tmp'
        try:
            with urlopen(f'https://github.com/rclone/rclone/releases/download/{VERSION}/{ARCHIVE}', timeout=60) as response, archive.open('wb') as target:
                shutil.copyfileobj(response, target)
            with archive.open('rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != SHA256:
                    raise ValueError('rclone 下載校驗失敗。')
            with zipfile.ZipFile(archive) as package, package.open(f'rclone-{VERSION}-windows-amd64/rclone.exe') as source, temporary.open('wb') as target:
                shutil.copyfileobj(source, target)
            temporary.replace(executable)
        finally:
            archive.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)
    return executable


class DriveSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = True
    folder_id: str = Field(default='1LQUNBvxtG6ONE7hAO_s8m6l5eicsRlza', min_length=10, max_length=200,
                           pattern='^[a-zA-Z0-9_-]+$')


class Drive:
    def __init__(self, state, output):
        self.directory = Path(state) / 'drive'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.output = Path(output)
        self.settings_path = self.directory / 'settings.json'
        self.config = self.directory / 'rclone.conf'
        self.wake = threading.Event()
        self.uploading = False
        self.message = '等待背景上傳…'
        self.last_success = None

    def read(self):
        return DriveSettings.model_validate_json(self.settings_path.read_bytes()) if self.settings_path.is_file() else DriveSettings()

    def save(self, settings):
        with gpu_lock(path=self.directory / 'settings.lock', timeout=10):
            temporary = self.settings_path.with_suffix('.tmp')
            temporary.write_text(settings.model_dump_json(), encoding='utf-8')
            temporary.replace(self.settings_path)
        self.wake.set()
        return self.status()

    def connected(self):
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(self.config, encoding='utf-8')
        return bool(parser.get('qianmi', 'token', fallback=''))

    def status(self):
        settings = self.read()
        connected = self.connected()
        return dict(**settings.model_dump(), connected=connected, uploading=self.uploading,
                    message=self.message if connected and settings.enabled else '自動上傳已關閉。' if not settings.enabled else '等待 Google Drive 授權。',
                    last_success=self.last_success)

    def connect(self, path):
        source = Path(path)
        if source.suffix.lower() != '.json' or source.stat().st_size > 65536:
            raise ValueError('請選擇 Google OAuth 桌面應用程式 JSON。')
        document = json.loads(source.read_text(encoding='utf-8-sig'))
        client = document.get('installed', {}) if isinstance(document, dict) else {}
        if not isinstance(client, dict):
            raise ValueError('請選擇 Google OAuth 桌面應用程式 JSON。')
        client_id, secret = client.get('client_id', ''), client.get('client_secret', '')
        if not isinstance(client_id, str) or not client_id.endswith('.apps.googleusercontent.com') or not isinstance(secret, str) or not secret or '\n' in secret or '\r' in secret:
            raise ValueError('OAuth JSON 缺少桌面應用程式的用戶端資料。')
        executable = ensure_rclone()
        with gpu_lock(path=self.directory / 'transfer.lock', timeout=0):
            pending = self.config.with_suffix('.pending')
            try:
                obscured = subprocess.run([str(executable), 'obscure', '-'], input=secret + '\n',
                                          text=True, capture_output=True, timeout=10, creationflags=FLAGS)
                if obscured.returncode:
                    raise RuntimeError('無法準備 Google Drive 授權。')
                parser = configparser.ConfigParser(interpolation=None)
                parser['qianmi'] = dict(type='drive', scope='drive', client_id=client_id, client_secret=obscured.stdout.strip())
                with pending.open('w', encoding='utf-8') as target:
                    parser.write(target)
                result = subprocess.run([str(executable), 'config', 'reconnect', 'qianmi:', '--config', str(pending), '--auto-confirm'],
                                        capture_output=True, timeout=300, creationflags=FLAGS)
                parser.read(pending, encoding='utf-8')
                if result.returncode or not json.loads(parser.get('qianmi', 'token', fallback='{}')).get('refresh_token'):
                    raise RuntimeError('Google Drive 授權未完成，請重新登入。')
                pending.replace(self.config)
            finally:
                pending.unlink(missing_ok=True)
        return dict(connected=True, message='授權完成，將自動上傳日期資料夾。')

    def copy(self, stop):
        settings = self.read()
        executable = ensure_rclone()
        with gpu_lock(path=self.directory / 'transfer.lock', timeout=0):
            args = [str(executable), 'copy', str(self.output), 'qianmi:', '--config', str(self.config),
                    '--drive-root-folder-id', settings.folder_id, '--checksum', '--immutable']
            for extension in ('png', 'jpg', 'jpeg', 'webp', 'bmp', 'mp4'):
                args += ['--include', f'/????-??-??/*.{extension}']
            process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, creationflags=FLAGS)
            self.uploading = True
            self.message = '正在自動上傳日期資料夾…'
            try:
                while process.poll() is None:
                    if stop.wait(.5) or self.read() != settings:
                        return
                if process.returncode:
                    raise RuntimeError('Google Drive 上傳失敗。')
                self.last_success = time.time()
                self.message = '日期資料夾已上傳，等待新作品。'
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
                self.uploading = False

    def run(self, stop):
        while not stop.is_set():
            try:
                if self.read().enabled and self.connected():
                    self.copy(stop)
            except TimeoutError:
                self.message = '正在進行 Google Drive 授權，稍後重試。'
            except Exception:
                self.message = '上傳失敗，30 秒後自動重試；請確認網路、授權及資料夾權限。'
            self.wake.wait(30)
            self.wake.clear()

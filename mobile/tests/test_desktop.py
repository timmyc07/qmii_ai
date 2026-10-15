"""Exercise the desktop HTTP bridge against a real isolated host API."""
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import socket
import tempfile
import threading
import time
import unittest

import uvicorn
from mobile.desktop import StudioClient
from mobile.server import create_app


class DesktopBridgeTest(unittest.TestCase):
    def test_old_server_is_rejected_before_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            code = Path(directory) / 'access-code.txt'
            code.write_text('test-code', encoding='utf-8')
            client = StudioClient(code_path=code)
            with patch('mobile.desktop.urllib.request.urlopen'), patch.object(client, 'request') as request:
                request.side_effect = [{'csrf': 'fixture'}, {'csrf': 'fixture'}, {'ok': True}]
                with self.assertRaisesRegex(RuntimeError, '舊版本'):
                    client.connect()
                self.assertEqual([call.args[0] for call in request.call_args_list],
                                 ['/api/login', '/api/session', '/api/logout'])
                self.assertEqual(client.csrf, '')

    def test_bridge_errors_are_utf8_under_windows_legacy_encoding(self):
        script = """import runpy, sys, warnings
from unittest.mock import patch
warnings.simplefilter('ignore', RuntimeWarning)
sys.argv = ['mobile.desktop', 'load_settings']
with patch('mobile.settings.SettingsStore.read', side_effect=RuntimeError('工作室服務仍是舊版本')):
    runpy.run_module('mobile.desktop', run_name='__main__')
"""
        result = subprocess.run([sys.executable, '-c', script], input=b'', capture_output=True,
                                env={**os.environ, 'PYTHONIOENCODING': 'cp950'}, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.decode('utf-8').strip(), '工作室服務仍是舊版本')

    def test_desktop_and_browser_share_queue_and_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            received = []

            def runner(payload, sources, output, progress):
                received.append(payload)
                return []

            app = create_app(root / 'state', root / 'output', runner=runner, settings_path=root / 'settings.json')
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                listener.listen()
                server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
                thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]})
                thread.start()
                try:
                    deadline = time.monotonic() + 10
                    while not server.started and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(server.started)
                    url = f'http://127.0.0.1:{listener.getsockname()[1]}'
                    desktop = StudioClient(url, root / 'state' / 'access-code.txt')
                    browser = StudioClient(url, root / 'state' / 'access-code.txt')
                    desktop.connect()
                    browser.connect()
                    value = desktop.request('/api/settings')
                    value['fixedPrompt'] = '跨設備'
                    desktop.request('/api/settings', value, method='PUT')
                    self.assertEqual(browser.request('/api/settings')['fixedPrompt'], '跨設備')
                    job = desktop.request('/api/jobs', dict(prompt='共同工作流', workflow='pose',
                                                           images=[], request_id='e' * 32))
                    self.assertEqual(browser.request('/api/jobs')['jobs'][0]['id'], job['id'])
                    for _ in range(100):
                        if browser.request('/api/jobs/' + job['id'])['status'] == 'completed':
                            break
                        time.sleep(.01)
                    self.assertEqual(received[0]['workflow'], 'pose')
                    desktop.request('/api/logout', method='POST')
                    browser.request('/api/logout', method='POST')
                finally:
                    server.should_exit = True
                    thread.join(10)
                    self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main()

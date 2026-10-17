"""Exercise the desktop HTTP bridge against a real isolated host API."""
import os
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock, patch
import socket
import tempfile
import threading
import time
import unittest

import uvicorn
from mobile.desktop import StudioClient, main
from mobile.server import create_app


class DesktopBridgeTest(unittest.TestCase):
    def test_video_bridge_uploads_tail_separately_and_reports_all_results(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / f'{index}.png' for index in range(5)]
            for index, path in enumerate(paths):
                path.write_bytes(f'image{index}'.encode())
            payload = dict(prompt='cat blinks', workflow='h3_image', images=list(map(str, paths[:4])),
                           last_image=str(paths[4]), parameters=dict(end_frame='custom'))
            job = dict(id='fixture', results=['a', 'b', 'c', 'd'],
                       result_files=[f'{index}.mp4' for index in range(4)], status='completed', message='影片完成')
            with patch('mobile.desktop.StudioClient') as client_class, \
                    patch('mobile.desktop.sys.argv', ['mobile.desktop', 'generate']), \
                    patch('mobile.desktop.sys.stdin', Mock(read=Mock(return_value=json.dumps(payload)))), \
                    patch('mobile.desktop.emit') as emit:
                client = client_class.return_value
                client.request.side_effect = [dict(id=str(index)) for index in range(5)] + [job, {}]
                main()
            submitted = client.request.call_args_list[5].args[1]
            self.assertEqual(submitted['images'], ['0', '1', '2', '3'])
            self.assertEqual(submitted['last_image'], '4')
            self.assertEqual(submitted['parameters'], payload['parameters'])
            reports = [call.args[0] for call in emit.call_args_list]
            self.assertEqual([report['index'] for report in reports], [1, 2, 3, 4, 4])
            self.assertTrue(all(report['total'] == 4 for report in reports))
            self.assertTrue(all(report['video'].endswith(f'{index}.mp4') and not report['done']
                                for index, report in enumerate(reports[:4])))
            self.assertTrue(reports[-1]['done'])
            self.assertEqual(client.request.call_args_list[-1].args, ('/api/logout',))

    def test_same_api_with_old_code_restarts_local_service(self):
        client = StudioClient()
        with patch('mobile.desktop.urllib.request.urlopen'), \
                patch('mobile.desktop.Path.read_text', return_value='test-code'), \
                patch('mobile.desktop.source_revision', return_value='current'), \
                patch('mobile.desktop.restart_service') as restart, \
                patch.object(client, 'request') as request:
            request.side_effect = [{'csrf': 'old'}, {'api_version': 8, 'source_revision': 'old'},
                                   {'ok': True}, {'csrf': 'new'},
                                   {'api_version': 8, 'source_revision': 'current'}]
            client.connect()
            restart.assert_called_once()
            self.assertEqual(client.csrf, 'new')
            self.assertEqual([call.args[0] for call in request.call_args_list],
                             ['/api/login', '/api/session', '/api/logout', '/api/login', '/api/session'])

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
                    value['preciseMode'] = True
                    desktop.request('/api/settings', value, method='PUT')
                    self.assertTrue(browser.request('/api/settings')['preciseMode'])
                    job = desktop.request('/api/jobs', dict(prompt='共同工作流', workflow='quick',
                                                           images=[], request_id='e' * 32))
                    self.assertEqual(browser.request('/api/jobs')['jobs'][0]['id'], job['id'])
                    for _ in range(100):
                        if browser.request('/api/jobs/' + job['id'])['status'] == 'completed':
                            break
                        time.sleep(.01)
                    self.assertEqual(received[0]['workflow'], 'quick')
                    desktop.request('/api/logout', method='POST')
                    browser.request('/api/logout', method='POST')
                finally:
                    server.should_exit = True
                    thread.join(10)
                    self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main()

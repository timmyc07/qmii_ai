from contextlib import contextmanager
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from mobile.cancellation import CancellationFailed, GenerationCancelled, TaskControl, run_process, task_scope
from mobile.gpu import gpu_lock
from mobile.tests.support import create_app


class CancellationTest(unittest.TestCase):
    def test_cli_is_killed_and_waited_for_when_cancelled(self):
        control = TaskControl()
        timer = threading.Timer(.2, control.cancelled.set)
        started = time.monotonic()
        timer.start()
        try:
            with self.assertRaises(GenerationCancelled), task_scope(control):
                run_process([sys.executable, '-c', 'import time; time.sleep(60)'], Path.cwd(), 5, 0)
        finally:
            timer.cancel(); timer.join()
        self.assertLess(time.monotonic() - started, 3)

    def test_comfy_cancel_is_targeted_and_confirmed_before_unlock(self):
        control = TaskControl(); control.prompt_id = 'owned'
        held = []
        requests = []

        @contextmanager
        def lock():
            held.append(True)
            try:
                yield
            finally:
                held.pop()

        def request(path, payload=None, timeout=10):
            self.assertTrue(held)
            requests.append((path, payload))
            if path == '/queue':
                return dict(queue_running=[[0, 'other']], queue_pending=[])
            return dict(cancelled=True)

        with patch('mobile.superduper.request_json', side_effect=request), self.assertRaises(GenerationCancelled):
            with lock(), task_scope(control):
                control.cancelled.set(); control.check()
        self.assertEqual(requests, [('/api/jobs/owned/cancel', {}), ('/queue', None)])
        self.assertFalse(held)
        with patch('mobile.superduper.request_json', side_effect=OSError), self.assertRaises(CancellationFailed):
            control.finish()

    def test_cancel_during_prompt_submission_keeps_id_for_targeted_cleanup(self):
        from mobile.superduper import request_json
        control = TaskControl()

        def open_request(*args, **kwargs):
            identifier = json.loads(args[0].data)['prompt_id']
            control.cancelled.set()
            return io.BytesIO(json.dumps({'prompt_id': identifier}).encode())

        with self.assertRaises(GenerationCancelled), patch.object(control, 'finish'), \
                patch('mobile.superduper.urlopen', side_effect=open_request), task_scope(control):
            request_json('/prompt', {'prompt': {}})
        self.assertIsNotNone(control.prompt_id)

    def test_waiting_for_gpu_can_be_cancelled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'gpu.lock'
            control = TaskControl(); control.cancelled.set()
            with gpu_lock(path=path), self.assertRaises(GenerationCancelled):
                with gpu_lock(path=path, check=control.check):
                    self.fail('Cancelled task acquired the GPU')

    def test_api_cancel_auth_queue_results_and_next_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ready = threading.Event()
            calls = []

            def runner(payload, sources, output, progress):
                calls.append(payload['prompt'])
                if len(calls) > 1:
                    return []
                Image.new('RGB', (16, 16)).save(output / '0.png')
                progress('已完成 1/4 張', ['0.png']); ready.set()
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    progress('正在生成第 2/4 張…'); time.sleep(.01)
                raise AssertionError('Cancellation did not reach the worker')

            app = create_app(root / 'state', root / 'output', runner=runner, settings_path=root / 'settings.json')
            with TestClient(app, base_url='http://localhost:8787') as client:
                origin = {'Origin': 'http://localhost:8787'}
                path = '/api/jobs/' + 'a' * 32 + '/cancel'
                self.assertEqual(client.post(path, headers=origin).status_code, 401)
                code = (root / 'state/access-code.txt').read_text()
                csrf = client.post('/api/login', json={'code': code}, headers=origin).json()['csrf']
                headers = {**origin, 'X-Qianmi-CSRF': csrf}
                self.assertEqual(client.post(path, headers=origin).status_code, 403)
                first = client.post('/api/jobs', json=dict(prompt='first', workflow='quick', request_id='a' * 32), headers=headers).json()
                self.assertTrue(ready.wait(2))
                queued = client.post('/api/jobs', json=dict(prompt='queued', workflow='quick', request_id='b' * 32), headers=headers).json()
                cancelled = client.post('/api/jobs/' + queued['id'] + '/cancel', headers=headers).json()
                self.assertEqual(cancelled['status'], 'cancelled')
                self.assertIsNotNone(cancelled['finished'])
                client.post('/api/jobs/' + first['id'] + '/cancel', headers=headers)
                for _ in range(100):
                    result = client.get('/api/jobs/' + first['id']).json()
                    if result['status'] == 'cancelled':
                        break
                    time.sleep(.02)
                self.assertEqual(result['status'], 'cancelled')
                self.assertTrue(result['result_files'][0].endswith(f'/{first["id"]}_0.png'))
                self.assertEqual(client.get(result['results'][0]).status_code, 200)
                self.assertEqual(client.post('/api/jobs/' + first['id'] + '/cancel', headers=headers).json()['status'], 'cancelled')
                third = client.post('/api/jobs', json=dict(prompt='next', workflow='quick', request_id='c' * 32), headers=headers).json()
                for _ in range(100):
                    if client.get('/api/jobs/' + third['id']).json()['status'] == 'completed':
                        break
                    time.sleep(.02)
                self.assertEqual(client.post('/api/jobs/' + third['id'] + '/cancel', headers=headers).json()['status'], 'completed')
                self.assertEqual(calls, ['first', 'next'])

    def test_unconfirmed_stop_fails_and_prevents_next_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = threading.Event()
            calls = []

            def runner(payload, sources, output, progress):
                calls.append(payload['prompt'])
                if not release.wait(5):
                    raise AssertionError('test did not release worker')
                raise CancellationFailed('無法確認模型已停止。')

            app = create_app(root / 'state', root / 'output', runner=runner, settings_path=root / 'settings.json')
            with TestClient(app, base_url='http://localhost:8787') as client:
                origin = {'Origin': 'http://localhost:8787'}
                code = (root / 'state/access-code.txt').read_text()
                csrf = client.post('/api/login', json={'code': code}, headers=origin).json()['csrf']
                headers = {**origin, 'X-Qianmi-CSRF': csrf}
                first = client.post('/api/jobs', json=dict(prompt='first', workflow='quick', request_id='a' * 32), headers=headers).json()
                queued = client.post('/api/jobs', json=dict(prompt='queued', workflow='quick', request_id='b' * 32), headers=headers).json()
                release.set()
                for _ in range(100):
                    result = client.get('/api/jobs/' + first['id']).json()
                    if result['status'] == 'failed':
                        break
                    time.sleep(.02)
                self.assertEqual(result['status'], 'failed')
                self.assertIn('佇列已停止', result['message'])
                self.assertEqual(client.get('/api/jobs/' + queued['id']).json()['status'], 'queued')
                self.assertEqual(client.post('/api/jobs', json=dict(prompt='next', workflow='quick', request_id='c' * 32), headers=headers).status_code, 503)
                self.assertEqual(calls, ['first'])

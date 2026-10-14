import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from mobile.server import create_app

ORIGIN = {'Origin': 'http://localhost:8787'}


def image_bytes():
    output = io.BytesIO()
    Image.new('RGB', (32, 32), 'purple').save(output, format='PNG')
    return output.getvalue()


class MobileSecurityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.release = threading.Event()
        self.active = 0
        self.max_active = 0
        self.received = []

        def runner(payload, sources, directory, progress):
            self.active += 1
            self.max_active = max(self.active, self.max_active)
            self.received.append(payload['prompt'])
            self.release.wait(3)
            (directory / '0.png').write_bytes(image_bytes())
            self.active -= 1
            return ['0.png']

        self.app = create_app(self.root / 'state', self.root / 'output', runner=runner)
        self.client = TestClient(self.app, base_url='http://localhost:8787')
        self.client.__enter__()

    def tearDown(self):
        self.release.set()
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def login(self):
        code = (self.root / 'state' / 'access-code.txt').read_text()
        result = self.client.post('/api/login', json={'code': code}, headers=ORIGIN)
        self.assertEqual(result.status_code, 200)
        self.assertIn('HttpOnly', result.headers['set-cookie'])
        return {**ORIGIN, 'X-Qianmi-CSRF': result.json()['csrf']}

    def job(self, headers, images=None, request_id=None):
        return self.client.post('/api/jobs', json=dict(prompt='private edit instruction', workflow='quick',
                                images=images or [], request_id=request_id or __import__('secrets').token_hex(16)), headers=headers)

    def test_auth_origin_csrf_and_download_guard(self):
        self.assertEqual(self.client.get('/api/jobs').status_code, 401)
        self.assertEqual(self.client.get('/api/uploads/' + 'a' * 32).status_code, 401)
        self.assertEqual(self.client.post('/api/login', json={'code': 'wrong'}, headers={'Origin': 'https://evil.example'}).status_code, 403)
        headers = self.login()
        self.assertEqual(self.job(ORIGIN).status_code, 403)
        self.assertEqual(self.client.get('/', headers={'Host': 'evil.example'}).status_code, 400)
        self.assertEqual(self.client.post('/api/logout', headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/api/jobs').status_code, 401)

    def test_upload_limits_and_path_validation(self):
        headers = self.login()
        self.assertEqual(self.client.post('/api/uploads', content=b'not an image', headers=headers).status_code, 422)
        self.assertEqual(self.client.post('/api/uploads', content=b'x' * (12 * 1024 * 1024 + 1), headers=headers).status_code, 413)
        self.assertEqual(self.job(headers, ['../private']).status_code, 404)
        self.assertEqual(self.job(headers, ['a' * 32]).status_code, 422)
        result = self.client.post('/api/uploads', content=image_bytes(), headers=headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.get(result.json()['url']).status_code, 200)

    def test_queue_idempotency_hidden_prompt_and_recovery(self):
        headers = self.login()
        upload = self.client.post('/api/uploads', content=image_bytes(), headers=headers).json()
        first = self.job(headers, [upload['id']], 'a' * 32)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['prompt'], '')
        retry = self.job(headers, [upload['id']], 'a' * 32)
        self.assertEqual(first.json()['id'], retry.json()['id'])
        second = self.job(headers)
        self.release.set()
        for _ in range(100):
            result = self.client.get('/api/jobs/' + second.json()['id']).json()
            if result['status'] == 'completed':
                break
            time.sleep(.03)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.max_active, 1)
        self.assertIn('private edit instruction', self.received)
        job = self.client.get('/api/jobs/' + first.json()['id']).json()
        self.assertEqual(job['prompt'], '')
        self.assertEqual(self.client.get(job['results'][0]).status_code, 200)
        other = TestClient(self.app, base_url='http://localhost:8787')
        self.assertEqual(other.get(job['results'][0]).status_code, 401)
        with self.app.state.store.connect() as db:
            self.assertEqual(db.execute('SELECT prompt FROM jobs WHERE id=?', (job['id'],)).fetchone()[0], '')

    def test_queue_bound_and_validation_does_not_echo_prompt(self):
        headers = self.login()
        for _ in range(8):
            self.assertEqual(self.job(headers).status_code, 200)
        self.assertEqual(self.job(headers).status_code, 429)
        result = self.client.post('/api/jobs', json={'prompt': 'sensitive text'}, headers=headers)
        self.assertEqual(result.status_code, 422)
        self.assertNotIn('sensitive text', result.text)

    def test_restart_marks_interrupted_job_failed(self):
        store = self.app.state.store
        with store.connect() as db:
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)',
                       ('e' * 32, 'f' * 32, 'running', 'old', '', 'quick', '[]', '[]', time.time(), time.time()))
        # Independent state recovery is exercised without starting a second GPU worker.
        self.release.set()
        self.client.__exit__(None, None, None)
        self.app = create_app(self.root / 'state', self.root / 'output', runner=lambda *args: [])
        self.client = TestClient(self.app, base_url='http://localhost:8787')
        self.client.__enter__()
        headers = self.login()
        self.assertEqual(self.client.get('/api/jobs/' + 'e' * 32).json()['status'], 'failed')

    def test_shutdown_drains_gpu_and_rejects_new_work(self):
        headers = self.login()
        self.job(headers)
        for _ in range(100):
            if self.active:
                break
            time.sleep(.01)
        code = (self.root / 'state' / 'access-code.txt').read_text()
        self.assertEqual(self.client.post('/api/control/drain', headers=ORIGIN).status_code, 403)
        result = self.client.post('/api/control/drain', headers={**ORIGIN, 'X-Qianmi-Control': code})
        self.assertTrue(result.json()['busy'])
        self.assertEqual(self.job(headers).status_code, 503)
        self.release.set()
        for _ in range(100):
            if not self.app.state.worker.is_alive():
                break
            time.sleep(.01)
        self.assertFalse(self.app.state.worker.is_alive())

    def test_https_pairing_uses_secure_cookie_without_external_network(self):
        origin = 'https://qmii.example'
        app = create_app(self.root / 'https-state', self.root / 'https-output', runner=lambda *args: [], public_url=origin)
        code = (self.root / 'https-state' / 'access-code.txt').read_text()
        with TestClient(app, base_url=origin) as client:
            response = client.post('/api/login', json={'code': code}, headers={'Origin': origin})
            self.assertEqual(response.status_code, 200)
            self.assertIn('Secure', response.headers['set-cookie'])
            self.assertIn('HttpOnly', response.headers['set-cookie'])
            self.assertEqual(client.get('/api/session').status_code, 200)


if __name__ == '__main__':
    unittest.main()

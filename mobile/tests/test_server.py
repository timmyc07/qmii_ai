import io
import json
import sqlite3
from pathlib import Path
import tempfile
import threading
import time
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from mobile.server import Store, create_app

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

        self.app = create_app(self.root / 'state', self.root / 'output', runner=runner,
                              settings_path=self.root / 'settings.json')
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
        oversized = io.BytesIO()
        Image.new('1', (5000, 4001)).save(oversized, format='PNG')
        self.assertEqual(self.client.post('/api/uploads', content=oversized.getvalue(), headers=headers).status_code, 422)
        self.assertEqual(self.client.post('/api/uploads', content=b'x' * (12 * 1024 * 1024 + 1), headers=headers).status_code, 413)
        self.assertEqual(self.job(headers, ['../private']).status_code, 404)
        self.assertEqual(self.job(headers, ['a' * 32]).status_code, 422)
        result = self.client.post('/api/uploads', content=image_bytes(), headers=headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.get(result.json()['url']).status_code, 200)

    def test_workflow_validation_and_authentication(self):
        payload = dict(prompt='blue teacup', workflow='quick', images=[], request_id='c' * 32)
        self.assertEqual(self.client.post('/api/jobs', json=payload, headers=ORIGIN).status_code, 401)
        headers = self.login()
        self.assertEqual(self.client.post('/api/jobs', json={**payload, 'workflow': 'unknown'}, headers=headers).status_code, 422)
        response = self.client.post('/api/jobs', json=payload, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['workflow'], 'quick')
        upload = self.client.post('/api/uploads', content=image_bytes(), headers=headers).json()['id']
        invalid = {**payload, 'workflow': 'superduper', 'images': [upload], 'request_id': 'd' * 32}
        self.assertEqual(self.client.post('/api/jobs', json=invalid, headers=headers).status_code, 200)
        valid = {**invalid, 'workflow': 'nsfw_adv', 'request_id': 'e' * 32, 'parameters': {'denoise': .6}}
        self.assertEqual(self.client.post('/api/jobs', json=valid, headers=headers).status_code, 200)
        invalid = {**valid, 'request_id': 'f' * 32, 'parameters': {'denoise': 1.1}}
        self.assertEqual(self.client.post('/api/jobs', json=invalid, headers=headers).status_code, 422)

    def test_shared_settings_conflict_and_security(self):
        self.assertEqual(self.client.get('/api/settings').status_code, 401)
        headers = self.login()
        value = self.client.get('/api/settings').json()
        value.update(preciseMode=True, presets=[dict(id='one', name='測試', prompt='花園'),
                                              dict(id='two', name='正負分欄', prompt='花園', negative='  模糊\n<水印>  ')],
                     generation={'quick': {'width': 768, 'height': 1344, 'negative': '模糊'}})
        self.assertEqual(self.client.put('/api/settings', json=value, headers=ORIGIN).status_code, 403)
        result = self.client.put('/api/settings', json=value, headers=headers)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(self.client.get('/api/session').json()['preciseMode'])
        self.assertEqual(result.json()['generation']['quick']['height'], 1344)
        self.assertEqual(self.client.put('/api/settings', json=value, headers=headers).status_code, 409)
        self.assertEqual(self.client.get('/api/settings').json()['presets'][0]['name'], '測試')
        saved = self.client.get('/api/settings').json()
        self.assertEqual(saved['presets'][0]['negative'], '')
        self.assertEqual(saved['presets'][1]['negative'], '  模糊\n<水印>  ')
        saved['presets'][1]['negative'] = 'x' * 4001
        self.assertEqual(self.client.put('/api/settings', json=saved, headers=headers).status_code, 422)
        self.assertEqual(self.client.get('/api/settings').json()['presets'][1]['negative'], '  模糊\n<水印>  ')

    def test_library_keeps_old_artwork_and_hides_paths(self):
        path = self.root / 'output' / 'desktop-old.png'
        path.write_bytes(image_bytes())
        self.assertEqual(self.client.get('/api/library').status_code, 401)
        self.login()
        value = self.client.get('/api/library').json()
        self.assertEqual(len(value['items']), 1)
        self.assertNotIn(str(path), json.dumps(value))
        url = value['items'][0]['url']
        self.assertEqual(self.client.get(url).content, image_bytes())
        self.app.state.store.cleanup()
        self.assertTrue(path.exists())
        other = TestClient(self.app, base_url='http://localhost:8787')
        self.assertEqual(other.get(url).status_code, 401)
        self.assertEqual(self.client.get('/api/library/' + 'a' * 64).status_code, 404)

    def test_reference_rules_and_cross_device_queue(self):
        headers = self.login()
        upload = self.client.post('/api/uploads', content=image_bytes(), headers=headers).json()['id']
        value = dict(prompt='融合', workflow='reference', images=[upload], request_id='a' * 32)
        self.assertEqual(self.client.post('/api/jobs', json=value, headers=headers).status_code, 422)
        value['images'] = [upload] * 5
        self.assertEqual(self.client.post('/api/jobs', json=value, headers=headers).status_code, 422)
        value['images'] = [upload] * 2
        job = self.client.post('/api/jobs', json=value, headers=headers).json()
        other = TestClient(self.app, base_url='http://localhost:8787')
        code = (self.root / 'state' / 'access-code.txt').read_text()
        other.post('/api/login', json={'code': code}, headers=ORIGIN)
        self.assertEqual(other.get('/api/jobs').json()['jobs'][0]['id'], job['id'])

    def test_completed_jobs_are_not_deleted_after_seven_days(self):
        store = self.app.state.store
        job_id = 'c' * 32
        folder = store.output / job_id
        folder.mkdir()
        (folder / '0.png').write_bytes(image_bytes())
        with store.connect() as db:
            db.execute('INSERT INTO jobs (id,request_id,status,message,prompt,workflow,sources,results,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (job_id, 'd' * 32, 'completed', 'done', '', 'quick', '[]', '["0.png"]', 1, 1))
        store.cleanup()
        self.assertTrue((folder / '0.png').exists())
        self.assertEqual(store.job(job_id)['status'], 'completed')

    def test_queue_idempotency_prompt_history_and_recovery(self):
        headers = self.login()
        upload = self.client.post('/api/uploads', content=image_bytes(), headers=headers).json()
        first = self.job(headers, [upload['id']], 'a' * 32)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['prompt'], 'private edit instruction')
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
        self.assertEqual(job['prompt'], 'private edit instruction')
        self.assertEqual(self.client.get(job['results'][0]).status_code, 200)
        other = TestClient(self.app, base_url='http://localhost:8787')
        self.assertEqual(other.get(job['results'][0]).status_code, 401)
        with self.app.state.store.connect() as db:
            self.assertEqual(db.execute('SELECT prompt FROM jobs WHERE id=?', (job['id'],)).fetchone()[0], 'private edit instruction')

    def test_job_origin_timestamps_and_authenticated_history(self):
        headers = self.login()
        origin = dict(platform='iOS · Safari · 網頁', device='小迷的手機', device_id='device-123', user='<小迷>')
        value = dict(prompt='  固定風格\n\n本次想法\n ', workflow='quick', request_id='b' * 32, origin=origin)
        first = self.client.post('/api/jobs', json=value, headers=headers).json()
        self.assertEqual(first['origin'], origin)
        value['origin']['user'] = '其他名稱'
        retry = self.client.post('/api/jobs', json=value, headers=headers).json()
        self.assertEqual(retry['origin']['user'], '<小迷>')
        self.release.set()
        for _ in range(100):
            job = self.client.get('/api/jobs/' + first['id']).json()
            if job['status'] == 'completed':
                break
            time.sleep(.03)
        self.assertEqual(job['status'], 'completed')
        self.assertLessEqual(job['created'], job['started'])
        self.assertLessEqual(job['started'], job['finished'])
        self.assertEqual(job['prompt'], '  固定風格\n\n本次想法\n ')
        self.assertIn('  固定風格\n\n本次想法\n ', self.received)
        other = TestClient(self.app, base_url='http://localhost:8787')
        self.assertEqual(other.get('/api/jobs').status_code, 401)
        self.assertEqual(other.get('/api/jobs/' + first['id']).status_code, 401)
        value['request_id'] = 'c' * 32
        value['origin']['user'] = 'a' * 101
        self.assertEqual(self.client.post('/api/jobs', json=value, headers=headers).status_code, 422)

    def test_existing_database_history_migration(self):
        state = self.root / 'old-state'
        state.mkdir()
        with sqlite3.connect(state / 'mobile.sqlite3') as db:
            db.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY, request_id TEXT UNIQUE, status TEXT, message TEXT, prompt TEXT, workflow TEXT, sources TEXT, results TEXT, created REAL, updated REAL)')
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)',
                       ('a' * 32, 'b' * 32, 'completed', 'done', 'old prompt', 'quick', '[]', '[]', 1, 2))
        db.close()
        store = Store(state, self.root / 'old-output')
        job = store.public_job(store.job('a' * 32))
        self.assertEqual(job['prompt'], 'old prompt')
        self.assertEqual(job['origin'], {})
        self.assertIsNone(job['started'])
        self.assertIsNone(job['finished'])
        Store(state, self.root / 'old-output')

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
            db.execute('INSERT INTO jobs (id,request_id,status,message,prompt,workflow,sources,results,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?)',
                       ('e' * 32, 'f' * 32, 'running', 'old', '', 'quick', '[]', '[]', time.time(), time.time()))
        # Independent state recovery is exercised without starting a second GPU worker.
        self.release.set()
        self.client.__exit__(None, None, None)
        self.app = create_app(self.root / 'state', self.root / 'output', runner=lambda *args: [])
        self.client = TestClient(self.app, base_url='http://localhost:8787')
        self.client.__enter__()
        headers = self.login()
        job = self.client.get('/api/jobs/' + 'e' * 32).json()
        self.assertEqual(job['status'], 'failed')
        self.assertIsNotNone(job['finished'])

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

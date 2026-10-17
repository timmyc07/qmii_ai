import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from mobile.maintenance import Maintenance, directory_size, workflow_check
from mobile.recipes import RecipeInput, Recipes
from mobile.server import Store, create_app


class MaintenanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'state', self.root / 'output')
        self.tools = Maintenance(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def artwork(self, number, status='completed', age=40):
        job_id = f'{number:032x}'
        name = f'2026-01-01/{job_id}_0.png'
        path = self.store.output / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'artwork')
        os.utime(path, (time.time() - age * 86400,) * 2)
        with self.store.connect() as db:
            db.execute('INSERT INTO jobs (id,status,sources,results) VALUES (?,?,?,?)',
                       (job_id, status, '[]', json.dumps([name])))
        return path

    def test_cleanup_requires_preview_and_preserves_active_new_and_changed_files(self):
        old = self.artwork(1)
        active = self.artwork(2, 'running')
        recent = self.artwork(3, age=1)
        changed = self.artwork(4)
        preview = self.tools.preview(30)
        self.assertEqual(preview['count'], 2)
        changed.write_bytes(b'new artwork')
        result = self.tools.cleanup(preview['token'])
        self.assertEqual(result['count'], 1)
        self.assertFalse(old.exists())
        self.assertTrue(all(path.exists() for path in (active, recent, changed)))
        self.assertEqual(json.loads(self.store.job(f'{1:032x}')['results']), [])
        with self.assertRaises(ValueError):
            self.tools.cleanup(preview['token'])

    def test_cleanup_rejects_expired_preview_and_paths_outside_output(self):
        path = self.artwork(1)
        outside = self.root / 'private.png'
        outside.write_bytes(b'private')
        with self.store.connect() as db:
            db.execute('UPDATE jobs SET results=? WHERE id=?', (json.dumps(['../private.png']), f'{1:032x}'))
        preview = self.tools.preview(1)
        self.assertEqual(preview['count'], 0)
        self.tools.previews[preview['token']] = (time.time() - 601, [])
        with self.assertRaises(ValueError):
            self.tools.cleanup(preview['token'])
        self.assertTrue(path.exists())
        self.assertTrue(outside.exists())

    def test_h3_health_uses_selected_profile_and_reports_missing_live_nodes(self):
        from mobile.h3 import FILES
        models = self.root / 'models'
        for folder, names in FILES.items():
            for name in names[:1] if folder == 'loras' else names:
                path = models / folder / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'model')
        comfy = self.root / 'comfy'; comfy.mkdir()
        (comfy / 'main.py').write_bytes(b'runtime')
        python = self.root / 'python.exe'; python.write_bytes(b'python')
        with patch('mobile.superduper.COMFY', comfy), patch('mobile.superduper.PYTHON', python), patch('mobile.h3.MODELS', models):
            self.assertTrue(workflow_check('h3_image', {'video_profile': 'turbo4'})['ready'])
            self.assertFalse(workflow_check('h3_image', {'video_profile': 'turbo8'})['ready'])
            checked = workflow_check('h3_image', info={})
            self.assertIn('MiniMaxH3ImageToVideo', checked['missing_nodes'])

    @unittest.skipUnless(os.name == 'nt', 'Windows junction protection')
    def test_cleanup_and_scan_skip_junctions_and_count_hardlinks_once(self):
        import _winapi
        target = self.root / 'outside'; target.mkdir()
        job_id = 'a' * 32
        outside = target / f'{job_id}_0.png'; outside.write_bytes(b'keep')
        os.utime(outside, (time.time() - 40 * 86400,) * 2)
        junction = self.store.output / '2026-01-01'
        _winapi.CreateJunction(str(target), str(junction))
        try:
            with self.store.connect() as db:
                db.execute('INSERT INTO jobs (id,status,sources,results) VALUES (?,?,?,?)',
                           (job_id, 'completed', '[]', json.dumps([f'2026-01-01/{job_id}_0.png'])))
            self.assertEqual(self.tools.preview(30)['count'], 0)
            self.assertEqual(directory_size(self.store.output), 0)
            self.assertTrue(outside.exists())
        finally:
            junction.rmdir()
        file = self.store.output / 'one.png'; file.write_bytes(b'artwork')
        os.link(file, self.store.output / 'two.png')
        self.assertEqual(directory_size(self.store.output), len(b'artwork'))

    def test_recipe_validation_and_atomic_crud(self):
        recipes = Recipes(self.store.state / 'recipes.json')
        recipe = RecipeInput(name='有聲影片', workflow='h3_image', prompt='轉頭微笑',
                             parameters={'video_profile': 'turbo8', 'steps': 8, 'end_frame': 'custom', 'seed': 42})
        saved = recipes.change(recipe=recipe)['recipes'][0]
        self.assertEqual(recipes.read()[0]['parameters']['seed'], 42)
        self.assertEqual(recipes.change(recipe_id=saved['id']), {'recipes': []})
        for value in (dict(workflow='unknown'), dict(parameters={'negative': '模糊'}), dict(name=' ')):
            with self.assertRaises(ValueError):
                RecipeInput.model_validate({**recipe.model_dump(), **value})


class ToolsApiTest(unittest.TestCase):
    def test_auth_csrf_recipe_validation_and_cleanup_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = create_app(root / 'state', root / 'output', runner=lambda *args: [], settings_path=root / 'settings.json')
            with TestClient(app, base_url='http://localhost:8787') as client:
                for path in ('/api/recipes', '/api/health', '/api/storage'):
                    self.assertEqual(client.get(path).status_code, 401)
                headers = {'Origin': 'http://localhost:8787'}
                code = (root / 'state/access-code.txt').read_text()
                headers['X-Qianmi-CSRF'] = client.post('/api/login', json={'code': code}, headers=headers).json()['csrf']
                recipe = dict(name='測試配方', workflow='quick', prompt='茶杯', parameters={'seed': 42})
                self.assertEqual(client.post('/api/recipes', json=recipe, headers={'Origin': headers['Origin']}).status_code, 403)
                result = client.post('/api/recipes', json=recipe, headers=headers)
                self.assertEqual(result.status_code, 200)
                recipe_id = result.json()['recipes'][0]['id']
                self.assertEqual(client.post('/api/recipes', json={**recipe, 'parameters': {'duration': 5}}, headers=headers).status_code, 422)
                self.assertEqual(client.delete('/api/recipes/' + recipe_id, headers=headers).json(), {'recipes': []})
                for days in (0, -1, 3651, 1.5):
                    self.assertEqual(client.post('/api/storage/preview', json={'days': days}, headers=headers).status_code, 422)
                preview = client.post('/api/storage/preview', json={'days': 30}, headers=headers).json()
                self.assertEqual(client.post('/api/storage/cleanup', json={'token': preview['token']}, headers={'Origin': headers['Origin']}).status_code, 403)
                self.assertEqual(client.post('/api/storage/cleanup', json={'token': preview['token']}, headers=headers).json()['count'], 0)
                self.assertEqual(client.post('/api/storage/cleanup', json={'token': preview['token']}, headers=headers).status_code, 409)

    def test_missing_model_is_rejected_before_queueing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = create_app(root / 'state', root / 'output', settings_path=root / 'settings.json')
            with TestClient(app, base_url='http://localhost:8787') as client, \
                    patch('mobile.server.workflow_check', return_value=dict(ready=False, missing=['缺少模型'], repair='請修復')):
                headers = {'Origin': 'http://localhost:8787'}
                code = (root / 'state/access-code.txt').read_text()
                headers['X-Qianmi-CSRF'] = client.post('/api/login', json={'code': code}, headers=headers).json()['csrf']
                response = client.post('/api/jobs', json=dict(prompt='茶杯', workflow='quick', images=[], request_id='a' * 32), headers=headers)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(client.get('/api/jobs').json()['jobs'], [])

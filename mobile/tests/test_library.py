from contextlib import nullcontext
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from PIL import Image

from mobile.library import CATALOG, catalog, resolve_lora
from mobile.generation import generate
from mobile.server import create_app


class LibraryTest(unittest.TestCase):
    def test_whitelist_and_model_mode_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'loras').mkdir()
            for item in CATALOG['loras']:
                (root / 'loras' / item['file']).write_bytes(b'fixture')
            self.assertEqual(sum(item['available'] for item in catalog(root)['loras']), 6)
            (root / 'checkpoints').mkdir()
            (root / 'checkpoints' / 'flux1-dev-fp8.safetensors').write_bytes(b'fixture')
            self.assertEqual(sum(item['available'] for item in catalog(root)['loras']), 9)
            for item in CATALOG['loras']:
                if item['workflow'] == 'flux':
                    self.assertEqual(resolve_lora(item['id'], 'flux', False, .65, root)['id'], item['id'])
                    with self.assertRaises(ValueError):
                        resolve_lora(item['id'], 'flux', True, .65, root)
            for value, workflow, images in [('..\\evil', 'pose', False), ('flux_figure', 'chroma', False),
                                            ('qwen_fullbody', 'quick', False), ('qwen_edit', 'pose', False)]:
                with self.assertRaises(ValueError):
                    resolve_lora(value, workflow, images, model_root=root)
            self.assertEqual(resolve_lora('qwen_edit', 'pose', True, model_root=root)['id'], 'qwen_edit')
            with self.assertRaises(ValueError):
                resolve_lora('qwen_edit', 'pose', True, float('nan'), root)

    def test_generation_applies_selected_lora_and_strength_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'loras').mkdir()
            item = next(item for item in CATALOG['loras'] if item['id'] == 'qwen_fullbody')
            (root / 'loras' / item['file']).write_bytes(b'fixture')
            calls = []

            def run(runner, cfg):
                calls.append(cfg)
                Image.new('RGB', (16, 16)).save(cfg['out'])

            with patch('mobile.generation.MODELS', root), patch('mobile.generation.gpu_lock', return_value=nullcontext()), \
                    patch('mobile.generation.ensure_comfy'), patch('mobile.generation.pose_runner'), \
                    patch('mobile.generation.run_pose', side_effect=run):
                generate(dict(prompt='a landscape', workflow='pose', lora='qwen_fullbody', lora_strength=.65), [], root, Mock())
                generate(dict(prompt='nsfw', workflow='pose', lora=''), [], root, Mock())
            self.assertEqual(calls[0]['lora'], item['file'])
            self.assertEqual(calls[0]['lora_strength'], .65)
            self.assertNotIn('lora', calls[1])

    def test_authenticated_api_persists_selection_and_rejects_invalid_pairings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captured = []
            def runner(payload, sources, output, progress):
                captured.append(payload)
                return []
            app = create_app(root / 'state', root / 'output', runner=runner, settings_path=root / 'settings.json')
            with TestClient(app, base_url='http://localhost:8787') as client:
                self.assertEqual(client.get('/api/creation-library').status_code, 401)
                headers = {'Origin': 'http://localhost:8787'}
                code = (root / 'state' / 'access-code.txt').read_text()
                login = client.post('/api/login', json=dict(code=code), headers=headers)
                headers['X-Qianmi-CSRF'] = login.json()['csrf']
                self.assertEqual(len(client.get('/api/creation-library').json()['loras']), 11)
                base = dict(prompt='test', workflow='quick', images=[], lora='qwen_fullbody', lora_strength=.7)
                def submit(value):
                    return client.post('/api/jobs', json=dict(value, request_id=secrets.token_hex(16)), headers=headers)
                self.assertEqual(submit(base).status_code, 422)
                self.assertEqual(submit(dict(base, workflow='pose', lora='qwen_edit')).status_code, 422)
                self.assertEqual(submit(dict(base, workflow='pose', lora_strength=3)).status_code, 422)
                self.assertEqual(submit(dict(base, workflow='chroma_hades')).status_code, 422)
                self.assertEqual(submit(dict(base, workflow='chroma_full', lora='')).status_code, 422)
                with patch('mobile.server.resolve_lora', return_value={'file':'fixture'}):
                    result = submit(dict(base, workflow='pose'))
                self.assertEqual(result.status_code, 200)
                job = client.get('/api/jobs/' + result.json()['id']).json()
                self.assertEqual((job['lora'], job['lora_strength']), ('qwen_fullbody', .7))
            self.assertEqual(captured[0]['lora'], 'qwen_fullbody')


if __name__ == '__main__':
    unittest.main()

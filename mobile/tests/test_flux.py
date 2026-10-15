from contextlib import nullcontext
from pathlib import Path
import tempfile
import unittest
import secrets
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from PIL import Image

from mobile import flux
from mobile.generation import generate
from mobile.library import CATALOG, catalog, resolve_lora
from mobile.server import create_app


class FluxTest(unittest.TestCase):
    def test_api_authentication_dependencies_and_workflow_pairings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(root / 'state', root / 'output', runner=lambda *args: [],
                             settings_path=root / 'settings.json')
            with TestClient(app, base_url='http://localhost:8787') as client:
                base = dict(prompt='a landscape', workflow='flux', images=[], lora='flux_figure', lora_strength=.7)
                headers = {'Origin': 'http://localhost:8787'}

                def submit(**changes):
                    return client.post('/api/jobs', json=dict(base, **changes, request_id=secrets.token_hex(16)), headers=headers)

                self.assertEqual(submit().status_code, 401)
                code = (root / 'state' / 'access-code.txt').read_text()
                headers['X-Qianmi-CSRF'] = client.post('/api/login', json=dict(code=code), headers=headers).json()['csrf']
                with patch('mobile.server.flux.validate_models', side_effect=ValueError('模型缺少')):
                    self.assertEqual(submit().status_code, 422)
                with patch('mobile.server.flux.validate_models'), patch('mobile.server.resolve_lora', wraps=resolve_lora) as resolver:
                    self.assertEqual(submit(images=['a' * 32]).status_code, 422)
                    self.assertEqual(submit(workflow='chroma').status_code, 422)
                    self.assertEqual(submit(lora='qwen_fullbody').status_code, 422)
                    self.assertEqual(submit(lora_strength=2.1).status_code, 422)
                    resolver.return_value = dict(file='fixture')
                    resolver.side_effect = None
                    response = submit()
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()['lora'], 'flux_figure')
                    self.assertEqual(response.json()['lora_strength'], .7)

    def test_all_three_loras_reach_sampler_with_requested_strength(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'checkpoints').mkdir()
            (root / 'checkpoints' / flux.MODEL).write_bytes(b'fixture')
            (root / 'loras').mkdir()
            graphs = []

            def run(runner, graph, output):
                graphs.append(graph)
                Image.new('RGB', (32, 32)).save(output)

            for item in CATALOG['loras']:
                if item['workflow'] != 'flux':
                    continue
                (root / 'loras' / item['file']).write_bytes(b'fixture')
                with patch('mobile.generation.MODELS', root), \
                        patch('mobile.generation.gpu_lock', return_value=nullcontext()), \
                        patch('mobile.generation.ensure_comfy'), patch('mobile.generation.pose_runner'), \
                        patch('mobile.generation.run_comfy_workflow', side_effect=run):
                    generate(dict(workflow='flux', prompt='a landscape', lora=item['id'], lora_strength=.65),
                             [], root, Mock())
                graph = graphs[-1]
                self.assertEqual(graph['12']['inputs']['lora_name'], item['file'])
                self.assertEqual(graph['12']['inputs']['strength_model'], .65)
                self.assertEqual(graph['4']['inputs']['model'], ['12', 0])
                self.assertEqual(graph['7']['inputs']['model'], ['12', 0])
                self.assertEqual(graph['1']['inputs']['ckpt_name'], flux.MODEL)
                self.assertEqual(graph['10']['inputs']['vae'], ['1', 2])
            self.assertEqual(len(graphs), 3)

    def test_missing_checkpoint_disables_and_rejects_lora(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'loras').mkdir()
            (root / 'loras' / 'Female_Figure.safetensors').write_bytes(b'fixture')
            item = next(item for item in catalog(root)['loras'] if item['id'] == 'flux_figure')
            self.assertTrue(item['installed'])
            self.assertFalse(item['available'])
            with self.assertRaisesRegex(ValueError, 'FLUX.1-dev 尚未安裝'):
                resolve_lora('flux_figure', 'flux', False, model_root=root)

    def test_base_only_has_no_lora_and_images_rejected_before_gpu(self):
        graph = flux.build_workflow('a landscape', 42, 'test')
        self.assertNotIn('12', graph)
        self.assertEqual(graph['4']['inputs']['model'], ['1', 0])
        with patch('mobile.generation.gpu_lock') as lock:
            with self.assertRaisesRegex(RuntimeError, '僅支援文字生圖'):
                generate(dict(workflow='flux', prompt='test'), [Path('test.png')], Path('.'), Mock())
            lock.assert_not_called()


if __name__ == '__main__':
    unittest.main()

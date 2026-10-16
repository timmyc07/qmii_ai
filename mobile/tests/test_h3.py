from contextlib import nullcontext
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from PIL import Image

from mobile import h3
from mobile.generation import generate
from mobile.parameters import validate_parameters
from mobile.settings import Settings
from mobile.server import create_app


class H3Test(unittest.TestCase):
    def test_authenticated_video_api_validation_and_range_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def runner(payload, sources, output, progress):
                (output / '0.mp4').write_bytes(b'0123456789')
                return ['0.mp4']

            app = create_app(root / 'state', root / 'output', runner=runner, settings_path=root / 'settings.json')
            with TestClient(app, base_url='http://localhost:8787') as client:
                origin = {'Origin': 'http://localhost:8787'}
                code = (root / 'state/access-code.txt').read_text()
                csrf = client.post('/api/login', json={'code': code}, headers=origin).json()['csrf']
                headers = {**origin, 'X-Qianmi-CSRF': csrf}
                png = io.BytesIO(); Image.new('RGB', (32, 32)).save(png, format='PNG')
                image = client.post('/api/uploads', content=png.getvalue(), headers=headers).json()['id']
                job = dict(prompt='cat turns its head', workflow='h3_image', images=[image], request_id='a' * 32,
                           parameters=dict(duration=6, seed=42))
                for invalid in ({**job, 'images': []}, {**job, 'images': [image, image]},
                                {**job, 'parameters': {'duration': 16}}, {**job, 'workflow': 'h3_text'}):
                    self.assertEqual(client.post('/api/jobs', json=invalid, headers=headers).status_code, 422)
                result = client.post('/api/jobs', json=job, headers=headers).json()
                for _ in range(100):
                    result = client.get('/api/jobs/' + result['id']).json()
                    if result['status'] == 'completed':
                        break
                    __import__('time').sleep(.02)
                self.assertEqual(result['result_files'], ['0.mp4'])
                response = client.get(result['results'][0], headers={'Range': 'bytes=2-5'})
                self.assertEqual(response.status_code, 206)
                self.assertEqual(response.headers['content-type'], 'video/mp4')
                self.assertEqual(response.content, b'2345')
                library = client.get('/api/library').json()['items']
                self.assertEqual(library[0]['media_type'], 'video')
                self.assertEqual(client.get(library[0]['url']).headers['content-type'], 'video/mp4')
                client.post('/api/logout', headers=headers)
                self.assertEqual(client.get(result['results'][0]).status_code, 401)

    def test_frame_grid_and_native_audio_graph(self):
        self.assertEqual(h3.frames(12), 294)
        for duration in (1, 5, 6, 8, 12, 15):
            length = h3.frames(duration)
            self.assertEqual(length % 17, 5)
            self.assertGreaterEqual(length, round(duration * 24))
        value = h3.graph(dict(duration=6, width=896, height=512), 'cat turns its head', 42, 'source.png')
        self.assertEqual(value['first']['class_type'], 'LoadImage')
        self.assertEqual(value['fit']['inputs']['crop'], 'center')
        self.assertEqual(value['condition']['inputs']['first_frame'], ['fit', 0])
        self.assertEqual(value['condition']['inputs']['length'], h3.frames(6))
        self.assertEqual(value['noise']['inputs']['noise_seed'], 42)
        self.assertEqual(value['scheduler']['inputs']['steps'], 4)
        self.assertEqual(value['video']['inputs']['audio'], ['audio', 0])
        self.assertEqual(value['video']['inputs']['fps'], 24)
        self.assertNotIn('UnetLoaderGGUF', {node['class_type'] for node in value.values()})

    def test_parameters_and_settings_reject_incompatible_image_options(self):
        self.assertEqual(validate_parameters(dict(width=768, height=1344, duration=12), 'h3_image')['duration'], 12)
        for parameters in (dict(width=1024, height=1024), dict(duration=16), dict(steps=8), dict(width=513)):
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                validate_parameters(parameters, 'h3_image')
        Settings.model_validate({'generation': {'h3_image': {'duration': 6, 'width': 512, 'height': 896}}})
        with self.assertRaises(ValueError):
            Settings.model_validate({'generation': {'h3_image': {'steps': 8}}})

    def test_routes_exactly_one_image_and_retains_mp4(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            source = output / 'source.png'
            payload = dict(prompt='cat turns its head', workflow='h3_image', parameters=dict(seed=42))
            with patch('mobile.generation.gpu_lock', return_value=nullcontext()), patch('mobile.h3.run', return_value=['0.mp4']) as runner:
                self.assertEqual(generate(payload, [source], output, Mock()), ['0.mp4'])
                self.assertEqual(runner.call_args.args[2], 42)
                self.assertEqual(runner.call_args.args[-1], source)
                for images in ([], [source, source]):
                    with self.assertRaisesRegex(ValueError, '一張'):
                        generate(payload, images, output, Mock())

    def test_downloads_video_and_reports_safe_execution_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            history = {'p': {'status': {'completed': True}, 'outputs': {'save': {'images': [
                dict(filename='clip.mp4', subfolder='qianmi_h3', type='output')]}}}}
            with patch('mobile.h3.ensure_models'), patch('mobile.h3.ensure_server'), \
                    patch('mobile.h3.image_input', return_value=nullcontext('source.png')), \
                    patch('mobile.h3.request_json', side_effect=[{'prompt_id': 'p'}, history]), \
                    patch('mobile.h3.urlopen', return_value=io.BytesIO(b'test-video')):
                self.assertEqual(h3.run({}, 'cat', 42, output, Mock(), output / 'source.png'), ['0.mp4'])
                self.assertEqual((output / '0.mp4').read_bytes(), b'test-video')
            history['p']['status'] = {'status_str': 'error', 'messages': [('execution_error', {
                'node_id': 'sample', 'exception_message': 'private prompt'})]}
            with patch('mobile.h3.ensure_models'), patch('mobile.h3.ensure_server'), \
                    patch('mobile.h3.image_input', return_value=nullcontext('source.png')), \
                    patch('mobile.h3.request_json', side_effect=[{'prompt_id': 'p'}, history]):
                with self.assertRaisesRegex(h3.ComfyWorkflowError, 'SamplerCustomAdvanced') as result:
                    h3.run({}, 'private prompt', 42, output, Mock(), output / 'source.png')
                self.assertNotIn('private prompt', str(result.exception))

    def test_models_share_files_without_copying_or_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comfy, models = root / 'comfy', root / 'models'
            comfy.mkdir(); (comfy / 'main.py').touch()
            python = root / 'python.exe'; python.touch()
            for folder, names in h3.FILES.items():
                (models / folder).mkdir(parents=True)
                for name in names:
                    (models / folder / name).write_bytes(b'model')
            with patch('mobile.h3.COMFY', comfy), patch('mobile.h3.PYTHON', python), patch('mobile.h3.MODELS', models):
                h3.ensure_models(); h3.ensure_models()
            for folder, names in h3.FILES.items():
                for name in names:
                    self.assertTrue((models / folder / name).samefile(comfy / 'models' / folder / name))

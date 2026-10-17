from contextlib import nullcontext
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from PIL import Image

from mobile import h3
from mobile.generation import generate
from mobile.parameters import validate_parameters
from mobile.settings import Settings
from mobile.tests.support import Store, create_app


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
                for invalid in ({**job, 'images': []}, {**job, 'images': [image] * 5},
                                {**job, 'parameters': {'duration': 16}}, {**job, 'workflow': 'h3_text'},
                                {**job, 'parameters': {'end_frame': 'custom'}},
                                {**job, 'last_image': image},
                                {**job, 'workflow': 'quick', 'last_image': image},
                                {**job, 'last_image': 'f' * 32, 'parameters': {'end_frame': 'custom'}},
                                {**job, 'last_image': '../invalid', 'parameters': {'end_frame': 'custom'}}):
                    self.assertEqual(client.post('/api/jobs', json=invalid, headers=headers).status_code, 422)
                tail = client.post('/api/jobs', json={**job, 'images': [image] * 4, 'last_image': image, 'request_id': 'b' * 32,
                    'parameters': dict(video_profile='turbo8', steps=8, end_frame='custom', video_audio=False)}, headers=headers)
                self.assertEqual(tail.status_code, 200)
                self.assertEqual(tail.json()['parameters']['end_frame'], 'custom')
                self.assertEqual(len(tail.json()['sources']), 4)
                self.assertEqual(tail.json()['last_image'], '/api/uploads/' + image)
                result = client.post('/api/jobs', json=job, headers=headers).json()
                for _ in range(100):
                    result = client.get('/api/jobs/' + result['id']).json()
                    if result['status'] == 'completed':
                        break
                    __import__('time').sleep(.02)
                self.assertEqual(result['result_files'], [f'{datetime.now():%Y-%m-%d}/{result["id"]}_0.mp4'])
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

    def test_profiles_and_safe_controls_reach_native_nodes(self):
        for profile, steps, shift in [('turbo4', 4, 6), ('turbo8', 8, 12), ('base', 25, 12)]:
            parameters = validate_parameters(dict(video_profile=profile, steps=steps, crop='disabled',
                                                  resize_method='bicubic', video_audio=False, video_crf=23,
                                                  identity_prompt=True, end_frame='first'), 'h3_image')
            value = h3.graph(parameters, 'integrated_multimodal_description: [Shot 1] cat blinks', 42, 'first.png')
            self.assertEqual(value['scheduler']['inputs']['steps'], steps)
            self.assertEqual(value['scheduler']['inputs']['denoise'], 1)
            self.assertEqual(value['shift']['inputs']['shift_video'], shift)
            self.assertEqual(value['sampler']['inputs']['sampler_name'], 'euler')
            self.assertEqual(value['fit']['inputs']['crop'], 'disabled')
            self.assertEqual(value['fit']['inputs']['upscale_method'], 'bicubic')
            self.assertEqual(value['save']['inputs']['format.codec.encoding.crf'], 23)
            self.assertNotIn('audio', value)
            self.assertNotIn('audio', value['video']['inputs'])
            self.assertEqual(value['condition']['inputs']['last_frame'], ['fit', 0])
            self.assertIn('<Picture 2>', value['condition']['inputs']['prompt'])
            self.assertIn('Preserve the identity', value['condition']['inputs']['prompt'])
            self.assertEqual('turbo' in value, profile != 'base')
            if profile != 'base':
                self.assertEqual(value['turbo']['inputs']['lora_name'], h3.FILES['loras'][profile == 'turbo8'])
        value = h3.graph(dict(end_frame='custom'), 'cat blinks', 42, 'first.png', 'last.png')
        self.assertEqual(value['last']['inputs']['image'], 'last.png')
        self.assertEqual(value['condition']['inputs']['last_frame'], ['last_fit', 0])
        self.assertEqual(h3.conditioning_prompt({}, 'original prompt'), 'original prompt')
        for invalid in (dict(video_profile='turbo8', steps=4), dict(video_profile='base', steps=8),
                        dict(video_profile='base', lora_strength=1), dict(shift_audio=float('nan')),
                        dict(video_audio='false'), dict(video_crf=52), dict(sampler='unknown'), dict(cfg=2),
                        dict(denoise=.5), dict(negative='blur'), dict(negative='')):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_parameters(invalid, 'h3_image')
        with self.assertRaises(ValueError):
            validate_parameters(dict(video_profile='turbo4'), 'quick')
        parameters = dict(video_profile='turbo8', steps=8, video_audio=False, video_crf=23,
                          end_frame='custom', identity_prompt=True, width=896, height=512, seed=42)
        stored = Settings.model_validate({'generation': {'h3_image': parameters}}).model_dump(exclude_none=True)
        self.assertEqual(stored['generation']['h3_image'], parameters)

    def test_batch_sources_tail_modes_seeds_and_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for count in (1, 4):
                for mode in ('none', 'first', 'custom'):
                    with self.subTest(count=count, mode=mode):
                        sources = [root / f'first{i}.png' for i in range(count)]
                        tail = root / 'last.png' if mode == 'custom' else None
                        parameters = dict(end_frame=mode, seed=42, duration=6, refmod=True)
                        payload = dict(prompt='cat blinks', workflow='h3_image', parameters=parameters, last_image=tail)
                        progress = Mock()
                        graphs = []

                        def run(params, prompt, seed, output, report, source, last):
                            self.assertEqual(params, parameters)
                            self.assertEqual(prompt, payload['prompt'])
                            self.assertEqual(last, tail)
                            graphs.append(h3.graph(params, prompt, seed, str(source), str(last) if last else None))
                            output.write_bytes(source.name.encode())
                            report('正在將首幀生成影片…')
                            return [output.name]

                        with patch('mobile.generation.gpu_lock', return_value=nullcontext()) as lock, patch('mobile.h3.run', side_effect=run):
                            names = generate(payload, sources, root, progress)
                        lock.assert_called_once()
                        self.assertEqual(names, [f'{i}.mp4' for i in range(count)])
                        self.assertEqual([(root / name).read_bytes() for name in names], [source.name.encode() for source in sources])
                        self.assertEqual([graph['noise']['inputs']['noise_seed'] for graph in graphs], list(range(42, 42 + count)))
                        self.assertEqual([graph['first']['inputs']['image'] for graph in graphs], list(map(str, sources)))
                        for graph in graphs:
                            if mode == 'none':
                                self.assertNotIn('last_frame', graph['condition']['inputs'])
                            else:
                                self.assertEqual(graph['condition']['inputs']['last_frame'], ['fit' if mode == 'first' else 'last_fit', 0])
                                if mode == 'custom':
                                    self.assertEqual(graph['last']['inputs']['image'], str(tail))
                        partial = [call.args for call in progress.call_args_list if len(call.args) == 2]
                        self.assertEqual(partial, [(f'已完成 {i}/{count} 支影片', names[:i]) for i in range(1, count + 1)])
                        progress.assert_any_call(f'第 {count}/{count} 支：正在將首幀生成影片…')

    def test_source_validation_precedes_gpu_work_and_seed_wraps(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            source = output / 'source.png'
            payload = dict(prompt='cat turns its head', workflow='h3_image', parameters=dict(seed=42))
            with patch('mobile.generation.gpu_lock', return_value=nullcontext()), patch('mobile.h3.run', return_value=['0.mp4']) as runner:
                self.assertEqual(generate(payload, [source], output, Mock()), ['0.mp4'])
                self.assertEqual(runner.call_args.args[2], 42)
                self.assertEqual(runner.call_args.args[-2], source)
                self.assertIsNone(runner.call_args.args[-1])
                for images in ([], [source] * 5):
                    with self.assertRaisesRegex(ValueError, '1 至 4'):
                        generate(payload, images, output, Mock())
                with self.assertRaisesRegex(ValueError, '尾幀'):
                    generate({**payload, 'parameters': dict(end_frame='custom')}, [source], output, Mock())
                payload['parameters']['seed'] = 9007199254740991
                runner.reset_mock()
                generate(payload, [source] * 4, output, Mock())
                self.assertEqual([call.args[2] for call in runner.call_args_list], [9007199254740991, 0, 1, 2])

    def test_partial_batch_is_downloadable_before_failure_and_keeps_shared_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            second_started, release = threading.Event(), threading.Event()
            calls = []

            def run(params, prompt, seed, output, report, source, last):
                calls.append((source, last))
                if len(calls) == 2:
                    second_started.set()
                    if not release.wait(5):
                        raise AssertionError('Test did not release worker')
                    raise RuntimeError('private upstream prompt')
                output.write_bytes(b'completed video')
                return [output.name]

            with patch('mobile.generation.gpu_lock', return_value=nullcontext()), patch('mobile.h3.run', side_effect=run):
                app = create_app(root / 'state', root / 'output', settings_path=root / 'settings.json')
                with TestClient(app, base_url='http://localhost:8787') as client:
                    origin = {'Origin': 'http://localhost:8787'}
                    code = (root / 'state/access-code.txt').read_text()
                    csrf = client.post('/api/login', json={'code': code}, headers=origin).json()['csrf']
                    headers = {**origin, 'X-Qianmi-CSRF': csrf}
                    png = io.BytesIO(); Image.new('RGB', (32, 32)).save(png, format='PNG')
                    images = [client.post('/api/uploads', content=png.getvalue(), headers=headers).json()['id'] for _ in range(5)]
                    payload = dict(prompt='cat blinks', workflow='h3_image', images=images[:4], last_image=images[4],
                                   parameters=dict(end_frame='custom', seed=42), request_id='c' * 32)
                    job = client.post('/api/jobs', json=payload, headers=headers).json()
                    try:
                        self.assertTrue(second_started.wait(5))
                        partial = client.get('/api/jobs/' + job['id']).json()
                        self.assertEqual(partial['status'], 'running')
                        self.assertEqual(partial['result_files'], [f'{datetime.now():%Y-%m-%d}/{job["id"]}_0.mp4'])
                        self.assertIn('2/4', partial['message'])
                        self.assertEqual(client.get(partial['results'][0]).content, b'completed video')
                    finally:
                        release.set()
                    for _ in range(100):
                        result = client.get('/api/jobs/' + job['id']).json()
                        if result['status'] == 'failed':
                            break
                        time.sleep(.02)
                    self.assertEqual(result['status'], 'failed')
                    self.assertIn('第 2/4 支', result['message'])
                    self.assertIn('已保留 1 支', result['message'])
                    self.assertNotIn('private upstream prompt', result['message'])
                    self.assertEqual(result['result_files'], partial['result_files'])
                    self.assertEqual(client.get(result['results'][0]).content, b'completed video')
                    expected_tail = root / 'state/uploads' / f'{images[4]}.png'
                    self.assertEqual(calls, [(root / 'state/uploads' / f'{image}.png', expected_tail) for image in images[:2]])

    def test_migrates_old_tail_and_retains_it_while_queued(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, last, job_id = 'a' * 32, 'b' * 32, 'c' * 32
            store = Store(root / 'state', root / 'output')
            with store.connect() as db:
                db.execute('ALTER TABLE jobs DROP COLUMN last_image')
                db.execute('INSERT INTO jobs (id,status,workflow,sources,results,parameters) VALUES (?,?,?,?,?,?)',
                           (job_id, 'queued', 'h3_image', json.dumps([first, last]), '[]', '{"end_frame":"custom"}'))
                db.execute('INSERT INTO uploads(id,created) VALUES (?,?)', (last, 1))
            tail = root / 'state/uploads' / f'{last}.png'
            tail.touch()
            store = Store(root / 'state', root / 'output')
            job = store.public_job(store.job(job_id))
            self.assertEqual(job['sources'], ['/api/uploads/' + first])
            self.assertEqual(job['last_image'], '/api/uploads/' + last)
            store.cleanup()
            self.assertTrue(tail.is_file())
            store = Store(root / 'state', root / 'output')
            self.assertEqual(store.public_job(store.job(job_id))['sources'], job['sources'])
            store.update(job_id, 'failed', 'stopped')
            store.cleanup()
            self.assertFalse(tail.exists())

    def test_downloads_video_and_reports_safe_execution_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            history = {'p': {'status': {'completed': True}, 'outputs': {'save': {'images': [
                dict(filename='clip.mp4', subfolder='qianmi_h3', type='output')]}}}}
            with patch('mobile.h3.ensure_models'), patch('mobile.h3.ensure_server'), \
                    patch('mobile.h3.image_input', return_value=nullcontext('source.png')), \
                    patch('mobile.h3.urlopen', side_effect=[io.BytesIO(b'first-video'), io.BytesIO(b'next-video')]), \
                    patch('mobile.h3.request_json', side_effect=[{'prompt_id': 'p'}, history] * 2):
                self.assertEqual(h3.run({}, 'cat', 42, output / '0.mp4', Mock(), output / 'source.png'), ['0.mp4'])
                self.assertEqual(h3.run({}, 'cat', 43, output / '1.mp4', Mock(), output / 'source.png'), ['1.mp4'])
                self.assertEqual((output / '0.mp4').read_bytes(), b'first-video')
                self.assertEqual((output / '1.mp4').read_bytes(), b'next-video')
            history['p']['status'] = {'status_str': 'error', 'messages': [('execution_error', {
                'node_id': 'sample', 'exception_message': 'private prompt'})]}
            with patch('mobile.h3.ensure_models'), patch('mobile.h3.ensure_server'), \
                    patch('mobile.h3.image_input', return_value=nullcontext('source.png')), \
                    patch('mobile.h3.request_json', side_effect=[{'prompt_id': 'p'}, history]):
                with self.assertRaisesRegex(h3.ComfyWorkflowError, 'SamplerCustomAdvanced') as result:
                    h3.run({}, 'private prompt', 42, output / '2.mp4', Mock(), output / 'source.png')
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
                h3.ensure_models(); h3.ensure_models(dict(video_profile='turbo8'))
            for folder, names in h3.FILES.items():
                for name in names:
                    self.assertTrue((models / folder / name).samefile(comfy / 'models' / folder / name))

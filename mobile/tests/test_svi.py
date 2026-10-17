from contextlib import nullcontext
import io
import json
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from PIL import Image

from mobile import svi
from mobile.cancellation import CURRENT, CancellationFailed, GenerationCancelled, TaskControl, task_scope
from mobile.generation import generate
from mobile.parameters import validate_parameters
from mobile.tests.support import create_app
from tools.install_svi import prepare_lightning


PROMPTS = ['A cat blinks.', 'The cat stretches.', 'The cat settles down.']


def write_lora(path, payload=b'\0' * 10):
    header = {'diffusion_model.blocks.0.self_attn.q.lora_A.weight': dict(dtype='F16', shape=[1, 2], data_offsets=[0, 4]),
              'diffusion_model.blocks.0.self_attn.q.lora_B.weight': dict(dtype='F16', shape=[2, 1], data_offsets=[4, 8]),
              'diffusion_model.blocks.0.diff_m': dict(dtype='F16', shape=[1], data_offsets=[8, 10])}
    encoded = json.dumps(header).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack('<Q', len(encoded)) + encoded + payload)


class SviTest(unittest.TestCase):
    def test_imported_loras_are_snapshots_with_distinct_names_and_native_modulation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(svi, 'COMFY', Path(directory) / 'comfy'):
            root = Path(directory)
            source, other = root / 'a' / 'style.safetensors', root / 'b' / 'style.safetensors'
            write_lora(source); write_lora(other, b'\1' * 10)
            original = source.read_bytes()
            name, second = svi.import_lora(str(source)), svi.import_lora(str(other))
            self.assertNotEqual(name, second)
            self.assertEqual(svi.import_lora(str(source)), name)
            self.assertEqual(source.read_bytes(), original)
            with (svi.COMFY / 'models/loras' / name).open('rb') as file:
                header = json.loads(file.read(struct.unpack('<Q', file.read(8))[0]))
                self.assertIn('diffusion_model.blocks.0.modulation.diff', header)
                self.assertEqual(file.read(), b'\0' * 10)
            source.unlink()
            params = validate_parameters(dict(high_lora=dict(name=name, strength=.4)), 'svi_image')
            svi.validate_loras(params)
            (svi.COMFY / 'models/loras' / name).unlink()
            with self.assertRaisesRegex(ValueError, 'HIGH LoRA 已不存在'):
                svi.validate_loras(params)

    def test_import_rejects_invalid_files_and_reserved_recipe_loras(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(svi, 'COMFY', Path(directory) / 'comfy'):
            path = Path(directory) / 'bad.safetensors'
            for content in (b'not weights', struct.pack('<Q', 100_000_000), struct.pack('<Q', 2) + b'{}'):
                path.write_bytes(content)
                with self.assertRaises(ValueError):
                    svi.import_lora(str(path))
            for name in (*svi.FILES['loras'], svi.LIGHTNING_HIGH):
                path = Path(directory) / name; write_lora(path)
                with self.assertRaisesRegex(ValueError, '已隨配方載入'):
                    svi.import_lora(str(path))

    def test_import_failure_leaves_no_partial_model_or_changes_to_original(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(svi, 'COMFY', Path(directory) / 'comfy'):
            source = Path(directory) / 'style.safetensors'; write_lora(source)
            original = source.read_bytes()
            with patch.object(svi.shutil, 'copyfileobj', side_effect=OSError('disk full')), self.assertRaises(ValueError):
                svi.import_lora(str(source))
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(list((svi.COMFY / 'models/loras').rglob('*.safetensors')), [])

    def test_high_low_loras_preserve_recipe_and_apply_to_all_three_segments(self):
        name = 'svi_custom/' + 'a' * 64 + '/style.safetensors'
        params = validate_parameters(dict(segment_prompts=PROMPTS, high_lora=dict(name=name, strength=.4),
                                         low_lora=dict(name=name, strength=-.2)), 'svi_image')
        value = svi.graph(params, 42, 'first.png')
        for side, strength in [('high', .4), ('low', -.2)]:
            self.assertEqual(value[side + '_extra']['inputs'], dict(model=[side + '_lightning', 0], lora_name=str(Path(name)), strength_model=strength))
            self.assertEqual(value[side + '_lightning']['inputs']['model'], [side + '_svi', 0])
            self.assertEqual(value[side + '_lightning']['inputs']['strength_model'], 1)
            self.assertEqual(value[side + '_svi']['inputs']['strength_model'], 1)
            for index in range(1, 4):
                self.assertEqual(value[f'part{index}_guide_{side}']['inputs']['model'], [side + '_extra', 0])
        params['high_lora']['strength'] = 0; params.pop('low_lora')
        baseline = svi.graph(params, 42, 'first.png')
        self.assertNotIn('high_extra', baseline); self.assertNotIn('low_extra', baseline)
        self.assertEqual(baseline['part3_guide_high']['inputs']['model'], ['high_lightning', 0])
        for invalid in (dict(name='../escape.safetensors'), dict(name='C:/secret.safetensors'),
                        dict(name=name, strength=float('nan')), dict(name=name, strength=2.1),
                        dict(name=name, strength=-2.1), dict(name=name, extra=1)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_parameters(dict(high_lora=invalid), 'svi_image')
        with self.assertRaises(ValueError):
            validate_parameters(dict(low_lora=dict(name=name)), 'h3_image')

    def test_lightning_modulation_rename_preserves_all_tensor_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'original', Path(directory) / 'converted'
            header = {f'diffusion_model.blocks.{i}.diff_m': dict(dtype='F16', shape=[1], data_offsets=[i*2,i*2+2]) for i in range(41)}
            encoded = json.dumps(header).encode()
            payload = bytes(range(82))
            source.write_bytes(struct.pack('<Q', len(encoded)) + encoded + payload)
            prepare_lightning(source, target)
            with target.open('rb') as result:
                converted = json.loads(result.read(struct.unpack('<Q', result.read(8))[0]))
                self.assertEqual(result.read(), payload)
            self.assertEqual(converted, {key.replace('.diff_m', '.modulation.diff'): value for key, value in header.items()})
            prepare_lightning(source, target)
            self.assertEqual(len(source.read_bytes()), 8 + len(encoded) + len(payload))

    def test_busy_comfy_desktop_prevents_starting_another_model_process(self):
        with patch.object(svi, 'ensure_models'), patch.object(svi, 'request_json', return_value=dict(queue_running=[[0, 'external']])), \
                patch.object(svi.subprocess, 'Popen') as process, self.assertRaisesRegex(svi.ComfyWorkflowError, 'Comfy Desktop 正在生成'):
            svi.run(dict(segment_prompts=PROMPTS), 42, Path('0.mp4'), Mock(), Path('first'))
        process.assert_not_called()

    def test_three_segments_continue_previous_latent_and_merge_once(self):
        value = svi.graph(dict(segment_prompts=PROMPTS), 42, 'first.png')
        for index, text in enumerate(PROMPTS, 1):
            self.assertEqual(value[f'part{index}_text']['inputs']['text'], text)
            inputs = value[f'part{index}']['inputs']
            self.assertEqual(inputs['length'], 81)
            self.assertEqual(inputs['anchor_samples'], ['anchor', 0])
            self.assertEqual(inputs['motion_latent_count'], int(index > 1))
            if index > 1:
                self.assertEqual(inputs['prev_samples'], [f'part{index - 1}_low', 0])
            self.assertEqual(value[f'part{index}_low']['inputs']['noise'], ['no_noise', 0])
        self.assertEqual(value['schedule']['inputs']['steps'], 8)
        self.assertEqual(value['sigmas']['inputs']['step'], 4)
        self.assertEqual(value['part3_merge']['inputs']['source_images'], ['part2_merge', 2])
        self.assertEqual(value['part3_merge']['inputs']['overlap'], 5)
        self.assertEqual(value['video']['inputs'], dict(images=['part3_merge', 2], fps=16))
        self.assertEqual(value['noise']['inputs']['noise_seed'], 42)

    def test_svi_rejects_incompatible_or_incomplete_inputs(self):
        for params in ({'segment_prompts': PROMPTS[:2]}, {'segment_prompts': PROMPTS + ['extra']},
                       {'segment_prompts': [' ', 'cat', 'cat']}, {'segment_prompts': ['x' * 2501] * 3},
                       {'duration': 6}, {'width': 512}, {'refmod': True}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                validate_parameters(params, 'svi_image')
        with self.assertRaises(ValueError):
            validate_parameters(dict(segment_prompts=PROMPTS), 'quick')
        for images in ([], ['first', 'second']):
            with self.assertRaises(ValueError):
                generate(dict(workflow='svi_image', parameters=dict(segment_prompts=PROMPTS)), images, Path('.'), Mock())

    def test_cleanup_runs_on_success_error_and_cancellation_before_return(self):
        for error in (None, RuntimeError('generation failed'), GenerationCancelled('cancelled')):
            with self.subTest(error=error):
                control = TaskControl()
                process = Mock(); process.poll.return_value = None
                events = []

                def execute(*args, **kwargs):
                    control.prompt_id = 'owned'
                    if error:
                        control.cancelled.set() if isinstance(error, GenerationCancelled) else None
                        raise error
                    return ['0.mp4']

                def request(path, payload=None, **kwargs):
                    if path == '/free':
                        self.assertIsNone(CURRENT.get())
                        self.assertEqual(payload, dict(unload_models=True, free_memory=True))
                        events.append('free')
                    return {node['class_type']: {} for node in svi.graph(dict(segment_prompts=PROMPTS), 42, 'first').values()}

                process.terminate.side_effect = lambda: events.append('terminate')
                process.wait.side_effect = lambda **kwargs: events.append('wait')
                with tempfile.TemporaryDirectory() as directory, \
                        patch.object(svi, 'ROOT', Path(directory)), patch.object(svi, 'ensure_models'), \
                        patch.object(svi, 'release_models'), patch.object(svi.socket, 'create_connection', side_effect=OSError), \
                        patch.object(svi, 'image_input', return_value=nullcontext('first')), \
                        patch.object(svi.subprocess, 'Popen', return_value=process), \
                        patch.object(svi, 'request_json', side_effect=request), \
                        patch.object(svi, 'execute_video', side_effect=execute):
                    if error:
                        with self.assertRaises(type(error)), task_scope(control):
                            svi.run(dict(segment_prompts=PROMPTS), 42, Path(directory) / '0.mp4', Mock(), Path('first'))
                    else:
                        with task_scope(control):
                            result = svi.run(dict(segment_prompts=PROMPTS), 42, Path(directory) / '0.mp4', Mock(), Path('first'))
                            self.assertEqual(result, ['0.mp4'])
                            self.assertEqual(events, ['free', 'terminate', 'wait'])
                self.assertIsNone(control.prompt_id)
                self.assertEqual(events, ['free', 'terminate', 'wait'])

    def test_cleanup_force_kills_and_stops_queue_if_exit_unconfirmed(self):
        process = Mock(); process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('comfy', 15), 0]
        with patch.object(svi, 'request_json', side_effect=OSError):
            svi.stop_server(process)
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)
        process.wait.side_effect = subprocess.TimeoutExpired('comfy', 10)
        with patch.object(svi, 'request_json'), self.assertRaises(CancellationFailed):
            svi.stop_server(process)

    def test_cleanup_confirms_owned_real_process_has_exited(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; data=bytearray(32*1024**2); time.sleep(60)'])
        try:
            with patch.object(svi, 'request_json', side_effect=OSError):
                svi.stop_server(process)
            self.assertIsNotNone(process.poll())
        finally:
            if process.poll() is None:
                process.kill(); process.wait()

    def test_api_preserves_long_three_part_prompts_and_download_after_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = []

            def runner(payload, sources, output, progress):
                calls.append(payload)
                (output / '0.mp4').write_bytes(b'0123456789')
                progress('影片已儲存，正在釋放模型與快取…', ['0.mp4'])
                return ['0.mp4']

            app = create_app(root / 'state', root / 'output', runner=runner, settings_path=root / 'settings.json')
            with TestClient(app, base_url='http://localhost:8787') as client, patch.object(svi, 'COMFY', root / 'comfy'):
                origin = {'Origin': 'http://localhost:8787'}
                code = (root / 'state/access-code.txt').read_text()
                csrf = client.post('/api/login', json={'code': code}, headers=origin).json()['csrf']
                headers = {**origin, 'X-Qianmi-CSRF': csrf}
                png = io.BytesIO(); Image.new('RGB', (32, 32)).save(png, format='PNG')
                image = client.post('/api/uploads', content=png.getvalue(), headers=headers).json()['id']
                prompts = ['貓' * 2500, '伸' * 2500, '睡' * 2500]
                local = root / 'style.safetensors'; write_lora(local)
                name = svi.import_lora(str(local))
                job = dict(workflow='svi_image', prompt='\n'.join(prompts), images=[image],
                           request_id='c' * 32, parameters=dict(segment_prompts=prompts, seed=42,
                           high_lora=dict(name=name, strength=.4), low_lora=dict(name=name, strength=-.2)))
                for invalid in ({**job, 'images': []}, {**job, 'images': [image, image]},
                                {**job, 'parameters': {}}, {**job, 'last_image': image}, {**job, 'precise_mode': True},
                                {**job, 'parameters': {**job['parameters'], 'high_lora': dict(name='../escape.safetensors')}},
                                {**job, 'parameters': {**job['parameters'], 'low_lora': dict(name=name, strength=3)}},
                                {**job, 'parameters': {**job['parameters'], 'low_lora': dict(name=name.replace('style', 'missing'))}}):
                    self.assertEqual(client.post('/api/jobs', json=invalid, headers=headers).status_code, 422)
                self.assertEqual(client.post('/api/jobs', json=job, headers=origin).status_code, 403)
                response = client.post('/api/jobs', json=job, headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                for _ in range(100):
                    result = client.get('/api/jobs/' + result['id']).json()
                    if result['status'] == 'completed':
                        break
                    time.sleep(.02)
                self.assertEqual(result['status'], 'completed')
                self.assertIn('資源已釋放', result['message'])
                self.assertEqual(result['parameters']['segment_prompts'], prompts)
                self.assertEqual(result['parameters']['high_lora'], job['parameters']['high_lora'])
                self.assertEqual(result['parameters']['low_lora'], job['parameters']['low_lora'])
                self.assertEqual(calls[0]['parameters']['segment_prompts'], prompts)
                response = client.get(result['results'][0], headers={'Range': 'bytes=2-5'})
                self.assertEqual(response.status_code, 206)
                self.assertEqual(response.content, b'2345')


if __name__ == '__main__':
    unittest.main()

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
from mobile.server import create_app
from tools.install_svi import prepare_lightning


PROMPTS = ['A cat blinks.', 'The cat stretches.', 'The cat settles down.']


class SviTest(unittest.TestCase):
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
            with TestClient(app, base_url='http://localhost:8787') as client:
                origin = {'Origin': 'http://localhost:8787'}
                code = (root / 'state/access-code.txt').read_text()
                csrf = client.post('/api/login', json={'code': code}, headers=origin).json()['csrf']
                headers = {**origin, 'X-Qianmi-CSRF': csrf}
                png = io.BytesIO(); Image.new('RGB', (32, 32)).save(png, format='PNG')
                image = client.post('/api/uploads', content=png.getvalue(), headers=headers).json()['id']
                prompts = ['貓' * 2500, '伸' * 2500, '睡' * 2500]
                job = dict(workflow='svi_image', prompt='\n'.join(prompts), images=[image],
                           request_id='c' * 32, parameters=dict(segment_prompts=prompts, seed=42))
                for invalid in ({**job, 'images': []}, {**job, 'images': [image, image]},
                                {**job, 'parameters': {}}, {**job, 'last_image': image}, {**job, 'precise_mode': True}):
                    self.assertEqual(client.post('/api/jobs', json=invalid, headers=headers).status_code, 422)
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
                self.assertEqual(calls[0]['parameters']['segment_prompts'], prompts)
                response = client.get(result['results'][0], headers={'Range': 'bytes=2-5'})
                self.assertEqual(response.status_code, 206)
                self.assertEqual(response.content, b'2345')


if __name__ == '__main__':
    unittest.main()

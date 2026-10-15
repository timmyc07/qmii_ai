from contextlib import nullcontext
import io
import secrets
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from PIL import Image

from mobile import wan
from mobile.generation import generate, run_comfy_workflow
from mobile.parameters import validate_parameters
from mobile.server import create_app


class WanTest(unittest.TestCase):
    def test_native_5b_text_and_image_graphs_keep_14b_loras_out(self):
        graph = wan.build_workflow('wan', 'a lake', 42, 'video')
        self.assertNotIn('start_image', graph['latent']['inputs'])
        self.assertEqual(graph['latent']['inputs']['length'], 49)
        graph = wan.build_workflow('wan', 'a lake', 42, 'video', ['lake.png'], dict(width=384, height=640, frames=81, steps=12, cfg=2.7))
        self.assertEqual(graph['latent']['inputs']['start_image'], ['image', 0])
        self.assertEqual(graph['sample']['inputs']['steps'], 12)
        with self.assertRaises(ValueError):
            wan.build_workflow('wan', 'a lake', 42, 'video', lora='14b.safetensors')

    def test_template_two_stages_and_high_only_lora(self):
        graph = wan.build_workflow('wan_template', 'a lake', 42, 'video', ['lake.png'], lora='style.safetensors', strength=.3)
        self.assertEqual(graph['lora']['inputs']['strength_model'], .3)
        self.assertEqual(graph['sampling']['inputs']['model'], ['lora', 0])
        self.assertEqual(graph['sampling_low']['inputs']['model'], ['low', 0])
        self.assertEqual(graph['sample_high']['inputs']['end_at_step'], 3)
        self.assertEqual(graph['sample']['inputs']['start_at_step'], 3)
        self.assertEqual(graph['video']['inputs']['fps'], 16)
        self.assertEqual(graph['save']['inputs']['format.codec'], 'h264')

    def test_parameter_validation_rejects_ignored_fields_and_unbounded_video(self):
        for workflow, images, params in [('wan', False, dict(frames=50)), ('wan', False, dict(width=832,height=832)),
                                        ('wan', True, dict(denoise=.5)), ('quick', False, dict(denoise=.5)),
                                        ('flux', False, dict(negative='ignored')), ('chroma_full', True, dict(steps=8)),
                                        ('pose', False, dict(denoise=.5)), ('pose', True, dict(cfg=float('nan')))]:
            with self.subTest(workflow=workflow, params=params), self.assertRaises(ValueError):
                validate_parameters(workflow, images, params)
        self.assertEqual(validate_parameters('pose', True, dict(denoise=.48,steps=10,cfg=2.7)), dict(denoise=.48,steps=10,cfg=2.7))

    def test_video_reader_never_returns_last_frame_or_failed_preview(self):
        history = dict(status=dict(completed=True), outputs=dict(save=dict(images=[dict(filename='lake.mp4',subfolder='wan',type='output')]),
                                                              last=dict(images=[dict(filename='last.png', type='output')])))
        self.assertEqual(wan.wait_video('job', lambda _: {'job':history}), 'wan/lake.mp4')
        history['outputs']['save']['images'][0]['filename'] = 'last.png'
        with self.assertRaises(RuntimeError):
            wan.wait_video('job', lambda _: {'job': history})
        history['status'] = dict(status_str='error')
        with self.assertRaises(RuntimeError):
            wan.wait_video('job', lambda _: {'job': history})

    def test_video_generation_uses_shared_lock_and_saves_mp4(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            def run(runner, graph, output, reader):
                self.assertEqual(output.suffix, '.mp4')
                self.assertEqual(graph['sample']['inputs']['seed'], 123)
                output.write_bytes(b'video')
            with patch('mobile.generation.gpu_lock', return_value=nullcontext()), patch('mobile.generation.ensure_comfy'), \
                    patch('mobile.generation.wan.validate_dependencies'), patch('mobile.generation.comfy_json'), \
                    patch('mobile.generation.pose_runner'), patch('mobile.generation.run_comfy_workflow', side_effect=run):
                self.assertEqual(generate(dict(workflow='wan',prompt='lake',parameters=dict(seed=123,steps=8)), [], target, Mock()), ['0.mp4'])

    def test_pose_and_mask_parameters_reach_the_actual_recipe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def pose(runner, cfg):
                self.assertEqual((cfg['steps'], cfg['cfg'], cfg['denoise'], cfg['seed']), (10, 2.7, .48, 42))
                Image.new('RGB', (16, 16)).save(cfg['out'])
            def template(runner, graph, output):
                repair = graph['c146']['inputs']
                self.assertEqual((repair['steps'],repair['cfg'],repair['denoise'],repair['bbox_dilation'],repair['feather']), (10,2.7,.48,14,8))
                self.assertEqual(repair['sam_dilation'], 12)
                Image.new('RGB', (16,16)).save(output)
            with patch('mobile.generation.gpu_lock',return_value=nullcontext()), patch('mobile.generation.ensure_comfy'), \
                    patch('mobile.generation.pose_runner'), patch('mobile.generation.comfy_json'), \
                    patch('mobile.generation.chroma_templates.validate_dependencies'), \
                    patch('mobile.generation.run_pose',side_effect=pose), patch('mobile.generation.run_comfy_workflow',side_effect=template):
                generate(dict(workflow='pose',prompt='lake',parameters=dict(steps=10,cfg=2.7,denoise=.48,seed=42)), [root/'input.png'], root, Mock())
                generate(dict(workflow='chroma_hades',prompt='lake',parameters=dict(detail_steps=10,detail_cfg=2.7,denoise=.48,bbox_dilation=14,sam_dilation=12,feather=8)), [], root, Mock())

    def test_authenticated_api_records_parameters_and_serves_video(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captured = []
            def runner(payload, sources, output, progress):
                captured.append(payload)
                (output / '0.mp4').write_bytes(b'video-fixture')
                return ['0.mp4']
            app = create_app(root/'state',root/'output',runner=runner,settings_path=root/'settings.json')
            with TestClient(app,base_url='http://localhost:8787') as client:
                headers = {'Origin':'http://localhost:8787'}
                code = (root/'state'/'access-code.txt').read_text()
                headers['X-Qianmi-CSRF'] = client.post('/api/login',json=dict(code=code),headers=headers).json()['csrf']
                def submit(**kwargs):
                    return client.post('/api/jobs',json=dict(prompt='lake',workflow='wan',request_id=secrets.token_hex(16),**kwargs),headers=headers)
                self.assertEqual(submit(parameters=dict(frames=50)).status_code,422)
                self.assertEqual(submit(parameters=dict(denoise=.48)).status_code,422)
                settings = client.get('/api/settings').json()
                settings['generation'] = dict(wan=dict(steps=8,cfg=2.7,seed=123))
                self.assertEqual(client.put('/api/settings',json=settings,headers=headers).status_code,200)
                job = submit().json()
                self.assertEqual(job['parameters'],dict(steps=8,cfg=2.7,seed=123))
                for _ in range(100):
                    job = client.get('/api/jobs/'+job['id']).json()
                    if job['status'] == 'completed': break
                    time.sleep(.01)
                self.assertEqual(job['status'],'completed')
                self.assertEqual(job['media_type'],'video')
                response = client.get(job['results'][0])
                self.assertEqual(response.headers['content-type'],'video/mp4')
                self.assertEqual(response.content,b'video-fixture')
                self.assertEqual(client.get('/api/library').json()['items'][0]['media_type'],'video')
                self.assertEqual(submit(parameters={}).json()['parameters'], {})
                client.post('/api/logout',json={},headers=headers)
                self.assertEqual(client.get(job['results'][0]).status_code,401)


if __name__ == '__main__':
    unittest.main()

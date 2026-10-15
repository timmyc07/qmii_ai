from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from mobile import chroma_templates as templates
from mobile.generation import generate
from mobile.server import JobInput


class ChromaTemplatesTest(unittest.TestCase):
    def test_original_hades_sampling_face_repair_and_upscale_are_connected(self):
        graph = templates.build_workflow('chroma_hades', 'an adult portrait', 123, 'fixture')
        self.assertEqual(graph['c142']['inputs']['steps'], 10)
        self.assertEqual(graph['c102']['class_type'], 'UNETLoader')
        self.assertEqual(graph['c102']['inputs']['unet_name'], 'velvetChroma_v20FP16.safetensors')
        self.assertEqual(graph['c102']['inputs']['weight_dtype'], 'default')
        self.assertEqual(graph['c142']['inputs']['scheduler'], 'sigmoid_offset')
        self.assertEqual(graph['c146']['class_type'], 'FaceDetailer')
        self.assertEqual(graph['c168']['inputs']['upscale_by'], 2)
        self.assertEqual(graph['c168']['inputs']['tile_width'], ['c212', 0])
        self.assertEqual(graph['c168']['inputs']['tile_height'], ['c212', 1])
        self.assertEqual(graph['8']['inputs']['images'], ['c168', 0])
        self.assertEqual(graph['c9']['inputs']['text'], 'an adult portrait')
        self.assertEqual(graph['c146']['inputs']['seed'], 123)
        self.assertTrue(graph['c168']['inputs']['tiled_decode'])

    def test_full_pipeline_connects_all_five_stages_without_author_paths(self):
        graph = templates.build_workflow('chroma_full', 'an adult standing', 456, 'fixture', ['pose.png', 'color.png'])
        self.assertEqual(graph['c176']['inputs']['image'], 'pose.png')
        self.assertEqual(graph['c258']['inputs']['image'], 'color.png')
        self.assertEqual(graph['c103']['inputs']['image'], ['c268', 0])
        self.assertEqual(graph['c275']['inputs']['image'], ['c211', 0])
        self.assertEqual(graph['c276']['inputs']['image'], ['c220', 0])
        self.assertEqual(graph['c235']['inputs']['image'], ['c228', 0])
        self.assertEqual(graph['8']['inputs']['images'], ['c231', 0])
        self.assertEqual(graph['c166']['inputs']['steps'], 4)
        for name in ['chroma_hades', 'chroma_full']:
            value = json.dumps(templates.build_workflow(name, 'safe prompt', 1, 'test', ['pose.png'] if name == 'chroma_full' else []))
            self.assertNotIn('/Users/', value)
            self.assertNotIn('teen', value)
            self.assertNotIn('LoadImageListFromDir', value)
        for node in graph.values():
            for value in node['inputs'].values():
                if isinstance(value, list):
                    self.assertIn(value[0], graph)

    def test_input_rules_reject_before_gpu_and_keep_api_allowlist(self):
        for workflow, images in [('chroma_hades', [Path('pose.png')]), ('chroma_full', []),
                                 ('chroma_full', [Path('pose.png')] * 3)]:
            with patch('mobile.generation.gpu_lock') as lock:
                with self.assertRaises(ValueError):
                    generate(dict(workflow=workflow, prompt='test'), images, Path('.'), Mock())
                lock.assert_not_called()
        JobInput(prompt='test', workflow='chroma_hades', request_id='a' * 32)
        with self.assertRaises(ValueError):
            JobInput(prompt='test', workflow='unreviewed_graph', request_id='a' * 32)

    def test_bad_size_socket_is_rejected_before_queue_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in templates.requirements('chroma_hades'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'fixture')
            info = {node['class_type']: {'input': {'required': {}}, 'output': ['*'] * 8}
                    for node in templates.GRAPHS['chroma_hades'].values()}
            info['GetImageSize']['output'] = ['INT', 'INT', 'INT']
            info['VAEDecode']['output'] = ['IMAGE']
            info['UltimateSDUpscale']['input']['required'] = {'tile_width': ['INT', {}], 'tile_height': ['INT', {}]}
            templates.validate_dependencies('chroma_hades', root, info)
            graph = templates.build_workflow('chroma_hades', 'an adult portrait', 1, 'test')
            graph['c168']['inputs']['tile_width'] = ['c7', 0]
            with patch.dict(templates.GRAPHS, {'chroma_hades': graph}):
                with self.assertRaisesRegex(templates.TemplateDependencyError, '連線類型不符'):
                    templates.validate_dependencies('chroma_hades', root, info)

    def test_status_requires_both_models_and_node_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ready = root / 'ready.json'
            self.assertFalse(templates.status('chroma_full', root, ready)['available'])
            for name in templates.requirements('chroma_full'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'fixture')
            self.assertFalse(templates.status('chroma_full', root, ready)['available'])
            ready.write_text(json.dumps(dict(classes=[node['class_type'] for node in templates.GRAPHS['chroma_full'].values()])))
            self.assertTrue(templates.status('chroma_full', root, ready)['available'])
            (root / templates.requirements('chroma_full')[0]).unlink()
            self.assertFalse(templates.status('chroma_full', root, ready)['available'])

    def test_two_reference_images_generate_one_output_with_same_queue_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in templates.requirements('chroma_full'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'fixture')
            runner = Mock()
            runner.upload_image.side_effect = ['pose.png', 'color.png']
            info = {node['class_type']: {'input': {'required': {}}} for node in templates.GRAPHS['chroma_full'].values()}
            graphs = []
            def run(runner, graph, output):
                graphs.append(graph)
                Image.new('RGB', (16, 16)).save(output)
            with patch('mobile.generation.MODELS', root), patch('mobile.generation.gpu_lock', return_value=nullcontext()), \
                    patch('mobile.generation.ensure_comfy'), patch('mobile.generation.pose_runner', return_value=runner), \
                    patch('mobile.generation.comfy_json', return_value=info), \
                    patch('mobile.generation.run_comfy_workflow', side_effect=run):
                outputs = generate(dict(workflow='chroma_full', prompt='an adult standing'),
                                   [root / 'pose.png', root / 'color.png'], root, Mock())
            self.assertEqual(outputs, ['0.png'])
            self.assertEqual(len(graphs), 1)
            self.assertEqual(graphs[0]['c258']['inputs']['image'], 'color.png')
            self.assertEqual(runner.TIMEOUT, 7200)


if __name__ == '__main__':
    unittest.main()

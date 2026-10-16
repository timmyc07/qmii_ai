import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mobile.superduper import compile_workflow, image_input, workflow_error
from PIL import Image


class SuperDuperTest(unittest.TestCase):
    def test_error_names_node_without_exposing_prompt(self):
        status = {'messages': [('execution_error', {'node_id': '110', 'exception_message': 'private prompt'})]}
        error = workflow_error('SuperDuper', status, {'110': {'class_type': 'FaceDetailer'}})
        self.assertIn('FaceDetailer', str(error))
        self.assertNotIn('private prompt', str(error))

    def test_source_copy_is_removed_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'original.png'
            Image.new('RGB', (16, 16)).save(source)
            with patch('mobile.superduper.COMFY', root):
                with self.assertRaisesRegex(RuntimeError, 'test failure'):
                    with image_input(source) as name:
                        self.assertTrue((root / 'input' / name).is_file())
                        raise RuntimeError('test failure')
            self.assertTrue(source.is_file())
            self.assertEqual(list((root / 'input').iterdir()), [])

    def test_compiles_ui_workflow_and_applies_controls(self):
        nodes = [
            {'id': value, 'type': kind, 'mode': 0, 'inputs': [], 'widgets_values_named': {}}
            for value, kind in [(55, 'MarkdownNote'), (56, 'SaveImage'), (62, 'EmptyLatentImage'),
                                (82, 'TextEncodeQwenImage21'), (83, 'LoraLoader'),
                                (88, 'KSamplerAdvanced'), (89, 'KSamplerAdvanced'), (90, 'SeedNode'),
                                (121, 'FaceDetailer'), (123, 'LoraLoader')]
        ]
        for node in nodes:
            if node['type'] == 'FaceDetailer':
                node['widgets_values_named']['image'] = ['8', 0]
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / 'workflow.json'
            workflow.write_text(json.dumps({'nodes': nodes, 'links': []}), encoding='utf-8')
            with patch('mobile.superduper.WORKFLOW', workflow):
                graph = compile_workflow(dict(width=768, height=1344, steps=20, cfg=2.5,
                                              lora_strength=.65, negative='blur'), 'portrait', 42)
                edit = compile_workflow(dict(width=512, height=768), 'blue teacup', 42, 'test/source.png')
        self.assertNotIn('55', graph)
        self.assertEqual(graph['62']['inputs']['height'], 1344)
        self.assertEqual(graph['82']['inputs']['prompt'], 'STZK, portrait')
        self.assertEqual(graph['82']['inputs']['negative_prompt'], 'blur')
        self.assertEqual(graph['88']['inputs']['end_at_step'], 12)
        self.assertEqual(graph['89']['inputs']['start_at_step'], 12)
        self.assertEqual(graph['83']['inputs']['strength_model'], .65)
        self.assertEqual(graph['123']['inputs']['clip'], ['83', 1])
        self.assertEqual(graph['123']['inputs']['lora_name'], 'qwen2.1_penisV01_000004956_comfy.safetensors')
        self.assertEqual(graph['121']['inputs']['model'], ['123', 0])
        self.assertEqual(graph['90']['inputs']['seed'], 42)
        self.assertEqual(edit['82']['inputs']['images.image_1'], ['131', 0])
        self.assertEqual(edit['88']['inputs']['latent_image'], ['82', 2])
        self.assertNotIn('62', edit)
        self.assertEqual(graph['121']['inputs']['image'], ['rgb_121', 0])
        self.assertEqual(graph['rgb_121']['class_type'], 'SplitImageWithAlpha')
        self.assertEqual(graph['rgb_121']['inputs']['image'], ['8', 0])


if __name__ == '__main__':
    unittest.main()

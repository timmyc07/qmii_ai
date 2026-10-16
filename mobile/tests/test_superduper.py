import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mobile.superduper import compile_workflow


class SuperDuperTest(unittest.TestCase):
    def test_compiles_ui_workflow_and_applies_controls(self):
        nodes = [
            {'id': value, 'type': kind, 'mode': 0, 'inputs': [], 'widgets_values_named': {}}
            for value, kind in [(55, 'MarkdownNote'), (56, 'SaveImage'), (62, 'EmptyLatentImage'),
                                (82, 'TextEncodeQwenImage21'), (83, 'LoraLoader'),
                                (88, 'KSamplerAdvanced'), (89, 'KSamplerAdvanced'), (90, 'SeedNode')]
        ]
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / 'workflow.json'
            workflow.write_text(json.dumps({'nodes': nodes, 'links': []}), encoding='utf-8')
            with patch('mobile.superduper.WORKFLOW', workflow):
                graph = compile_workflow(dict(width=768, height=1344, steps=20, cfg=2.5,
                                              lora_strength=.65, negative='blur'), 'portrait', 42)
        self.assertNotIn('55', graph)
        self.assertEqual(graph['62']['inputs']['height'], 1344)
        self.assertEqual(graph['82']['inputs']['prompt'], 'STZK, portrait')
        self.assertEqual(graph['82']['inputs']['negative_prompt'], 'blur')
        self.assertEqual(graph['88']['inputs']['end_at_step'], 12)
        self.assertEqual(graph['89']['inputs']['start_at_step'], 12)
        self.assertEqual(graph['83']['inputs']['strength_model'], .65)
        self.assertEqual(graph['90']['inputs']['seed'], 42)


if __name__ == '__main__':
    unittest.main()

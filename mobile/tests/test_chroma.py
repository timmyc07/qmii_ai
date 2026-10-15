from contextlib import nullcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from mobile import chroma
from mobile.generation import generate


class ChromaTest(unittest.TestCase):
    def test_text_generation_uses_chroma_and_shared_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            captured = []

            def run(runner, workflow, target):
                captured.append(workflow)
                Image.new('RGB', (32, 32)).save(target)

            with patch('mobile.generation.gpu_lock', return_value=nullcontext()), \
                    patch('mobile.generation.ensure_comfy'), patch('mobile.generation.pose_runner'), \
                    patch('mobile.generation.chroma.validate_models'), \
                    patch('mobile.generation.run_comfy_workflow', side_effect=run), \
                    patch('mobile.generation.run_turbo') as turbo:
                self.assertEqual(generate(dict(workflow='chroma', prompt='blue teacup'), [], output, Mock()), ['0.png'])
                turbo.assert_not_called()
            graph = captured[0]
            self.assertEqual(graph['1']['inputs']['unet_name'], chroma.MODEL)
            self.assertEqual(graph['2']['inputs']['type'], 'chroma')
            self.assertEqual(graph['5']['inputs']['text'], 'blue teacup')
            self.assertEqual(graph['13']['inputs']['steps'], 26)
            self.assertEqual(graph['10']['inputs']['cfg'], 3.8)
            self.assertEqual(graph['8']['class_type'], 'SaveImage')
            for node in graph.values():
                for value in node['inputs'].values():
                    if isinstance(value, list):
                        self.assertIn(value[0], graph)

    def test_reference_images_rejected_before_gpu_access(self):
        with patch('mobile.generation.gpu_lock') as lock:
            with self.assertRaisesRegex(RuntimeError, '僅支援文字生圖'):
                generate(dict(workflow='chroma', prompt='test'), [Path('source.png')], Path('.'), Mock())
            lock.assert_not_called()

    def test_incomplete_install_reports_missing_model(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, '模型未安裝完整'):
                chroma.validate_models(Path(directory))


if __name__ == '__main__':
    unittest.main()

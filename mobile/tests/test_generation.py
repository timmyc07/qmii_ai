from contextlib import nullcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from mobile.generation import generate


class GenerationTest(unittest.TestCase):
    def test_quick_batch_and_reference_use_turbo(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            calls = []

            def turbo(prompt, sources, target, seed, parameters):
                calls.append((prompt, sources, seed, parameters))
                Image.new('RGB', (16, 16)).save(target)

            sources = [output / 'source1.png', output / 'source2.png']
            payload = dict(prompt='same prompt', workflow='quick', parameters=dict(seed=10, steps=9))
            with patch('mobile.generation.gpu_lock', return_value=nullcontext()), \
                    patch('mobile.generation.run_turbo', side_effect=turbo):
                self.assertEqual(generate(payload, sources, output, Mock()), ['0.png', '1.png'])
                self.assertEqual([call[1] for call in calls], [[sources[0]], [sources[1]]])
                self.assertEqual([call[2] for call in calls], [10, 11])
                calls.clear()
                payload.update(workflow='reference')
                self.assertEqual(generate(payload, sources, output, Mock()), ['0.png'])
            self.assertEqual(calls[0][1], sources)
            self.assertIn('same prompt', calls[0][0])
            self.assertEqual(calls[0][3]['steps'], 9)

    def test_rejects_removed_workflows_and_short_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.assertRaisesRegex(RuntimeError, '不支援'):
                generate(dict(prompt='test', workflow='pose'), [], output, Mock())
            with self.assertRaisesRegex(RuntimeError, '至少需要 2 張'):
                generate(dict(prompt='test', workflow='reference'), [output / 'one.png'], output, Mock())


if __name__ == '__main__':
    unittest.main()

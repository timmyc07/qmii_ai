import io
from contextlib import nullcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from PIL import Image
from mobile.generation import comfy_json, run_pose, generate


class GenerationFailureTest(unittest.TestCase):
    def test_quick_batch_and_reference_output_count(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            calls = []

            def turbo(prompt, sources, target, seed):
                calls.append((prompt, sources))
                Image.new('RGB', (16, 16)).save(target)

            sources = [output / 'source1.png', output / 'source2.png']
            with patch('mobile.generation.gpu_lock', return_value=nullcontext()), \
                    patch('mobile.generation.comfy_json'), patch('mobile.generation.run_turbo', side_effect=turbo):
                self.assertEqual(generate(dict(prompt='same prompt', workflow='quick'), sources, output, Mock()), ['0.png', '1.png'])
                self.assertEqual([call[1] for call in calls], [[sources[0]], [sources[1]]])
                calls.clear()
                self.assertEqual(generate(dict(prompt='same prompt', workflow='reference'), sources, output, Mock()), ['0.png'])
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][1], sources)
                self.assertIn('same prompt', calls[0][0])

    def test_qwen_shared_t2i_edit_recipe(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            calls = []

            def pose(runner, cfg):
                calls.append(cfg)
                Image.new('RGB', (16, 16)).save(cfg['out'])

            with patch('mobile.generation.gpu_lock', return_value=nullcontext()), \
                    patch('mobile.generation.ensure_comfy'), patch('mobile.generation.pose_runner', return_value=Mock()), \
                    patch('mobile.generation.run_pose', side_effect=pose):
                generate(dict(prompt='landscape', workflow='pose'), [], output, Mock())
                generate(dict(prompt='landscape', workflow='pose'), [output / 'input.png'], output, Mock())
            self.assertEqual((calls[0]['steps'], calls[0]['cfg']), (50, 2.5))
            self.assertNotIn('lora', calls[0])
            self.assertEqual((calls[1]['steps'], calls[1]['cfg'], calls[1]['mode']), (20, 3, 'edit'))
            self.assertEqual((calls[0]['width'], calls[0]['height']), (1152, 1728))
            self.assertTrue(all(cfg['sampler'] == 'er_sde' and cfg['scheduler'] == 'beta' for cfg in calls))

    def test_successful_empty_comfy_response(self):
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'')):
            self.assertEqual(comfy_json('/free', {'free_memory': True}), {})

    def test_timeout_cancels_only_own_prompt_before_unlock(self):
        runner = Mock()
        runner.build_workflow.return_value = ({}, {})
        runner.media_lock.return_value = MagicMock()
        runner.queue_prompt.return_value = 'own-prompt'
        runner.wait_and_get_image.side_effect = TimeoutError('expired')
        runner._http_json.return_value = {'queue_running': [[0, 'someone-else']], 'queue_pending': []}
        with self.assertRaises(TimeoutError):
            run_pose(runner, {'mode': 't2i', 'out': 'unused.png'})
        calls = runner._http_json.call_args_list
        self.assertEqual(calls[0].args[2], {'delete': ['own-prompt']})
        self.assertEqual(calls[1].args[2], {'prompt_id': 'own-prompt'})


if __name__ == '__main__':
    unittest.main()

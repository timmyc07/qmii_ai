from contextlib import nullcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from mobile.generation import generate, run_turbo


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

    def test_superduper_runs_once_without_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)

            def comfy(parameters, prompt, seed, target, progress, source=None):
                self.assertEqual(parameters['lora_strength'], .7)
                self.assertEqual(prompt, 'portrait')
                Image.new('RGB', (16, 16)).save(target)

            with patch('mobile.generation.gpu_lock', return_value=nullcontext()), \
                    patch('mobile.superduper.run', side_effect=comfy):
                result = generate(dict(prompt='portrait', workflow='superduper',
                                       parameters=dict(seed=12, lora_strength=.7)), [], output, Mock())
            self.assertEqual(result, ['0.png'])

    def test_nsfw_adv_group_and_precise_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)

            def comfy(parameters, prompt, seed, target, progress, source=None):
                self.assertEqual(parameters['lokr_strength'], 1)
                self.assertTrue(prompt.startswith('portrait\n\n【精準模式生成規範】'))
                Image.new('RGB', (16, 16)).save(target)

            with patch('mobile.generation.gpu_lock', return_value=nullcontext()), \
                    patch('mobile.nsfw_adv.run', side_effect=comfy):
                result = generate(dict(prompt='portrait', workflow='nsfw_adv', precise_mode=True,
                                       parameters=dict(seed=12, lokr_strength=1)), [], output, Mock())
            self.assertEqual(result, ['0.png'])

    def test_precision_toggle_reaches_every_generation_runner(self):
        original = '原文\n"Hello, 世界!" 不改寫'
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for workflow in ('quick', 'reference', 'superduper', 'nsfw_adv'):
                for enabled in (False, True):
                    sources = [output / 'a.png', output / 'b.png'] if workflow == 'reference' else []
                    calls = []

                    def turbo(prompt, sources, target, seed, parameters):
                        calls.append(prompt)
                        Image.new('RGB', (16, 16)).save(target)

                    def comfy(parameters, prompt, seed, target, progress, source=None):
                        calls.append(prompt)
                        Image.new('RGB', (16, 16)).save(target)

                    runner = 'mobile.generation.run_turbo' if workflow in ('quick', 'reference') else f'mobile.{workflow}.run'
                    with self.subTest(workflow=workflow, enabled=enabled), \
                            patch('mobile.generation.gpu_lock', return_value=nullcontext()), \
                            patch(runner, side_effect=turbo if workflow in ('quick', 'reference') else comfy):
                        generate(dict(workflow=workflow, prompt=original, precise_mode=enabled), sources, output, Mock())
                        self.assertEqual(len(calls), 1)
                        self.assertIn(original, calls[0])
                        self.assertEqual('【精準模式生成規範】' in calls[0], enabled)

    def test_comfy_modes_modify_each_source_with_incrementing_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            sources = [output / 'a.png', output / 'b.png']
            for workflow in ('superduper', 'nsfw_adv'):
                calls = []

                def comfy(parameters, prompt, seed, target, progress, source=None):
                    calls.append((source, seed, prompt))
                    Image.new('RGB', (16, 16)).save(target)

                with patch('mobile.generation.gpu_lock', return_value=nullcontext()), \
                        patch(f'mobile.{workflow}.run', side_effect=comfy):
                    result = generate(dict(workflow=workflow, prompt='blue teacup', parameters=dict(seed=10)),
                                      sources, output, Mock())
                self.assertEqual(result, ['0.png', '1.png'])
                self.assertEqual(calls, [(sources[0], 10, 'blue teacup'), (sources[1], 11, 'blue teacup')])

    def test_turbo_applies_image_parameters_and_cleans_prompt_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'output.png'
            with patch('mobile.generation.TURBO', root), patch('mobile.generation.subprocess.run') as execute:
                execute.return_value.returncode = 0
                run_turbo('main prompt', [], output, 42,
                          dict(width=768, height=1344, steps=8, cfg=2.5, negative='blur'))
            args = execute.call_args.args[0]
            self.assertEqual(args[args.index('-W') + 1], '768')
            self.assertEqual(args[args.index('-H') + 1], '1344')
            self.assertEqual(args[args.index('--cfg-scale') + 1], '2.5')
            self.assertIn('--negative-prompt-file', args)
            self.assertFalse((root / '.prompt.txt').exists())
            self.assertFalse((root / '.negative.txt').exists())

    def test_dimensions_must_be_multiples_of_32(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                generate(dict(prompt='test', workflow='quick', parameters=dict(width=1000)), [],
                         Path(directory), Mock())


if __name__ == '__main__':
    unittest.main()

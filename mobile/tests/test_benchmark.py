import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from mobile import h3, superduper
from mobile.gpu import gpu_lock
from mobile.parameters import validate_parameters
from tools import install_wan, wan_benchmark
from tools.benchmark_generation import NodeTimings, ROOT, write_table


class BenchmarkTest(unittest.TestCase):
    def test_gpu_lock_excludes_another_process(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'gpu.lock'
            script = ('from mobile.gpu import gpu_lock; from pathlib import Path; import sys; '
                      'lock=gpu_lock(timeout=0,path=Path(sys.argv[1])); lock.__enter__()')
            with gpu_lock(path=path):
                result = subprocess.run([sys.executable, '-c', script, str(path)], cwd=ROOT, capture_output=True,
                                        creationflags=superduper.FLAGS, timeout=15)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b'GPU is busy', result.stderr)
            with gpu_lock(timeout=0, path=path):
                pass

    def test_handoff_skips_only_stopped_comfy_and_rejects_busy(self):
        with patch.object(superduper, 'request_json', side_effect=URLError(ConnectionRefusedError())):
            superduper.release_models()
        with patch.object(superduper, 'request_json', side_effect=URLError(TimeoutError())):
            with self.assertRaisesRegex(superduper.ComfyWorkflowError, '無法確認'):
                superduper.release_models()
        with patch.object(superduper, 'request_json', return_value={'queue_running': ['work']}) as request:
            with self.assertRaisesRegex(superduper.ComfyWorkflowError, '仍有生成'):
                superduper.release_models()
            request.assert_called_once_with('/queue')

    def test_handoff_waits_for_cleanup_and_refuses_timeout(self):
        busy = {'devices': [{'torch_vram_total': 1024**3, 'torch_vram_free': 0}]}
        free = {'devices': [{'torch_vram_total': 0, 'torch_vram_free': 0}]}
        with patch.object(superduper, 'request_json', side_effect=[{}, {}, busy, free]) as request, \
                patch.object(superduper.time, 'sleep') as sleep:
            superduper.release_models()
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(request.call_args_list[1].args, ('/free', {'unload_models': True, 'free_memory': True}))
        with patch.object(superduper, 'request_json', side_effect=[{}, {}] + [busy] * 60), \
                patch.object(superduper.time, 'sleep'):
            with self.assertRaisesRegex(superduper.ComfyWorkflowError, '尚未釋放'):
                superduper.release_models()

    def test_cases_reproduce_parameters_and_matched_video_length(self):
        cases = json.loads((ROOT / 'docs' / 'benchmark_cases.json').read_text(encoding='utf-8'))['cases']
        self.assertEqual(len({case['id'] for case in cases}), len(cases))
        for case in cases:
            with self.subTest(case=case['id']):
                if case['workflow'] == 'wan':
                    graph = wan_benchmark.graph(case['parameters'], case['prompt'], case['parameters']['seed'])
                    self.assertEqual(graph['latent']['inputs']['length'], 141)
                else:
                    validate_parameters(case['parameters'], case['workflow'])
                if case['workflow'] == 'h3_image':
                    self.assertEqual(h3.frames(case['parameters']['duration']), 141)

    def test_wan_native_text_and_image_graph_is_silent(self):
        for source in (None, 'source.png'):
            graph = wan_benchmark.graph({}, 'prompt', 42, source)
            self.assertEqual('first' in graph, bool(source))
            self.assertEqual('start_image' in graph['latent']['inputs'], bool(source))
            self.assertNotIn('audio', graph['video']['inputs'])
            self.assertEqual(graph['sample']['inputs']['sampler_name'], 'uni_pc')
            self.assertEqual(graph['shift']['inputs']['shift'], 8)
        for params in ({'video_audio': True}, {'end_frame': 'first'}, {'width': 2048}, {'duration': float('nan')}):
            with self.assertRaises(ValueError):
                wan_benchmark.graph(params, 'prompt', 42)

    def test_wan_download_validates_before_replacing_and_keeps_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            comfy = Path(directory)
            (comfy / 'main.py').touch()
            name = 'vae/test.safetensors'
            expected = hashlib.sha256(b'weights').hexdigest()
            with patch.object(install_wan, 'COMFY', comfy), patch.object(install_wan, 'FILES', {name: expected}), \
                    patch.object(install_wan, 'urlopen', return_value=io.BytesIO(b'bad')):
                with self.assertRaisesRegex(RuntimeError, '下載校驗失敗'):
                    install_wan.install()
                self.assertFalse((comfy / 'models' / name).exists())
            target = comfy / 'models' / name
            target.write_bytes(b'existing')
            with patch.object(install_wan, 'COMFY', comfy), patch.object(install_wan, 'FILES', {name: expected}):
                with self.assertRaisesRegex(RuntimeError, '未覆寫'):
                    install_wan.install()
            self.assertEqual(target.read_bytes(), b'existing')

    def test_node_timing_excludes_cache_hits_and_table_handles_missing_samples(self):
        timing = NodeTimings()
        timing.event('execution_cached', {'nodes': ['clip']}, 0)
        timing.event('executing', {'node': 'sample'}, 2)
        timing.event('executing', {'node': 'decode'}, 5)
        timing.event('execution_success', {}, 7)
        self.assertEqual(timing.seconds, {'sample': 3, 'decode': 2})
        self.assertEqual(timing.cached, ['clip'])
        with tempfile.TemporaryDirectory() as directory:
            write_table(Path(directory), [dict(case='failed', success=False, generation_seconds=1)])
            self.assertIn('未量測', (Path(directory) / 'comparison.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()

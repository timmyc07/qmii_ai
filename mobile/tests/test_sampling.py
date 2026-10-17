import io
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

import websocket

from mobile.cancellation import GenerationCancelled, TaskControl, run_process, task_scope
from mobile.sampling import CliProgress, ComfyProgress, SamplingProgress
from mobile.superduper import request_json


class SamplingTest(unittest.TestCase):
    def test_speed_excludes_loading_updates_with_actual_intervals_and_resets(self):
        sampling = SamplingProgress()
        with patch('mobile.sampling.time.monotonic') as clock:
            clock.return_value = 100
            sampling.update('one', 0, 8)
            clock.return_value = 500
            sampling.update('one', 1, 8)
            self.assertIsNone(sampling.snapshot()['seconds_per_step'])
            clock.return_value = 502
            sampling.update('one', 2, 8)
            self.assertEqual(sampling.snapshot()['seconds_per_step'], 2)
            clock.return_value = 506
            sampling.update('one', 3, 8)
            self.assertAlmostEqual(sampling.snapshot()['seconds_per_step'], 2.6)
            self.assertNotIn('remaining_seconds', sampling.snapshot())
            clock.return_value = 507
            self.assertEqual(sampling.snapshot()['age_seconds'], 1)
            sampling.update('one', 3, 8)
            self.assertEqual(sampling.snapshot()['age_seconds'], 1)
            sampling.update('two', 1, 4)
            self.assertIsNone(sampling.snapshot()['seconds_per_step'])
            sampling.update('two', 4, 4, seconds=2)
            self.assertEqual(sampling.snapshot()['state'], 'complete')
            sampling.update('two', 1, 4)
            self.assertIsNone(sampling.snapshot()['seconds_per_step'])

    def test_rejects_invalid_counts_and_disconnect_does_not_invent_progress(self):
        sampling = SamplingProgress()
        for step, total in [(True, 8), (1, 0), (9, 8), (-1, 8), (1, float('inf')), ('1', 8), (.5, 8)]:
            sampling.update('one', step, total)
        self.assertIsNone(sampling.snapshot())
        sampling.idle()
        self.assertIsNone(sampling.snapshot())
        sampling.disconnected()
        self.assertEqual(sampling.snapshot(), {'state': 'disconnected'})
        sampling.update('one', 1, 8, seconds=3)
        sampling.disconnected()
        self.assertEqual(sampling.snapshot()['state'], 'disconnected')

    def test_cli_parses_split_carriage_return_frames_and_ignores_loading(self):
        sampling = SamplingProgress()
        parser = CliProgress(sampling)
        parser.feed(b'private prompt\r |#########| 200/400 - 200MB/s\x1b[K')
        self.assertIsNone(sampling.snapshot())
        parser.feed(b'\r |==>   | 1/8 - 2.')
        self.assertIsNone(sampling.snapshot())
        parser.feed(b'50s/it\x1b[K\r |===>  | 2/8 - 4.00it/s\x1b[K')
        result = sampling.snapshot()
        self.assertEqual((result['step'], result['total']), (2, 8))
        self.assertEqual(result['seconds_per_step'], .25)
        self.assertNotIn('remaining_seconds', result)
        self.assertNotIn('private', json.dumps(result))

    def test_cli_streams_before_process_exits_and_preserves_both_pipes(self):
        sampling = SamplingProgress()
        control = TaskControl(sampling)
        observed = threading.Event()

        def observe():
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if sampling.snapshot() and sampling.snapshot()['state'] == 'sampling':
                    observed.set()
                    return
                time.sleep(.01)

        observer = threading.Thread(target=observe)
        observer.start()
        code = "import sys,time; sys.stdout.write('\\r |==>  | 1/4 - 0.50s/it'); sys.stdout.flush(); time.sleep(.8); sys.stderr.write('diagnostic'); sys.stderr.flush()"
        try:
            with task_scope(control):
                result = run_process([sys.executable, '-c', code], Path.cwd(), 5, 0)
        finally:
            observer.join()
        self.assertTrue(observed.is_set())
        self.assertIn(b'1/4', result.stdout)
        self.assertEqual(result.stderr, b'diagnostic')
        self.assertEqual(result.returncode, 0)
        with self.assertRaises(subprocess.TimeoutExpired), task_scope(TaskControl(SamplingProgress())):
            run_process([sys.executable, '-c', 'import time; time.sleep(60)'], Path.cwd(), .1, 0)

    def test_websocket_filters_prompt_and_nodes_and_closes_its_thread(self):
        messages = queue.Queue()

        class Socket:
            def settimeout(self, value):
                pass

            def recv(self):
                try:
                    return messages.get(timeout=.05)
                except queue.Empty:
                    raise websocket.WebSocketTimeoutException()

            def close(self, **kwargs):
                pass

        sampling = SamplingProgress()
        graph = {'part2_low': {'class_type': 'SamplerCustomAdvanced'}, 'decode': {'class_type': 'VAEDecode'}}
        with patch('websocket.create_connection', return_value=Socket()) as connect:
            listener = ComfyProgress(sampling, 'owned', graph, 'http://127.0.0.1:8192')
            try:
                listener.event(dict(type='progress', data=dict(prompt_id='other', node='part2_low', value=2, max=4)))
                listener.event(dict(type='progress', data=dict(prompt_id='owned', node='decode', value=2, max=4)))
                self.assertIsNone(sampling.snapshot())
                messages.put(b'private image preview')
                messages.put(json.dumps(dict(type='progress', data=dict(prompt_id='owned', node='part2_low', value=2, max=4))))
                deadline = time.monotonic() + 2
                while sampling.snapshot() is None and time.monotonic() < deadline:
                    time.sleep(.01)
                result = sampling.snapshot()
                self.assertEqual((result['step'], result['total']), (2, 4))
                self.assertEqual(result['label'], '第 2/3 段 · 低噪採樣')
                listener.event(dict(type='executing', data=dict(prompt_id='owned', node='decode')))
                self.assertEqual(sampling.snapshot()['state'], 'paused')
                self.assertIn('/ws?clientId=owned', connect.call_args.args[0])
            finally:
                listener.close()
            self.assertFalse(listener.thread.is_alive())

    def test_prompt_submission_owns_websocket_before_post_and_closes_on_failure(self):
        control = TaskControl(SamplingProgress())

        def submit(request, **kwargs):
            payload = json.loads(request.data)
            self.assertEqual(payload['prompt_id'], payload['client_id'])
            self.assertEqual(listener.call_args.args[1], payload['prompt_id'])
            return io.BytesIO(json.dumps({'prompt_id': payload['prompt_id']}).encode())

        with patch('mobile.sampling.ComfyProgress') as listener, patch('mobile.superduper.urlopen', side_effect=submit):
            with self.assertRaisesRegex(RuntimeError, 'failed'), task_scope(control):
                request_json('/prompt', {'prompt': {}})
                raise RuntimeError('failed')
            listener.return_value.close.assert_called_once()

    def test_websocket_reconnects_with_same_client_without_failing_generation(self):
        sampling = SamplingProgress()
        received = threading.Event()

        class Socket:
            def settimeout(self, value):
                pass

            def recv(self):
                if not received.is_set():
                    received.set()
                    return json.dumps(dict(type='progress', data=dict(prompt_id='owned', node='sample', value=1, max=4)))
                time.sleep(.02)
                raise websocket.WebSocketTimeoutException()

            def close(self, **kwargs):
                pass

        with patch('websocket.create_connection', side_effect=[OSError(), Socket()]) as connect:
            listener = ComfyProgress(sampling, 'owned', {'sample': {'class_type': 'KSampler'}}, 'http://127.0.0.1:8191')
            try:
                self.assertEqual(sampling.snapshot()['state'], 'disconnected')
                self.assertTrue(received.wait(3))
                deadline = time.monotonic() + 1
                while sampling.snapshot().get('step') != 1 and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(sampling.snapshot()['step'], 1)
                self.assertEqual(connect.call_args_list[0].args[0], connect.call_args_list[1].args[0])
            finally:
                listener.close()

    def test_cancel_while_connecting_does_not_submit_a_prompt(self):
        control = TaskControl(SamplingProgress())
        with patch('mobile.sampling.ComfyProgress') as listener, \
                patch('mobile.superduper.urlopen') as submit, patch.object(control, 'finish'):
            listener.side_effect = lambda *args: (control.cancelled.set() or listener.return_value)
            with self.assertRaises(GenerationCancelled), task_scope(control):
                request_json('/prompt', {'prompt': {}})
            submit.assert_not_called()
            listener.return_value.close.assert_called_once()

    def test_http_completion_starts_download_and_save_timing(self):
        control = TaskControl(SamplingProgress())
        control.prompt_id = 'owned'
        timing = control.sampling.timing
        timing.begin_engine({'sample': {'class_type': 'KSampler'}})
        timing.executing('sample')
        history = {'owned': {'status': {'completed': True}}}
        with patch('mobile.superduper.urlopen', return_value=io.BytesIO(json.dumps(history).encode())), task_scope(control):
            request_json('/history/owned')
        self.assertFalse(timing.engine_active)
        self.assertEqual(timing.current['kind'], 'save')

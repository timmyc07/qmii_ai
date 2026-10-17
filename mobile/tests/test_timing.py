import unittest
from unittest.mock import patch

from mobile.timing import TaskTiming


GRAPH = {node: {'class_type': kind} for node, kind in
         [('a', 'KSampler'), ('b', 'KSampler'), ('decode', 'VAEDecode'), ('video', 'SaveVideo')]}


class TimingTest(unittest.TestCase):
    def setUp(self):
        self.clock = patch('mobile.timing.time.monotonic').start()
        self.addCleanup(patch.stopall)
        self.now = 0
        self.clock.side_effect = lambda: self.now

    def advance(self, seconds):
        self.now += seconds

    def profile(self, outputs=1):
        timing = TaskTiming(outputs)
        for index in range(outputs):
            self.advance(2 if index == 0 else 1)
            timing.begin_engine(GRAPH)
            self.advance(1)
            for node in ('a', 'b'):
                timing.executing(node)
                for step in range(1, 5):
                    self.advance(1)
                    timing.sample(node, step, 4, 1)
            timing.executing('decode')
            self.advance(10)
            timing.executing('video')
            self.advance(5)
            timing.engine_finished()
            self.advance(3)
            timing.output_finished(index + 1)
        self.advance(2)
        return timing.finish()

    def live(self, outputs=1):
        profile = self.profile(outputs)
        self.now = 100
        timing = TaskTiming(outputs, [profile])
        self.advance(2)
        timing.begin_engine(GRAPH)
        self.advance(1)
        timing.executing('a')
        return timing

    def test_speed_change_updates_future_rounds_and_keeps_decode_save_cleanup(self):
        timing = self.live()
        self.advance(2)
        timing.sample('a', 1, 4, 2)
        self.assertEqual(timing.remaining(), 34)
        self.advance(6)
        timing.sample('a', 4, 4, 2)
        timing.executing('b')
        self.advance(8)
        timing.sample('b', 4, 4, 2)
        self.assertEqual(timing.remaining(), 20)
        timing.executing('decode')
        self.advance(5)
        self.assertEqual(timing.remaining(), 15)
        self.advance(5)
        timing.executing('video')
        self.assertEqual(timing.remaining(), 10)
        self.advance(5)
        timing.engine_finished()
        self.assertEqual(timing.remaining(), 5)
        self.advance(3)
        timing.output_finished(1)
        self.assertEqual(timing.remaining(), 2)

    def test_all_batch_outputs_and_observed_decode_speed_are_included(self):
        timing = self.live(outputs=2)
        self.advance(8)
        timing.sample('a', 4, 4, 2)
        timing.executing('b')
        self.advance(8)
        timing.sample('b', 4, 4, 2)
        timing.executing('decode')
        self.advance(20)
        timing.executing('video')
        self.assertEqual(timing.remaining(), 56)

    def test_four_output_batch_includes_every_future_sampling_round(self):
        timing = self.live(outputs=4)
        self.advance(2)
        timing.sample('a', 1, 4, 2)
        self.assertEqual(timing.remaining(), 142)

    def test_three_video_parts_include_six_samplers_and_all_decodes(self):
        graph = {f'part{part}_{side}': {'class_type': 'SamplerCustomAdvanced'}
                 for part in range(1, 4) for side in ('high', 'low')}
        graph.update({f'decode{part}': {'class_type': 'VAEDecode'} for part in range(1, 4)})
        graph['video'] = {'class_type': 'SaveVideo'}
        history = TaskTiming()
        history.begin_engine(graph)
        for part in range(1, 4):
            for side in ('high', 'low'):
                node = f'part{part}_{side}'
                history.executing(node)
                self.advance(4)
                history.sample(node, 4, 4, 1)
            history.executing(f'decode{part}')
            self.advance(2)
        history.executing('video')
        self.advance(3)
        history.engine_finished()
        self.advance(2)
        history.output_finished(1)
        self.advance(1)
        profile = history.finish()
        self.now = 100
        timing = TaskTiming(1, [profile])
        timing.begin_engine(graph)
        timing.executing('part1_high')
        self.advance(2)
        timing.sample('part1_high', 1, 4, 2)
        self.assertEqual(timing.remaining(), 58)

    def test_cached_nodes_are_removed_without_assuming_other_nodes_are_free(self):
        timing = self.live()
        timing.cached(['b', 'not-in-graph'])
        self.assertEqual(timing.remaining(), 24)

    def test_extra_detailer_round_increases_remaining_work(self):
        timing = self.live()
        self.advance(8)
        timing.sample('a', 4, 4, 2)
        self.assertEqual(timing.remaining(), 28)
        self.advance(2)
        timing.sample('a', 1, 4, 2)
        self.assertEqual(timing.remaining(), 34)

    def test_cli_decode_is_timed_separately_after_last_sample(self):
        timing = TaskTiming()
        self.advance(2)
        timing.begin_engine()
        self.advance(7)
        timing.sample('cli', 4, 4, 1)
        self.advance(5)
        timing.engine_finished()
        self.advance(3)
        timing.output_finished(1)
        self.advance(2)
        profile = timing.finish()
        self.assertEqual(sum(value['seconds'] for value in profile.values()), 19)
        self.now = 100
        timing = TaskTiming(1, [profile])
        self.advance(2)
        timing.begin_engine()
        self.advance(5)
        timing.sample('cli', 1, 4, 2)
        self.assertEqual(timing.remaining(), 16)
        self.advance(6)
        timing.sample('cli', 4, 4, 2)
        self.assertEqual(timing.remaining(), 10)

    def test_no_profile_is_calibration_not_a_partial_task_estimate(self):
        timing = TaskTiming()
        timing.begin_engine(GRAPH)
        timing.executing('a')
        timing.sample('a', 2, 4, 2)
        self.assertIsNone(timing.remaining())
        timing.disconnected()
        self.assertEqual(timing.finish(), {})

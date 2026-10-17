import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from mobile.tests.support import Store, create_app
from mobile.sampling import SamplingProgress
from mobile.timing import TaskTiming


class ProgressTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'state', self.root / 'output')
        self.addCleanup(self.temp.cleanup)

    def job(self, name, status='running', created=10, started=20, finished=None,
            workflow='quick', parameters=None, sources=None, results=None, last_image=None):
        with self.store.connect() as db:
            db.execute('''INSERT INTO jobs (id,status,message,prompt,workflow,parameters,sources,results,
                       created,started,finished,updated,last_image) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                       (name * 32, status, '正在生成', 'private prompt', workflow, json.dumps(parameters or {}),
                        json.dumps(sources or []), json.dumps(results or []), created, started, finished,
                        finished or started or created, last_image))
        return self.store.job(name * 32)

    def test_estimate_uses_median_of_matching_successes_and_ignores_seed(self):
        for name, seconds in [('a', 60), ('b', 100), ('c', 200)]:
            self.job(name, 'completed', finished=20 + seconds, parameters=dict(steps=8, seed=1))
        self.job('d', 'failed', finished=9999, parameters=dict(steps=8))
        self.job('e', 'completed', finished=9999, parameters=dict(steps=40))
        self.job('f', 'completed', finished=9999, parameters=dict(steps=8), sources=['one'])
        self.job('1', 'completed', finished=9999, workflow='h3_image', parameters=dict(steps=8))
        row = self.job('2', parameters=dict(seed=99, steps=8, negative='private negative'))
        with patch('mobile.server.time.time', return_value=50):
            progress = self.store.public_job(row)['progress']
        self.assertEqual(progress, dict(elapsed_seconds=40, running_seconds=30,
                                      remaining_seconds=70, estimate_basis='history', sample_count=3,
                                      queue_position=None, completed=0, total=1, sampling=None))
        self.assertNotIn('private', json.dumps(progress))

    def test_queue_position_elapsed_and_terminal_clocks(self):
        self.job('a')
        self.job('b', 'queued', created=30, started=None)
        row = self.job('c', 'queued', created=30, started=None)
        with patch('mobile.server.time.time', return_value=60):
            progress = self.store.job_progress(row)
        self.assertEqual(progress['queue_position'], 3)
        self.assertEqual(progress['elapsed_seconds'], 30)
        self.assertIsNone(progress['running_seconds'])
        self.assertIsNone(progress['remaining_seconds'])

        row = self.job('d', 'cancelled', finished=40, results=['saved.png'])
        with patch('mobile.server.time.time', return_value=900):
            progress = self.store.job_progress(row)
        self.assertEqual(progress['elapsed_seconds'], 30)
        self.assertEqual(progress['running_seconds'], 20)
        self.assertEqual(progress['completed'], 1)
        self.assertIsNone(progress['remaining_seconds'])

    def test_estimate_uses_only_five_latest_matches(self):
        for index, (name, seconds) in enumerate(zip('abcdef', [999, 10, 20, 30, 40, 50])):
            started = 2000 + index * 1000
            self.job(name, 'completed', started=started, finished=started + seconds)
        with patch('mobile.server.time.time', return_value=20):
            progress = self.store.job_progress(self.job('1'))
        self.assertEqual(progress['sample_count'], 5)
        self.assertEqual(progress['remaining_seconds'], 30)

    def test_batch_tail_and_video_settings_do_not_share_estimates(self):
        self.job('a', 'completed', workflow='h3_image', finished=120,
                 parameters=dict(video_profile='turbo4'), sources=['one'], last_image='tail')
        row = self.job('b', workflow='h3_image', parameters=dict(video_profile='turbo8'), sources=['one'])
        self.assertIsNone(self.store.job_progress(row)['remaining_seconds'])
        row = self.job('c', workflow='h3_image', parameters=dict(video_profile='turbo4'), sources=['one'])
        self.assertIsNone(self.store.job_progress(row)['remaining_seconds'])
        row = self.job('d', workflow='h3_image', sources=['one', 'two', 'three', 'four'])
        self.assertEqual(self.store.job_progress(row)['total'], 4)
        row = self.job('e', workflow='reference', sources=['one', 'two'])
        self.assertEqual(self.store.job_progress(row)['total'], 1)

    def test_progress_assets_are_served_to_mobile(self):
        app = create_app(self.root / 'assets', self.root / 'output', runner=lambda *args: [])
        with TestClient(app, base_url='http://localhost:8787') as client:
            self.assertIn('qianmiProgress', client.get('/static/taskprogress.js').text)
            self.assertIn('task-progress', client.get('/static/taskprogress.css').text)

    def test_live_sampling_is_scoped_to_active_job_and_not_returned_for_finished_jobs(self):
        row = self.job('a')
        other = self.job('b')
        sampling = self.store.live_sampling[row['id']] = SamplingProgress()
        sampling.update('sample', 2, 8, seconds=3)
        progress = self.store.public_job(row)['progress']['sampling']
        self.assertEqual((progress['step'], progress['total']), (2, 8))
        self.assertNotIn('remaining_seconds', progress)
        self.assertIsNone(self.store.public_job(other)['progress']['sampling'])
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET status='completed',finished=100 WHERE id=?", (row['id'],))
        self.assertIsNone(self.store.public_job(self.store.job(row['id']))['progress']['sampling'])

    def test_complete_profiles_survive_restart_and_failed_tasks_do_not_calibrate(self):
        row = self.job('a')
        with patch('mobile.timing.time.monotonic') as clock:
            clock.return_value = 0
            timing = TaskTiming()
            sampling = self.store.live_sampling[row['id']] = SamplingProgress(timing)
            clock.return_value = 2
            timing.begin_engine()
            clock.return_value = 10
            sampling.update('cli', 4, 4, seconds=2)
            clock.return_value = 15
            timing.engine_finished()
            clock.return_value = 18
            timing.output_finished(1)
            clock.return_value = 20
            self.store.update(row['id'], 'completed', 'done')
        restored = Store(self.root / 'state', self.root / 'output')
        profile = json.loads(restored.job(row['id'])['timings'])
        self.assertEqual(profile['0:decode']['seconds'], 5)
        self.assertEqual(profile['0:save']['seconds'], 3)
        self.assertEqual(profile['finish']['seconds'], 2)
        self.assertNotIn('timings', restored.public_job(restored.job(row['id'])))
        next_job = self.job('c')
        profiles = [json.loads(value['timings']) for value in restored.progress_history(next_job)]
        with patch('mobile.timing.time.monotonic', return_value=100):
            restored.live_sampling[next_job['id']] = SamplingProgress(TaskTiming(1, profiles))
            progress = restored.job_progress(next_job)
        self.assertEqual(progress['remaining_seconds'], 20)
        self.assertEqual(progress['estimate_basis'], 'speed')
        failed = self.job('b')
        self.store.live_sampling[failed['id']] = SamplingProgress()
        self.store.update(failed['id'], 'failed', 'failed')
        self.assertEqual(json.loads(restored.job(failed['id'])['timings']), {})

    def test_api_remaining_is_whole_task_and_not_the_current_round(self):
        def stage(kind, seconds, steps=0, rate=None):
            return dict(kind=kind, seconds=seconds, steps=steps, rate=rate)
        profile = {'prepare:0': stage('prepare', 1), '0:cli': stage('cli', 8, 8, 1),
                   '0:decode': stage('decode', 5), '0:save': stage('save', 2), 'finish': stage('finish', 1)}
        row = self.job('a')
        with patch('mobile.timing.time.monotonic') as clock:
            clock.return_value = 0
            timing = TaskTiming(1, [profile])
            sampling = self.store.live_sampling[row['id']] = SamplingProgress(timing)
            clock.return_value = 1
            timing.begin_engine()
            clock.return_value = 7
            sampling.update('cli', 2, 8, seconds=3)
            progress = self.store.public_job(row)['progress']
        self.assertEqual(progress['remaining_seconds'], 26)
        self.assertEqual(progress['estimate_basis'], 'speed')
        self.assertEqual(progress['sampling']['step'], 2)
        self.assertNotIn('remaining_seconds', progress['sampling'])

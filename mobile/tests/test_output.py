from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from mobile.tests.support import Store, create_app


class OutputTest(unittest.TestCase):
    def test_migrates_existing_outputs_once_and_keeps_history_downloads(self):
        for layout in ('mobile', ''):
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                store = Store(root / 'state', root / 'output')
                timestamp = datetime(2026, 10, 16, 23, 30).timestamp()
                expected = []
                with store.connect() as db:
                    db.execute('PRAGMA user_version=0')
                    for job_id, extension, platform in [('a' * 32, 'png', 'Windows 桌面'),
                                                         ('b' * 32, 'mp4', '手機網頁')]:
                        folder = store.output / layout / job_id
                        folder.mkdir(parents=True)
                        name = f'0.{extension}'
                        (folder / name).write_bytes(extension.encode())
                        db.execute('INSERT INTO jobs (id,status,prompt,workflow,sources,results,created,updated,origin) '
                                   'VALUES (?,?,?,?,?,?,?,?,?)',
                                   (job_id, 'completed', '保留提示詞', 'quick', '[]', json.dumps([name]),
                                    timestamp, timestamp, json.dumps(dict(platform=platform))))
                        expected.append(f'2026-10-16/{job_id}_{name}')
                    db.execute('INSERT INTO jobs (id,status,results,created) VALUES (?,?,?,?)',
                               ('c' * 32, 'completed', '["0.png"]', timestamp))
                app = create_app(root / 'state', root / 'output', runner=lambda *args: [],
                                 settings_path=root / 'settings.json')
                store = app.state.store
                for relative, job_id in zip(expected, ['a' * 32, 'b' * 32]):
                    self.assertEqual(json.loads(store.job(job_id)['results']), [relative])
                    self.assertTrue((store.output / relative).is_file())
                    self.assertFalse((store.output / layout / job_id).exists())
                self.assertEqual(sorted(path.name for path in store.output.iterdir()), ['2026-10-16'])
                missing = f'2026-10-16/{"c" * 32}_0.png'
                self.assertEqual(json.loads(store.job('c' * 32)['results']), [missing])
                self.assertFalse((store.output / missing).exists())
                Store(root / 'state', root / 'output')
                with TestClient(app, base_url='http://localhost:8787') as client:
                    code = (root / 'state/access-code.txt').read_text()
                    client.post('/api/login', json=dict(code=code), headers={'Origin': 'http://localhost:8787'})
                    for job_id, extension in [('a' * 32, 'png'), ('b' * 32, 'mp4')]:
                        job = client.get('/api/jobs/' + job_id).json()
                        self.assertEqual(job['prompt'], '保留提示詞')
                        self.assertEqual(client.get(job['results'][0]).content, extension.encode())
                    self.assertEqual(len(client.get('/api/library').json()['items']), 2)

    def test_partial_results_keep_their_dates_when_batch_crosses_midnight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / 'state', root / 'output')
            staging = store.state / 'results' / ('a' * 32)
            staging.mkdir(parents=True)
            published = {}
            (staging / '0.png').write_bytes(b'first')
            first = store.publish_results('a' * 32, staging, ['0.png'], '2026-10-16', published)
            (staging / '1.mp4').write_bytes(b'second')
            results = store.publish_results('a' * 32, staging, ['0.png', '1.mp4'], '2026-10-17', published)
            self.assertEqual(results, first + [f'2026-10-17/{"a" * 32}_1.mp4'])
            self.assertEqual([(store.output / value).read_bytes() for value in results], [b'first', b'second'])
            self.assertFalse(any(staging.iterdir()))

    def test_refuses_overwrite_and_invalid_result_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / 'state', root / 'output')
            source = store.state / '0.png'
            source.write_bytes(b'new')
            target = store.output / '2026-10-17' / f'{"a" * 32}_0.png'
            target.parent.mkdir()
            target.write_bytes(b'existing')
            with self.assertRaises(FileExistsError):
                store.publish_results('a' * 32, store.state, ['0.png'], '2026-10-17', {})
            self.assertEqual(target.read_bytes(), b'existing')
            self.assertEqual(source.read_bytes(), b'new')
            with self.assertRaises(ValueError):
                store.publish_results('a' * 32, store.state, ['../0.png'], '2026-10-17', {})


if __name__ == '__main__':
    unittest.main()

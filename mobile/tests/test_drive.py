import configparser
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

from mobile import drive


class DriveTest(unittest.TestCase):
    def test_installer_verifies_archive_and_leaves_no_partial_files(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as package:
            package.writestr(f'rclone-{drive.VERSION}-windows-amd64/rclone.exe', b'executable')
        archive = data.getvalue()
        for valid in (False, True):
            with self.subTest(valid=valid), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with patch.object(drive, 'ROOT', root), patch.object(drive, 'urlopen', return_value=io.BytesIO(archive)), \
                        patch.object(drive, 'SHA256', hashlib.sha256(archive).hexdigest() if valid else 'invalid'):
                    if valid:
                        self.assertEqual(drive.ensure_rclone().read_bytes(), b'executable')
                    else:
                        with self.assertRaises(ValueError):
                            drive.ensure_rclone()
                        self.assertFalse((root / '.runtime/rclone/rclone.exe').exists())
                self.assertFalse((root / '.runtime/rclone/download.zip').exists())
                self.assertFalse((root / '.runtime/rclone/rclone.tmp').exists())

    def test_oauth_keeps_secrets_local_and_preserves_previous_auth_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = drive.Drive(root / 'state', root / 'output')
            source = root / 'client.json'
            source.write_text(json.dumps(dict(installed=dict(client_id='test.apps.googleusercontent.com',
                                                             client_secret='private-client-secret'))))
            original = source.read_bytes()

            def command(args, **kwargs):
                self.assertNotIn('private-client-secret', ' '.join(args))
                if args[1] == 'obscure':
                    self.assertEqual(kwargs['input'], 'private-client-secret\n')
                    return subprocess.CompletedProcess(args, 0, stdout='obscured\n')
                self.assertNotIn('input', kwargs)
                config = configparser.ConfigParser(interpolation=None)
                pending = Path(args[args.index('--config') + 1])
                config.read(pending)
                config['qianmi']['token'] = json.dumps(dict(refresh_token='private-refresh-token'))
                with pending.open('w') as target:
                    config.write(target)
                return subprocess.CompletedProcess(args, 0)

            with patch.object(drive, 'ensure_rclone', return_value=Path('rclone.exe')), \
                    patch.object(drive.subprocess, 'run', side_effect=command):
                self.assertTrue(service.connect(source)['connected'])
            self.assertTrue(service.connected())
            self.assertNotIn('private-', json.dumps(service.status()))
            self.assertEqual(source.read_bytes(), original)
            previous = service.config.read_bytes()
            with patch.object(drive, 'ensure_rclone', return_value=Path('rclone.exe')), \
                    patch.object(drive.subprocess, 'run', side_effect=[Mock(returncode=0, stdout='obscured'), Mock(returncode=1)]):
                with self.assertRaisesRegex(RuntimeError, '授權未完成'):
                    service.connect(source)
            self.assertEqual(service.config.read_bytes(), previous)
            self.assertFalse(service.config.with_suffix('.pending').exists())
            source.write_text('{"web": {}}')
            with self.assertRaises(ValueError), patch.object(drive, 'ensure_rclone') as installer:
                service.connect(source)
            installer.assert_not_called()

    def test_copy_uses_only_daily_media_and_never_deletes_or_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = drive.Drive(root / 'state', root / 'output')
            process = Mock(returncode=0)
            process.poll.return_value = 0
            with patch.object(drive, 'ensure_rclone', return_value=Path('rclone.exe')), \
                    patch.object(drive.subprocess, 'Popen', return_value=process) as start:
                service.copy(threading.Event())
            args = start.call_args.args[0]
            self.assertEqual(args[1:4], ['copy', str(service.output), 'qianmi:'])
            self.assertIn('--checksum', args)
            self.assertIn('--immutable', args)
            self.assertIn('/????-??-??/*.png', args)
            self.assertIn('/????-??-??/*.mp4', args)
            self.assertNotIn('sync', args)
            self.assertNotIn('move', args)
            self.assertIsNotNone(service.last_success)
            self.assertFalse(service.uploading)
            process.terminate.assert_not_called()
            stop = threading.Event(); stop.set()
            process.poll.return_value = None
            with patch.object(drive, 'ensure_rclone', return_value=Path('rclone.exe')), \
                    patch.object(drive.subprocess, 'Popen', return_value=process):
                service.copy(stop)
            process.terminate.assert_called_once()
            process.wait.assert_called_once_with(timeout=10)
            self.assertFalse(service.uploading)

    def test_worker_retries_failure_without_exposing_upstream_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            service = drive.Drive(Path(directory) / 'state', Path(directory) / 'output')
            stop = threading.Event()
            calls = []

            def copy(event):
                calls.append(service.message)
                service.wake.set()
                if len(calls) == 1:
                    raise RuntimeError('private-client-secret')
                stop.set()

            with patch.object(service, 'connected', return_value=True), patch.object(service, 'copy', side_effect=copy):
                service.run(stop)
            self.assertEqual(len(calls), 2)
            self.assertIn('重試', calls[1])
            self.assertNotIn('private-', calls[1])
            service.save(drive.DriveSettings(enabled=False))
            with patch.object(service, 'copy') as copy:
                service.wake.set(); stop.clear()
                with patch.object(service.wake, 'wait', side_effect=lambda _: stop.set()):
                    service.run(stop)
            copy.assert_not_called()

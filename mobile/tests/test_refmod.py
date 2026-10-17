import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from mobile import h3
from mobile.parameters import validate_parameters
from mobile.settings import Settings
from tools import install_refmod


class RefModTest(unittest.TestCase):
    def test_all_h3_profiles_keep_native_frames_audio_and_sampler(self):
        for profile in ('turbo4', 'turbo8', 'base'):
            for end in ('none', 'first', 'custom'):
                with self.subTest(profile=profile, end=end):
                    parameters = dict(video_profile=profile, end_frame=end)
                    off = h3.graph(parameters, 'cat blinks', 42, 'first.png', 'last.png')
                    self.assertEqual(h3.graph({**parameters, 'refmod': False}, 'cat blinks', 42, 'first.png', 'last.png'), off)
                    on = h3.graph({**parameters, 'refmod': True}, 'cat blinks', 42, 'first.png', 'last.png')
                    for name in off.keys() - {'guider'}:
                        self.assertEqual(on[name], off[name])
                    self.assertEqual(on['guider']['inputs']['conditioning'], ['refmod_apply', 0])
                    self.assertEqual(on['refmod_apply']['inputs']['conditioning'], ['condition', 0])
                    self.assertEqual(on['refmod_extract']['inputs']['refs_image.ref_image_1'], ['fit', 0])
                    self.assertFalse(on['refmod_extract']['inputs']['save'])
                    self.assertEqual(on['refmod_extract']['inputs']['mode'], 'Full Reference')

    def test_settings_and_api_parameters_reject_incompatible_qwen_modes(self):
        for workflow in ('quick', 'reference', 'superduper', 'nsfw_adv'):
            for value in (True, False):
                with self.subTest(workflow=workflow, value=value), self.assertRaisesRegex(ValueError, 'Qwen'):
                    validate_parameters(dict(refmod=value), workflow)
        for value in ('true', 1):
            with self.assertRaises(ValueError):
                validate_parameters(dict(refmod=value), 'h3_image')
        settings = Settings.model_validate({'generation': {'h3_image': {'refmod': True}}})
        self.assertTrue(settings.generation['h3_image'].refmod)

    def test_installer_verifies_archive_and_does_not_replace_existing_pack(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.writestr(f'{install_refmod.PACK}-{install_refmod.REVISION}/__init__.py', '# test fixture')
        data = archive.getvalue()
        with tempfile.TemporaryDirectory() as directory:
            comfy = Path(directory); (comfy / 'main.py').touch()
            target = comfy / 'custom_nodes' / install_refmod.PACK
            with patch.object(install_refmod, 'COMFY', comfy), patch.object(install_refmod, 'urlopen', return_value=io.BytesIO(data)):
                with self.assertRaisesRegex(RuntimeError, 'SHA256'):
                    install_refmod.install()
            self.assertFalse(target.exists())
            with patch.object(install_refmod, 'COMFY', comfy), patch.object(install_refmod, 'SHA256', hashlib.sha256(data).hexdigest()), \
                    patch.object(install_refmod, 'urlopen', return_value=io.BytesIO(data)):
                install_refmod.install()
            with patch.object(install_refmod, 'COMFY', comfy), patch.object(install_refmod, 'urlopen') as download:
                install_refmod.install(); download.assert_not_called()
                (target / '.qianmi-revision').write_text('different')
                with self.assertRaisesRegex(RuntimeError, '未覆寫'):
                    install_refmod.install()
            self.assertEqual((target / '__init__.py').read_text(), '# test fixture')

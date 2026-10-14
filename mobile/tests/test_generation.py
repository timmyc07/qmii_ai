import io
import unittest
from unittest.mock import MagicMock, Mock, patch

from mobile.generation import comfy_json, run_pose


class GenerationFailureTest(unittest.TestCase):
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

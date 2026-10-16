import unittest

from mobile.precision import _first_text, _positive_prompt


class PrecisionTest(unittest.TestCase):
    def test_extracts_nested_json_prompt(self):
        value = {'result': [None, {'text': 'prefix {"positive_prompt":"a precise scene"} suffix'}]}
        self.assertEqual(_positive_prompt(_first_text(value)), 'a precise scene')

    def test_accepts_direct_prompt_output(self):
        self.assertEqual(_positive_prompt('a direct prompt'), 'a direct prompt')

    def test_rejects_empty_output(self):
        with self.assertRaisesRegex(RuntimeError, '沒有產生提示詞'):
            _positive_prompt('  ')


if __name__ == '__main__':
    unittest.main()

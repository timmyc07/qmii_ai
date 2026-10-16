import unittest

from mobile.precision import apply_rules


class PrecisionTest(unittest.TestCase):
    def test_original_text_is_unchanged_for_every_mode(self):
        original = '  原文\n「Hello, 世界!」 <image1>\n不翻譯。  '
        for workflow in ('quick', 'reference', 'superduper', 'nsfw_adv'):
            for has_images in (False, True):
                with self.subTest(workflow=workflow, has_images=has_images):
                    result = apply_rules(original, workflow, has_images)
                    self.assertEqual(result.split('\n\n【精準模式生成規範】\n')[0], original)
                    self.assertIn('有衝突時以使用者明確要求為準', result)

    def test_image_rules_are_only_added_for_image_jobs(self):
        self.assertNotIn('僅修改', apply_rules('test', 'quick', False))
        self.assertIn('僅修改', apply_rules('test', 'quick', True))
        self.assertNotIn('<image2>', apply_rules('test', 'superduper', True))
        self.assertIn('<image2>', apply_rules('test', 'reference', True))


if __name__ == '__main__':
    unittest.main()

import unittest

from mobile.nsfw_adv import graph


class NsfwAdvTest(unittest.TestCase):
    def test_author_recipe_is_grouped_in_one_graph(self):
        value = graph(dict(width=1024, height=1536, lokr_strength=1,
                           lightning_strength=.45, negative='模糊\n<水印>'), 'portrait', 12)
        self.assertEqual(value['6']['inputs']['text'], 'portrait')
        self.assertEqual(value['7']['inputs']['text'], '模糊\n<水印>')
        self.assertEqual(value['2']['inputs']['strength_model'], .45)
        self.assertEqual(value['3']['inputs']['strength_model'], 1)
        self.assertEqual(value['9']['inputs']['sampler_name'], 'res_2s')
        self.assertEqual(value['9']['inputs']['scheduler'], 'bong_tangent')
        self.assertEqual(value['9']['inputs']['steps'], 10)
        self.assertEqual(value['9']['inputs']['cfg'], 1)

    def test_img2img_encodes_source_and_applies_denoise(self):
        value = graph(dict(width=512, height=768, denoise=.4), 'blue teacup', 12, 'test/source.png')
        self.assertEqual(value['13']['inputs']['image'], 'test/source.png')
        self.assertEqual(value['8']['class_type'], 'VAEEncode')
        self.assertEqual(value['8']['inputs']['pixels'], ['14', 0])
        self.assertEqual(value['9']['inputs']['denoise'], .4)
        self.assertEqual(graph(dict(denoise=.4), 'test', 12)['9']['inputs']['denoise'], 1)


if __name__ == '__main__':
    unittest.main()

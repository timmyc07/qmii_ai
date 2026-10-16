import unittest

from mobile.nsfw_adv import graph


class NsfwAdvTest(unittest.TestCase):
    def test_author_recipe_is_grouped_in_one_graph(self):
        value = graph(dict(width=1024, height=1536, lokr_strength=1,
                           lightning_strength=.45), 'portrait', 12)
        self.assertEqual(value['2']['inputs']['strength_model'], .45)
        self.assertEqual(value['3']['inputs']['strength_model'], 1)
        self.assertEqual(value['9']['inputs']['sampler_name'], 'res_2s')
        self.assertEqual(value['9']['inputs']['scheduler'], 'bong_tangent')
        self.assertEqual(value['9']['inputs']['steps'], 10)
        self.assertEqual(value['9']['inputs']['cfg'], 1)


if __name__ == '__main__':
    unittest.main()

import unittest
from pathlib import Path
import sys

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_qwen_lora import split_projections


class QwenLoraTest(unittest.TestCase):
    def test_split_preserves_fused_projection(self):
        prefix = 'diffusion_model.transformer_blocks.0.img_mlp.gate_up'
        a = torch.arange(6, dtype=torch.float32).reshape(2, 3)
        b = torch.arange(8, dtype=torch.float32).reshape(4, 2)
        value = split_projections({prefix + '.lora_A.weight': a,
                                   prefix + '.lora_B.weight': b,
                                   prefix + '.alpha': torch.tensor(2.)})
        halves = []
        for name in ('gate_layer', 'proj'):
            target = 'transformer_blocks.0.img_mlp.' + name
            halves.append(value[target + '.lora_B.weight'] @ value[target + '.lora_A.weight'])
            self.assertEqual(value[target + '.alpha'].item(), 2.)
        torch.testing.assert_close(torch.cat(halves), b @ a)
        self.assertFalse(any('gate_up' in key for key in value))

    def test_rejects_invalid_fused_shape(self):
        prefix = 'diffusion_model.transformer_blocks.0.img_mlp.gate_up'
        with self.assertRaises(ValueError):
            split_projections({prefix + '.lora_A.weight': torch.zeros(2, 3),
                               prefix + '.lora_B.weight': torch.zeros(3, 2)})


if __name__ == '__main__':
    unittest.main()

"""Split Qwen 2.1 fused MLP LoRA projections for ComfyUI's gate/proj loader."""
from pathlib import Path
import sys

from safetensors import safe_open
from safetensors.torch import load_file, save_file


def split_projections(weights):
    result = dict(weights)
    for key in weights:
        if not key.endswith('.img_mlp.gate_up.lora_A.weight'):
            continue
        prefix = key.removesuffix('.lora_A.weight')
        b_key = prefix + '.lora_B.weight'
        a, b = weights[key], weights[b_key]
        if a.ndim != 2 or b.ndim != 2 or b.shape[0] % 2 or a.shape[0] != b.shape[1]:
            raise ValueError(f'Invalid fused LoRA shapes: {key}')
        del result[key], result[b_key]
        for name, half in zip(('gate_layer', 'proj'), b.chunk(2, dim=0)):
            target = prefix.removeprefix('diffusion_model.').replace('.gate_up', '.' + name)
            result[target + '.lora_A.weight'] = a.clone()
            result[target + '.lora_B.weight'] = half.contiguous().clone()
        alpha_key = prefix + '.alpha'
        if alpha_key in weights:
            del result[alpha_key]
            for name in ('gate_layer', 'proj'):
                target = prefix.removeprefix('diffusion_model.').replace('.gate_up', '.' + name)
                result[target + '.alpha'] = weights[alpha_key].clone()
    return result


if __name__ == '__main__':
    source, target = map(Path, sys.argv[1:])
    if source.resolve() == target.resolve():
        raise ValueError('Source and converted LoRA must have different paths.')
    with safe_open(source, framework='pt', device='cpu') as model:
        metadata = model.metadata()
    weights = split_projections(load_file(source))
    temporary = target.with_suffix('.part')
    save_file(weights, temporary, metadata=metadata)
    temporary.replace(target)
    print(f'Prepared ComfyUI LoRA: {target.name}')

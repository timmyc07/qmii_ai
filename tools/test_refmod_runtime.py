"""Validate the installed RefMod nodes on CPU without loading generation weights."""
import asyncio
import importlib
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mobile import h3
from mobile.superduper import COMFY, image_input

sys.path.insert(0, str(COMFY))
from comfy.cli_args import args
args.cpu = True

import execution
import nodes
import torch
from PIL import Image


async def main():
    for name in ('nodes_custom_sampler', 'nodes_video', 'nodes_audio', 'nodes_minimax_h3'):
        module = importlib.import_module('comfy_extras.' + name)
        extension = await module.comfy_entrypoint()
        for node in await extension.get_node_list():
            nodes.NODE_CLASS_MAPPINGS[node.define_schema().node_id] = node
    refmod = importlib.import_module('custom_nodes.ComfyUI-MiniMaxH3Mod.nodes')
    nodes.NODE_CLASS_MAPPINGS.update(refmod.NODE_CLASS_MAPPINGS)
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / 'source.png'
        Image.new('RGB', (256, 256), '#d8ad87').save(source)
        with image_input(source) as image:
            for profile in ('turbo4', 'turbo8', 'base'):
                h3.ensure_models(dict(video_profile=profile))
                for end in ('none', 'first', 'custom'):
                    graph = h3.graph(dict(refmod=True, video_profile=profile, end_frame=end), 'A still scene.', 42,
                                     image, image if end == 'custom' else None)
                    result = await execution.validate_prompt('refmod-check', graph, None)
                    assert result[0], (profile, end, result)
    keyframes = [{'resolved_frame_index': 0, 'latent': torch.zeros(1, 24, 1, 4, 4)}]
    original = [[torch.zeros(1, 1, 1), {'minimax_keyframes': keyframes}]]
    mod = refmod.H3RefMod(name='check', kind='image', latent=torch.ones(1, 24, 1, 4, 4), latent_h=4, latent_w=4)
    applied = refmod.MiniMaxH3RefModApply.execute(original, [(mod, 1.0)], max_total_tokens=1024)[0]
    assert applied[0][1]['minimax_keyframes'] is keyframes
    assert len(applied[0][1]['minimax_refs']) == 1
    assert 'minimax_refs' not in original[0][1]
    print('RefMod runtime passed: 3 profiles × 3 tail modes, native reference injection preserves keyframes.')


if __name__ == '__main__':
    asyncio.run(main())

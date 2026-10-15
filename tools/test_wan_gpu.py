"""Explicit local GPU smoke: tiny non-personal landscapes, real MP4 output."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from mobile.generation import generate, ROOT

mode = sys.argv[1] if len(sys.argv) > 1 else 'wan'
lora = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else ''
output = ROOT / 'output' / ('wan_smoke_' + mode + '_' + (lora or 'image' if '--image' in sys.argv else lora or 'base'))
output.mkdir(parents=True, exist_ok=True)
sources = []
if mode == 'wan_template' or '--image' in sys.argv:
    source = output / 'source.png'
    Image.new('RGB', (256, 256), (80, 150, 210)).save(source)
    sources.append(source)
result = generate(dict(workflow=mode, prompt='A quiet lake surrounded by mountains, gentle camera movement, landscape, no people',
                       lora=lora, lora_strength=.3, parameters=dict(width=256,height=256,frames=5,steps=6,cfg=1 if mode == 'wan_template' else 5,seed=123)),
                  sources, output, lambda message, results=None: print(message, flush=True))
path = output / result[0]
with path.open('rb') as stream:
    header = stream.read(32)
assert b'ftyp' in header, 'Output is not MP4'
print(json.dumps(dict(file=str(path),bytes=path.stat().st_size)), flush=True)

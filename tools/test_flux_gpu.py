"""Opt-in real FLUX/LoRA GPU regression with a fixed seed baseline."""
import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mobile import generation
from mobile.library import CATALOG


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    generation.flux.validate_models(generation.MODELS)
    generation.ensure_comfy()
    queue = generation.comfy_json('/queue')
    if any(queue.get(key) for key in ('queue_running', 'queue_pending')):
        raise RuntimeError('ComfyUI has pending work; retry after it finishes.')
    info = generation.comfy_json('/object_info')
    assert generation.flux.MODEL in info['CheckpointLoaderSimple']['input']['required']['ckpt_name'][0]
    loras = [item for item in CATALOG['loras'] if item['workflow'] == 'flux']
    assert len(loras) == 3
    for item in loras:
        assert item['file'] in info['LoraLoaderModelOnly']['input']['required']['lora_name'][0]
    destination = ROOT / 'output' / 'flux_validation' / time.strftime('%Y%m%d_%H%M%S')
    destination.mkdir(parents=True)
    report = dict(passed=False, seed=20261015, cases=[])
    baseline = None
    log = ROOT / '.runtime' / 'mobile' / 'comfyui.log'
    offset = log.stat().st_size if log.exists() else 0
    for item in [None, *loras]:
        name = item['id'] if item else 'baseline'
        target = destination / name
        target.mkdir()
        print('START ' + name, flush=True)
        started = time.monotonic()
        with patch('mobile.generation.secrets.randbelow', return_value=report['seed']):
            generation.generate(dict(workflow='flux', prompt=(
                'Full body studio fashion photograph of an adult woman, age 30, wearing a blue dress, '
                'standing naturally, neutral gray background, soft lighting, detailed realistic photograph.'),
                lora=item['id'] if item else '', lora_strength=.7), [], target,
                lambda message, *args: print(message, flush=True))
        output = target / '0.png'
        with Image.open(output) as image:
            image.load()
            assert image.size == (1024, 1024)
            assert max(ImageStat.Stat(image).stddev) > 5, 'Blank image'
            assert not any(key in image.info for key in ('prompt', 'workflow', 'parameters'))
            current = image.convert('RGB')
        difference = None
        if baseline is None:
            baseline = current.copy()
        else:
            difference = sum(ImageStat.Stat(ImageChops.difference(baseline, current)).mean) / 3
            assert difference > .01, 'LoRA did not change the fixed seed baseline'
        report['cases'].append(dict(lora=name, image=str(output), sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                                    difference_from_baseline=difference, elapsed_seconds=round(time.monotonic() - started, 1)))
        (destination / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print('PASS ' + name, flush=True)
    content = log.read_bytes()[offset:].decode('utf-8', errors='replace') if log.exists() else ''
    unloaded = [line for line in content.splitlines() if 'lora key not loaded' in line.lower() or 'NOT LOADED' in line]
    assert not unloaded, unloaded[:20]
    report.update(passed=True, unloaded_lora_keys=unloaded)
    (destination / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('ALL PASS ' + str(destination / 'report.json'), flush=True)


if __name__ == '__main__':
    main()

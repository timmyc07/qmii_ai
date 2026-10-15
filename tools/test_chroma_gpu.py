"""Opt-in Chroma smoke test through the same authenticated bridge used by Tauri."""
import json
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    started = time.monotonic()
    payload = dict(workflow='chroma', images=[], prompt=(
        'A small glossy blue ceramic teacup with a handle on a wooden table, '
        'soft morning light, realistic still life photograph, no text.'))
    process = subprocess.Popen([sys.executable, '-m', 'mobile.desktop', 'generate'], cwd=ROOT,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
    process.stdin.write(json.dumps(payload))
    process.stdin.close()
    images = []
    completed = False
    for line in process.stdout:
        event = json.loads(line)
        print(event.get('message', ''), flush=True)
        if event.get('error'):
            raise RuntimeError(event['error'])
        if event.get('image'):
            images.append(Path(event['image']))
        completed = completed or event.get('done', False)
    if process.wait() or not completed or len(images) != 1:
        raise RuntimeError(process.stderr.read() or 'Chroma did not complete with one image')
    with Image.open(images[0]) as image:
        image.load()
        assert image.size == (1024, 1024), image.size
        assert max(ImageStat.Stat(image).stddev) > 5, 'Blank image'
        assert not any(key in image.info for key in ('prompt', 'workflow', 'parameters'))
    report = dict(passed=True, workflow='chroma', image=str(images[0]), size=[1024, 1024],
                  elapsed_seconds=round(time.monotonic() - started, 1))
    destination = ROOT / '.runtime' / 'chroma_validation.json'
    destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()

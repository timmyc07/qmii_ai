"""Opt-in GPU acceptance through the desktop bridge and authenticated host queue."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mobile.generation import generate
from mobile.desktop import StudioClient

PROMPT = ('A realistic full-length photograph of a smiling adult man, 40 years old, '
          'standing upright, wearing a navy jacket and beige trousers, both feet visible, '
          'natural daylight, warm cream background, sharp details, no text, no watermark.')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('workflow', choices=['chroma_hades', 'chroma_full'])
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    state = ROOT / '.runtime' / 'chroma'
    state.mkdir(parents=True, exist_ok=True)
    images = []
    if args.workflow == 'chroma_full':
        source = args.source or state / 'validation_pose' / '0.png'
        if not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            print('Generating neutral adult pose reference with the existing Chroma workflow.', flush=True)
            generate(dict(workflow='chroma', prompt=PROMPT), [], source.parent,
                     lambda message, results=None: print(message, flush=True))
        images = [str(source.resolve())]
    started = time.monotonic()
    destination = state / (args.workflow + '_validation.json')
    report = dict(passed=False, workflow=args.workflow, prompt=PROMPT, images=images, started=time.time())
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    payload = dict(workflow=args.workflow, images=images, prompt=PROMPT, lora='', lora_strength=1.0)
    process = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'mobile.desktop', 'generate'], cwd=ROOT,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
    process.stdin.write(json.dumps(payload))
    process.stdin.close()
    paths = []
    complete = False
    previous = ''
    error = ''
    for line in process.stdout:
        event = json.loads(line)
        message = event.get('message', '')
        if message != previous:
            print(message, flush=True)
            previous = message
        if event.get('image'):
            paths.append(Path(event['image']))
        if event.get('error'):
            error = event['error']
        complete = complete or bool(event.get('done'))
    code = process.wait()
    if code or error or not complete or len(paths) != 1:
        report['error'] = error or process.stderr.read() or 'No final image'
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        raise RuntimeError(report['error'])
    with Image.open(paths[0]) as image:
        image.load()
        expected = (1792, 2304) if args.workflow == 'chroma_hades' else (4669, 4669)
        assert image.size == expected, image.size
        assert max(ImageStat.Stat(image).stddev) > 5, 'Blank output'
        assert not any(key in image.info for key in ('prompt', 'workflow', 'parameters'))
        report.update(passed=True, image=str(paths[0]), size=list(image.size),
                      elapsed_seconds=round(time.monotonic() - started, 1))
    client = StudioClient()
    client.connect()
    try:
        job = client.request('/api/jobs/' + paths[0].parent.name)
        assert job['workflow'] == args.workflow and job['status'] == 'completed'
        assert len(job['results']) == 1
        downloaded = client.opener.open(client.url + job['results'][0], timeout=60).read()
        assert downloaded == paths[0].read_bytes(), 'Authenticated download differs from desktop output'
        report['download_sha256'] = hashlib.sha256(downloaded).hexdigest()
    finally:
        client.request('/api/logout', method='POST')
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

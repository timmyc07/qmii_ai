"""Exercise the real mobile HTTP -> GPU -> protected download path."""
import argparse
from pathlib import Path
import secrets
import time

import httpx
from PIL import Image

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:8787')
parser.add_argument('--workflow', choices=['quick', 'reference', 'superduper', 'nsfw_adv'], default='quick')
parser.add_argument('--image', type=Path, action='append')
args = parser.parse_args()
url = args.url.rstrip('/')
with httpx.Client(base_url=url, timeout=30, headers={'Origin': url}) as client:
    assert client.get('/api/jobs').status_code == 401
    code = (root / '.runtime' / 'mobile' / 'access-code.txt').read_text().strip()
    login = client.post('/api/login', json={'code': code})
    login.raise_for_status()
    client.headers['X-Qianmi-CSRF'] = login.json()['csrf']
    sources = []
    for image in args.image or []:
        upload = client.post('/api/uploads', content=image.read_bytes(), headers={'Content-Type': 'image/png'})
        upload.raise_for_status()
        sources.append(upload.json()['id'])
    prompt = 'Keep the same subject, use soft warm studio lighting.' if sources else 'A small ceramic teacup on a wooden table, soft morning light, still life photograph.'
    response = client.post('/api/jobs', json=dict(prompt=prompt, workflow=args.workflow, images=sources, request_id=secrets.token_hex(16)))
    response.raise_for_status()
    job = response.json()
    print(f'job={job["id"]} workflow={args.workflow}', flush=True)
    last = ''
    deadline = time.monotonic() + 1500
    while time.monotonic() < deadline:
        response = client.get('/api/jobs/' + job['id'])
        response.raise_for_status()
        job = response.json()
        if job['message'] != last:
            print(f'{job["status"]}: {job["message"]}', flush=True)
            last = job['message']
        if job['status'] in ('completed', 'failed'):
            break
        time.sleep(2)
    assert job['status'] == 'completed', job['message']
    assert job['prompt'] == prompt
    result = client.get(job['results'][0])
    result.raise_for_status()
    path = root / 'output' / f'mobile-{args.workflow}-smoke.png'
    path.write_bytes(result.content)
    with Image.open(path) as image:
        image.verify()
    print(f'PASS protected download={len(result.content)} bytes output={path}', flush=True)
    with httpx.Client(base_url=url, timeout=30) as guest:
        assert guest.get(job['results'][0]).status_code == 401

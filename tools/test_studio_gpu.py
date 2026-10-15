"""Opt-in real GPU validation of desktop bridge and browser UI with the same inputs."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import httpx
from PIL import Image, ImageDraw, ImageStat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mobile.desktop import StudioClient


def browser(payload):
    result = subprocess.run(['node', str(ROOT / 'tools' / 'gpu_browser.cjs')],
                            input=json.dumps(payload), text=True, encoding='utf-8', capture_output=True,
                            cwd=ROOT, timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    value = json.loads(result.stdout)
    assert not value['browserErrors'], value['browserErrors']
    return value


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    destination = ROOT / 'output' / 'gpu_validation' / time.strftime('%Y%m%d_%H%M%S')
    destination.mkdir(parents=True)
    record = dict(boundary='Desktop Python bridge invoked by Tauri vs real Edge studio UI',
                  comparison='Independent random seeds; compare count, dimensions, visual quality and shared result bytes.',
                  cases=[], max_running=0, passed=False)
    (destination / 'report.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    client = StudioClient()
    client.connect()
    fixed = client.request('/api/settings')['fixedPrompt'].strip()
    prompts = dict(quick='A small glossy blue ceramic teacup with a handle on a wooden table, soft morning light, realistic still life photograph, no text.',
                   reference='Create one coherent realistic product photograph: use the blue ceramic teacup from image1 and the green botanical garden atmosphere from image2. One teacup on a stone table, soft daylight, no collage, no panels, no text.',
                   t2i='A small glossy blue ceramic teacup with a handle on a wooden table, soft morning light, realistic still life photograph, no text.',
                   edit='Keep the same blue ceramic teacup and its handle. Add one small yellow lemon on the wooden table beside the cup. Realistic still life photograph, no text.')
    inputs = []
    try:
        for case, workflow in [('quick', 'quick'), ('reference', 'reference'), ('t2i', 'pose'), ('edit', 'pose')]:
            sources = inputs if case == 'reference' else inputs[:1] if case == 'edit' else []
            print(f'START {case}: browser UI + desktop bridge, input_images={len(sources)}', flush=True)
            web = browser(dict(workflow=workflow, prompt=prompts[case], images=[str(path) for path in sources]))
            assert web['fixedPrompt'].strip() == fixed, 'Shared settings changed during test'
            payload = dict(workflow=workflow, prompt='\n\n'.join(filter(None, [fixed, prompts[case]])),
                           images=[str(path) for path in sources])
            desktop = subprocess.Popen([sys.executable, '-m', 'mobile.desktop', 'generate'], cwd=ROOT,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
            desktop.stdin.write(json.dumps(payload))
            desktop.stdin.close()
            # Bridge emits small progress events; use a file so a long GPU job
            # cannot block on a full stdout pipe while the observer polls jobs.
            import threading
            events = []
            def read_events():
                for line in desktop.stdout:
                    events.append(json.loads(line))
            reader = threading.Thread(target=read_events, daemon=True)
            reader.start()
            start = time.monotonic()
            last = None
            while time.monotonic() - start < 2400:
                jobs = client.request('/api/jobs')['jobs']
                running = sum(job['status'] == 'running' for job in jobs)
                record['max_running'] = max(record['max_running'], running)
                assert running <= 1, 'Two GPU jobs running simultaneously'
                job = client.request('/api/jobs/' + web['jobId'])
                state = (job['status'], job['message'], desktop.poll())
                if state != last:
                    print(f'{case}: web={job["status"]} {job["message"]}; desktop={"working" if desktop.poll() is None else "finished"}', flush=True)
                    last = state
                if job['status'] in ('completed', 'failed') and desktop.poll() is not None:
                    break
                time.sleep(3)
            else:
                raise TimeoutError('GPU validation timed out; host jobs were left intact for safe inspection')
            reader.join(10)
            assert desktop.returncode == 0, desktop.stderr.read()
            assert job['status'] == 'completed', job['message']
            assert any(event['done'] and not event['error'] for event in events), events[-1:]
            paths = [Path(event['image']) for event in events if event['image']]
            assert len(paths) == 1, 'Unexpected desktop batch output count'
            desktop_id = paths[0].parent.name
            desktop_job = client.request('/api/jobs/' + desktop_id)
            for endpoint, current in [('web', job), ('desktop', desktop_job)]:
                assert current['status'] == 'completed' and len(current['results']) == 1
                data = client.opener.open(client.url + current['results'][0], timeout=30).read()
                actual = ROOT / 'output' / 'mobile' / current['id'] / '0.png'
                assert actual.read_bytes() == data, 'Desktop file and authenticated web download differ'
                with Image.open(io.BytesIO(data)) as image:
                    image.load()
                    assert image.format == 'PNG' and min(image.size) >= 512
                    assert max(ImageStat.Stat(image).stddev) > 5, 'Blank or nearly flat image'
                    assert not any(key in image.info for key in ('prompt', 'workflow', 'parameters'))
                    size = list(image.size)
                copy = destination / f'{case}_{endpoint}.png'
                copy.write_bytes(data)
                with httpx.Client(timeout=15) as guest:
                    assert guest.get(client.url + current['results'][0]).status_code == 401
                record['cases'].append(dict(case=case, endpoint=endpoint, job=current['id'], status=current['status'],
                                            input_images=len(sources), output_images=1, size=size,
                                            sha256=hashlib.sha256(data).hexdigest(), image=copy.name,
                                            shared_download_identical=True, guest_denied=True,
                                            elapsed_seconds=round(time.monotonic() - start, 1)))
            assert record['cases'][-1]['size'] == record['cases'][-2]['size'], 'Endpoint output dimensions differ'
            (destination / 'report.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'PASS {case}: desktop/web output {size}, shared file/download identical', flush=True)
            if case == 'quick':
                cup = destination / 'quick_web.png'
                # Deterministic second reference image, independent of generated
                # subject: a green botanical palette and leaf arrangement.
                garden = Image.new('RGB', (1024, 1024), '#c5d9bd')
                draw = ImageDraw.Draw(garden)
                for i in range(12):
                    x, y = (i * 137) % 900, (i * 211) % 900
                    draw.ellipse((x, y, x + 220, y + 110), fill=['#38704b', '#81a664', '#e3ecd0'][i % 3])
                garden.save(destination / 'garden_reference.png')
                inputs = [cup, destination / 'garden_reference.png']
        observed = browser(dict(action='observe', ids=[value['job'] for value in record['cases']],
                                screenshot=str(destination / 'browser_desktop.png'),
                                mobileScreenshot=str(destination / 'browser_mobile.png')))
        assert len(observed['observed']) == 8
        jobs = subprocess.run([sys.executable, '-m', 'mobile.desktop', 'jobs'], cwd=ROOT, capture_output=True,
                              text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW, timeout=45)
        assert jobs.returncode == 0, jobs.stderr
        desktop_jobs = {job['id']: job for job in json.loads(jobs.stdout)['jobs']}
        assert all(value['job'] in desktop_jobs for value in record['cases'])
        record.update(passed=True, browser_observed_all=True, desktop_observed_all=True)
        (destination / 'report.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'ALL PASS report={destination / "report.json"}', flush=True)
    finally:
        client.request('/api/logout', method='POST')


if __name__ == '__main__':
    main()

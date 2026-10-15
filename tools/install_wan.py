"""Install missing 14B recipe weights, verifying Hugging Face LFS SHA-256."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import subprocess
import os
from pathlib import Path
import urllib.request

FILES = [
    ('QuantStack/Wan2.2-I2V-A14B-GGUF', 'LowNoise/Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf', 'unet'),
    ('Comfy-Org/Wan_2.1_ComfyUI_repackaged', 'split_files/vae/wan_2.1_vae.safetensors', 'vae'),
    ('Comfy-Org/Wan_2.1_ComfyUI_repackaged', 'split_files/clip_vision/clip_vision_h.safetensors', 'clip_vision'),
]


def install(item, model_root=Path(r'D:\AI\ComfyUI-Models')):
    repo, filename, folder = item
    request = urllib.request.Request('https://huggingface.co/api/models/' + repo + '/paths-info/main',
                                     data=json.dumps({'paths': [filename]}).encode(),
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        metadata = json.load(response)[0]
    digest, size = metadata['lfs']['oid'], metadata['size']
    target = model_root / folder / Path(filename).name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.stat().st_size == size and sha256(target) == digest:
            print('Verified: ' + target.name, flush=True)
            return
        raise RuntimeError('Existing model differs: ' + str(target))
    temporary = target.with_suffix(target.suffix + '.part')
    print('Downloading: ' + target.name, flush=True)
    subprocess.run(['curl.exe', '--fail', '--location', '--retry', '3', '--retry-delay', '3',
                    '--connect-timeout', '30', '--speed-limit', '1024', '--speed-time', '60',
                    '--continue-at', '-', '--silent', '--show-error', '--output', str(temporary),
                    'https://huggingface.co/' + repo + '/resolve/main/' + filename + '?download=true'],
                   check=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if temporary.stat().st_size != size or sha256(temporary) != digest:
        raise RuntimeError('Download verification failed: ' + target.name)
    temporary.replace(target)
    print('Verified: ' + target.name, flush=True)


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(install, FILES))

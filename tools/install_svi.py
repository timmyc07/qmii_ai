"""Install pinned SVI nodes and share the previously downloaded local models."""
import hashlib
import io
import json
import shutil
import struct
import subprocess
import tempfile
from urllib.request import urlopen
import zipfile
from pathlib import Path

from mobile.superduper import COMFY, PYTHON, FLAGS
from mobile.svi import FILES, MODELS, LIGHTNING_HIGH, ensure_models

PACKS = (
    ('city96', 'ComfyUI-GGUF', '6ea2651e7df66d7585f6ffee804b20e92fb38b8a',
     'aad273a0b774684285b4496f6edff7e2293bd29d71ef89926d6861bfdf4947ac'),
    ('kijai', 'ComfyUI-KJNodes', '17195fcfa8a05f601b766a0f09c9733284f47416',
     '6d97e7483d1d73ca90249e2f993c73c972e591a30babc8c5609b097100a650cb'),
)


def prepare_lightning(source, target):
    if target.is_file():
        return
    with source.open('rb') as weights:
        header = json.loads(weights.read(struct.unpack('<Q', weights.read(8))[0]))
        if sum(key.endswith('.diff_m') for key in header) != 41:
            raise RuntimeError('Lightning 高噪 LoRA 格式不符，未轉換。')
        # WanVideoWrapper maps these modulation deltas to ComfyUI's native diff format.
        header = {key.replace('.diff_m', '.modulation.diff'): value for key, value in header.items()}
        encoded = json.dumps(header, separators=(',', ':')).encode('utf-8')
        encoded += b' ' * (-len(encoded) % 8)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix('.download')
        try:
            with partial.open('wb') as output:
                output.write(struct.pack('<Q', len(encoded)))
                output.write(encoded)
                shutil.copyfileobj(weights, output)
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)


def install():
    if not PYTHON.is_file() or not (COMFY / 'main.py').is_file():
        raise RuntimeError('請先安裝 ComfyUI Portable。')
    for owner, pack, revision, expected in PACKS:
        target = COMFY / 'custom_nodes' / pack
        if target.exists():
            marker = target / '.qianmi-revision'
            if not marker.is_file() or marker.read_text().strip() != revision:
                raise RuntimeError(f'已有其他版本 {pack}，未覆寫；請先確認原節點套件。')
            continue
        with urlopen(f'https://codeload.github.com/{owner}/{pack}/zip/{revision}', timeout=120) as response:
            archive = response.read()
        if hashlib.sha256(archive).hexdigest() != expected:
            raise RuntimeError(f'{pack} 下載校驗失敗，未安裝。')
        with tempfile.TemporaryDirectory(prefix='qianmi_svi_', dir=target.parent) as directory:
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                bundle.extractall(directory)
            source = Path(directory) / f'{pack}-{revision}'
            (source / '.qianmi-revision').write_text(revision, encoding='utf-8')
            source.rename(target)
    subprocess.run([str(PYTHON), '-X', 'utf8', '-s', '-m', 'pip', 'install', '--disable-pip-version-check',
                    'gguf==0.19.0', 'color-matcher==0.6.0', 'mss==10.2.0'],
                   check=True, creationflags=FLAGS)
    prepare_lightning(MODELS / 'loras' / FILES['loras'][2], COMFY / 'models' / 'loras' / LIGHTNING_HIGH)
    ensure_models()
    print('SVI 節點與模型已就緒；每次生成使用獨立程序，結束後自動釋放。', flush=True)


if __name__ == '__main__':
    install()

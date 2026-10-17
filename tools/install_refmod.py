"""Install the reviewed RefMod revision without replacing an existing node pack."""
import hashlib
import io
from pathlib import Path
import tempfile
from urllib.request import urlopen
import zipfile

from mobile.superduper import COMFY

REVISION = '517e8c419a8584fbf69fceb487bc39d83e6a6ec8'
SHA256 = '53c2b89eac307d7d22d27803df150f6a6e429234ecf36f4a29c3fe04cbdbb523'
PACK = 'ComfyUI-MiniMaxH3Mod'


def install():
    if not (COMFY / 'main.py').is_file():
        raise RuntimeError('請先安裝 ComfyUI Portable。')
    target = COMFY / 'custom_nodes' / PACK
    if target.exists():
        marker = target / '.qianmi-revision'
        if not marker.is_file() or marker.read_text().strip() != REVISION:
            raise RuntimeError('已有其他版本 RefMod，未覆寫；請先確認並移開原節點套件。')
        print(f'RefMod 已安裝：{REVISION}', flush=True)
        return
    url = f'https://codeload.github.com/Luisacaotica/{PACK}/zip/{REVISION}'
    with urlopen(url, timeout=120) as response:
        archive = response.read()
    if hashlib.sha256(archive).hexdigest() != SHA256:
        raise RuntimeError('RefMod 下載 SHA256 不符，未安裝。')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='qianmi_refmod_', dir=target.parent) as directory:
        # The pinned archive is authenticated by its digest before extraction.
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            bundle.extractall(directory)
        source = Path(directory) / f'{PACK}-{REVISION}'
        (source / '.qianmi-revision').write_text(REVISION, encoding='utf-8')
        source.rename(target)
    print('RefMod 已安裝；請在 ComfyUI 佇列空閒時重新啟動服務。', flush=True)


if __name__ == '__main__':
    install()

"""Install the official Wan TI2V-5B weights; no nodes or attention packages."""
import hashlib
import shutil
from urllib.request import urlopen

from mobile.superduper import COMFY

REVISION = 'ee6f4a40737a995bf5818954cfce6d59443b0f04'
FILES = {
    'diffusion_models/wan2.2_ti2v_5B_fp16.safetensors': '456f901338bd9eadbded3828b819109a9b68e8a525ca5cf8d0049a69fcfeca1e',
    'text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors': 'c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68',
    'vae/wan2.2_vae.safetensors': 'e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156',
}


def install():
    if not (COMFY / 'main.py').is_file():
        raise RuntimeError('請先安裝 ComfyUI Portable。')
    for name, expected in FILES.items():
        target = COMFY / 'models' / name
        if target.is_file():
            with target.open('rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != expected:
                    raise RuntimeError(f'模型校驗失敗，未覆寫：{target}')
            print(f'已驗證 {target.name}', flush=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix('.download')
        print(f'下載 {target.name}', flush=True)
        try:
            url = f'https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/{REVISION}/split_files/{name}'
            with urlopen(url, timeout=120) as response, partial.open('wb') as output:
                shutil.copyfileobj(response, output)
            with partial.open('rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != expected:
                    raise RuntimeError(f'下載校驗失敗：{target.name}')
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
        print(f'已驗證 {target.name}', flush=True)


if __name__ == '__main__':
    install()

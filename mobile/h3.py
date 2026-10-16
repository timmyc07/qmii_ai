"""MiniMax H3 image-to-video recipe, using the supplied workflow's native nodes."""
import os
from pathlib import Path
import shutil
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from .superduper import COMFY, PYTHON, URL, ComfyWorkflowError, ensure_server, image_input, request_json, workflow_error

MODELS = Path(r'D:\AI-Manju\Models')
FILES = {
    'diffusion_models': ['minimax_h3_fl2va_pruned_int8_convrot.safetensors'],
    'text_encoders': ['qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors'],
    'vae': ['minimax_h3_video_vae_fp16.safetensors', 'minimax_h3_audio_vae_fp32.safetensors'],
    'loras': ['minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors'],
}


def frames(duration):
    length = max(5, round(duration * 24))
    return length + (5 - length % 17) % 17


def graph(parameters, prompt, seed, image):
    width, height = parameters.get('width', 512), parameters.get('height', 896)
    value = {
        'model': {'class_type': 'UNETLoader', 'inputs': {'unet_name': FILES['diffusion_models'][0], 'weight_dtype': 'default'}},
        'turbo': {'class_type': 'LoraLoaderModelOnly', 'inputs': {
            'model': ['model', 0], 'lora_name': FILES['loras'][0], 'strength_model': 1}},
        'clip': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': FILES['text_encoders'][0], 'type': 'minimax', 'device': 'default'}},
        'vae': {'class_type': 'VAELoader', 'inputs': {'vae_name': FILES['vae'][0]}},
        'audio_vae': {'class_type': 'VAELoader', 'inputs': {'vae_name': FILES['vae'][1]}},
        'fit': {'class_type': 'ImageScale', 'inputs': {
            'image': ['first', 0], 'upscale_method': 'lanczos', 'width': width, 'height': height, 'crop': 'center'}},
        'condition': {'class_type': 'MiniMaxH3ImageToVideo', 'inputs': {
            'clip': ['clip', 0], 'vae': ['vae', 0], 'first_frame': ['fit', 0], 'prompt': prompt,
            'width': width, 'height': height, 'length': frames(parameters.get('duration', 12))}},
        'noise': {'class_type': 'RandomNoise', 'inputs': {'noise_seed': seed}},
        'sampler': {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': 'res_multistep'}},
        'scheduler': {'class_type': 'BasicScheduler', 'inputs': {'model': ['turbo', 0], 'scheduler': 'simple', 'steps': 4, 'denoise': 1}},
        'guider': {'class_type': 'BasicGuider', 'inputs': {'model': ['turbo', 0], 'conditioning': ['condition', 0]}},
        'sample': {'class_type': 'SamplerCustomAdvanced', 'inputs': {
            'noise': ['noise', 0], 'guider': ['guider', 0], 'sampler': ['sampler', 0],
            'sigmas': ['scheduler', 0], 'latent_image': ['condition', 1]}},
        'decode': {'class_type': 'VAEDecode', 'inputs': {'samples': ['sample', 0], 'vae': ['vae', 0]}},
        'audio': {'class_type': 'VAEDecodeAudio', 'inputs': {'samples': ['sample', 0], 'vae': ['audio_vae', 0]}},
        'video': {'class_type': 'CreateVideo', 'inputs': {
            'images': ['decode', 0], 'audio': ['audio', 0], 'fps': 24, 'bit_depth': 8, 'color_space': 'sRGB', 'codec': 'h264'}},
        'save': {'class_type': 'SaveVideo', 'inputs': {
            'video': ['video', 0], 'filename_prefix': 'qianmi_h3/clip', 'format': 'mp4', 'format.codec': 'auto'}},
    }
    value['first'] = {'class_type': 'LoadImage', 'inputs': {'image': image}}
    return value


def ensure_models():
    if not PYTHON.is_file() or not (COMFY / 'main.py').is_file():
        raise ComfyWorkflowError('H3 需要千迷 AI 的 ComfyUI Portable 執行環境，請執行 tools/install-superduper.ps1。')
    for folder, names in FILES.items():
        for name in names:
            target = COMFY / 'models' / folder / name
            if target.is_file():
                continue
            source = MODELS / folder / name
            if not source.is_file():
                raise ComfyWorkflowError(f'H3 缺少模型：{source}')
            target.parent.mkdir(parents=True, exist_ok=True)
            # Both model locations are on D:; share the weights without copying tens of GB.
            os.link(source, target)


def run(parameters, prompt, seed, output, progress, source):
    ensure_models()
    with image_input(source) as image:
        value = graph(parameters, prompt, seed, image)
        progress('正在準備 H3 影片服務，首次載入需要較長時間…')
        ensure_server({node['class_type'] for node in value.values()})
        try:
            prompt_id = request_json('/prompt', {'prompt': value}, 30)['prompt_id']
        except HTTPError:
            raise ComfyWorkflowError('H3 工作流未通過節點驗證，請查看 .runtime/superduper.log。') from None
        progress('正在將首幀生成有聲影片…')
        for _ in range(7200):
            history = request_json(f'/history/{prompt_id}', timeout=30)
            if prompt_id in history:
                result = history[prompt_id]
                if result.get('status', {}).get('status_str') == 'error':
                    raise workflow_error('H3', result['status'], value)
                if result.get('status', {}).get('completed'):
                    files = result.get('outputs', {}).get('save', {}).get('images', [])
                    if not files:
                        raise ComfyWorkflowError('H3 未產生影片，請查看 .runtime/superduper.log。')
                    query = urlencode({key: files[-1][key] for key in ('filename', 'subfolder', 'type')})
                    with urlopen(URL + '/view?' + query, timeout=120) as response, (output / '0.mp4').open('wb') as target:
                        shutil.copyfileobj(response, target)
                    if not (output / '0.mp4').stat().st_size:
                        raise ComfyWorkflowError('H3 輸出檔案為空，請查看 .runtime/superduper.log。')
                    return ['0.mp4']
            time.sleep(1)
    raise ComfyWorkflowError('H3 影片生成逾時，請查看 .runtime/superduper.log。')

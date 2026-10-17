"""MiniMax H3 image-to-video recipe, using the supplied workflow's native nodes."""
from contextlib import ExitStack
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
    'loras': ['minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors',
              'minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors'],
}


def frames(duration):
    length = max(5, round(duration * 24))
    return length + (5 - length % 17) % 17


def conditioning_prompt(parameters, prompt):
    if parameters.get('end_frame', 'none') != 'none' and '<Picture 2>' not in prompt:
        end = (frames(parameters.get('duration', 12)) - 1) / 24
        prompt = f'For the target video, at {end:.3f} seconds, <Picture 2> is fully referenced as the last frame.\n\n' + prompt
    if parameters.get('identity_prompt'):
        text = "Preserve the identity and distinguishing features of the subject in <Picture 1> throughout the shot. "
        tag = 'integrated_multimodal_description:'
        if tag in prompt:
            prompt = prompt.replace(tag, tag + ' ' + text, 1)
        else:
            prompt = tag + ' [Shot 1] ' + text + '\n' + prompt
    return prompt


def graph(parameters, prompt, seed, image, last_image=None):
    width, height = parameters.get('width', 512), parameters.get('height', 896)
    profile = parameters.get('video_profile', 'turbo4')
    steps = {'turbo4': 4, 'turbo8': 8, 'base': parameters.get('steps', 20)}[profile]
    resize = dict(upscale_method=parameters.get('resize_method', 'lanczos'), width=width, height=height,
                  crop=parameters.get('crop', 'center'))
    value = {
        'model': {'class_type': 'UNETLoader', 'inputs': {'unet_name': FILES['diffusion_models'][0], 'weight_dtype': 'default'}},
        'shift': {'class_type': 'MiniMaxH3SigmaShift', 'inputs': {
            'model': ['model' if profile == 'base' else 'turbo', 0],
            'shift_video': parameters.get('shift_video', 6 if profile == 'turbo4' else 12),
            'shift_audio': parameters.get('shift_audio', 3)}},
        'clip': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': FILES['text_encoders'][0], 'type': 'minimax', 'device': 'default'}},
        'vae': {'class_type': 'VAELoader', 'inputs': {'vae_name': FILES['vae'][0]}},
        'audio_vae': {'class_type': 'VAELoader', 'inputs': {'vae_name': FILES['vae'][1]}},
        'fit': {'class_type': 'ImageScale', 'inputs': {'image': ['first', 0], **resize}},
        'condition': {'class_type': 'MiniMaxH3ImageToVideo', 'inputs': {
            'clip': ['clip', 0], 'vae': ['vae', 0], 'first_frame': ['fit', 0], 'prompt': conditioning_prompt(parameters, prompt),
            'width': width, 'height': height, 'length': frames(parameters.get('duration', 12))}},
        'noise': {'class_type': 'RandomNoise', 'inputs': {'noise_seed': seed}},
        'sampler': {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': parameters.get('sampler', 'euler')}},
        'scheduler': {'class_type': 'BasicScheduler', 'inputs': {'model': ['shift', 0], 'scheduler': 'simple', 'steps': steps, 'denoise': 1}},
        'guider': {'class_type': 'BasicGuider', 'inputs': {'model': ['shift', 0], 'conditioning': ['condition', 0]}},
        'sample': {'class_type': 'SamplerCustomAdvanced', 'inputs': {
            'noise': ['noise', 0], 'guider': ['guider', 0], 'sampler': ['sampler', 0],
            'sigmas': ['scheduler', 0], 'latent_image': ['condition', 1]}},
        'decode': {'class_type': 'VAEDecode', 'inputs': {'samples': ['sample', 0], 'vae': ['vae', 0]}},
        'audio': {'class_type': 'VAEDecodeAudio', 'inputs': {'samples': ['sample', 0], 'vae': ['audio_vae', 0]}},
        'video': {'class_type': 'CreateVideo', 'inputs': {
            'images': ['decode', 0], 'audio': ['audio', 0], 'fps': 24, 'bit_depth': 8, 'color_space': 'sRGB', 'codec': 'none'}},
        'save': {'class_type': 'SaveVideo', 'inputs': {
            'video': ['video', 0], 'filename_prefix': 'qianmi_h3/clip', 'format': 'mp4', 'format.codec': 'h264',
            'format.codec.encoding': 're-encode', 'format.codec.encoding.crf': parameters.get('video_crf', 18)}},
    }
    value['first'] = {'class_type': 'LoadImage', 'inputs': {'image': image}}
    if profile != 'base':
        value['turbo'] = {'class_type': 'LoraLoaderModelOnly', 'inputs': {
            'model': ['model', 0], 'lora_name': FILES['loras'][0 if profile == 'turbo4' else 1],
            'strength_model': parameters.get('lora_strength', 1)}}
    end = parameters.get('end_frame', 'none')
    if end == 'first':
        value['condition']['inputs']['last_frame'] = ['fit', 0]
    elif end == 'custom':
        if last_image is None:
            raise ValueError('請選擇尾幀圖片。')
        value['last'] = {'class_type': 'LoadImage', 'inputs': {'image': last_image}}
        value['last_fit'] = {'class_type': 'ImageScale', 'inputs': {'image': ['last', 0], **resize}}
        value['condition']['inputs']['last_frame'] = ['last_fit', 0]
    if parameters.get('refmod'):
        value['refmod_extract'] = {'class_type': 'MiniMaxH3RefModExtract', 'inputs': {
            'name': 'qianmi_identity', 'mode': 'Full Reference', 'concept_type': 'identity',
            'refs_image.ref_image_1': ['fit', 0], 'vae': ['vae', 0], 'background_retention': 0,
            'ref_resolution': 512, 'pool_h': 16, 'pool_w': 16, 'latent_frames': 1, 'identity': 0,
            'merge': False, 'motion_only': False, 'multiplier': 1, 'max_tokens': 1024,
            'extraction_preset': 'manual', 'description': '', 'save': False, 'budget_policy': 'error'}}
        value['refmod_apply'] = {'class_type': 'MiniMaxH3RefModApply', 'inputs': {
            'conditioning': ['condition', 0], 'mods': ['refmod_extract', 0], 'override': False,
            'retention': 1, 'curve_direction': 'constant', 'curve_shape': 'linear', 'curve_value': 1,
            'scramble_seed': -1, 'max_total_tokens': 1024}}
        value['guider']['inputs']['conditioning'] = ['refmod_apply', 0]
    if not parameters.get('video_audio', True):
        del value['audio'], value['audio_vae'], value['video']['inputs']['audio']
    return value


def ensure_models(parameters=None):
    if not PYTHON.is_file() or not (COMFY / 'main.py').is_file():
        raise ComfyWorkflowError('H3 需要千迷 AI 的 ComfyUI Portable 執行環境，請執行 tools/install-superduper.ps1。')
    profile = (parameters or {}).get('video_profile', 'turbo4')
    files = {**FILES, 'loras': [] if profile == 'base' else [FILES['loras'][profile == 'turbo8']]}
    for folder, names in files.items():
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


def run(parameters, prompt, seed, output, progress, source, last_source=None):
    ensure_models(parameters)
    with ExitStack() as stack:
        image = stack.enter_context(image_input(source))
        last = stack.enter_context(image_input(last_source)) if last_source is not None else None
        value = graph(parameters, prompt, seed, image, last)
        progress('正在準備 H3 影片服務，首次載入需要較長時間…')
        if parameters.get('refmod'):
            if not (COMFY / 'custom_nodes' / 'ComfyUI-MiniMaxH3Mod' / '__init__.py').is_file():
                raise ComfyWorkflowError('RefMod 尚未安裝，請執行 python -m tools.install_refmod。')
            progress('已啟用 RefMod，正在從本支影片首幀建立身分參考…')
        ensure_server({node['class_type'] for node in value.values()})
        progress('正在將首幀生成影片…')
        return execute_video(value, output, 'H3')


def execute_video(value, output, name):
    try:
        prompt_id = request_json('/prompt', {'prompt': value}, 30)['prompt_id']
    except HTTPError:
        raise ComfyWorkflowError(f'{name} 工作流未通過節點驗證，請查看 .runtime/superduper.log。') from None
    for _ in range(7200):
        history = request_json(f'/history/{prompt_id}', timeout=30)
        if prompt_id in history:
            result = history[prompt_id]
            if result.get('status', {}).get('status_str') == 'error':
                raise workflow_error(name, result['status'], value)
            if result.get('status', {}).get('completed'):
                files = result.get('outputs', {}).get('save', {}).get('images', [])
                if not files:
                    raise ComfyWorkflowError(f'{name} 未產生影片，請查看 .runtime/superduper.log。')
                query = urlencode({key: files[-1][key] for key in ('filename', 'subfolder', 'type')})
                with urlopen(URL + '/view?' + query, timeout=120) as response, output.open('wb') as target:
                    shutil.copyfileobj(response, target)
                if not output.stat().st_size:
                    raise ComfyWorkflowError(f'{name} 輸出檔案為空，請查看 .runtime/superduper.log。')
                return [output.name]
        time.sleep(1)
    raise ComfyWorkflowError(f'{name} 影片生成逾時，請查看 .runtime/superduper.log。')

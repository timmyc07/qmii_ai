"""Three-part Wan 2.2 SVI Pro video in a task-owned ComfyUI process."""
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.error import URLError

from .cancellation import CURRENT, CancellationFailed, task_scope
from .h3 import execute_video
from .superduper import COMFY, PYTHON, ROOT, FLAGS, LOG, ComfyWorkflowError, image_input, release_models, request_json

URL = 'http://127.0.0.1:8192'
MODELS = Path(r'D:\AI\ComfyUI-Models')
FILES = {
    'diffusion_models': ['wan2.2_i2v_high_noise_14B_Q8_0.gguf', 'wan2.2_i2v_low_noise_14B_Q8_0.gguf'],
    'loras': ['SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH_lora_rank_128_fp16.safetensors',
              'SVI_v2_PRO_Wan2.2-I2V-A14B_LOW_lora_rank_128_fp16.safetensors',
              'wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors',
              'wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors'],
    'vae': ['wan_2.1_vae.safetensors'],
    'text_encoders': ['umt5_xxl_fp8_e4m3fn_scaled.safetensors'],
}
NEGATIVE = '过曝，静态，细节模糊不清，作品，画作，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走'
LIGHTNING_HIGH = FILES['loras'][2].replace('.safetensors', '_comfy.safetensors')


def graph(parameters, seed, image):
    value = {
        'clip': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': FILES['text_encoders'][0], 'type': 'wan', 'device': 'default'}},
        'vae': {'class_type': 'VAELoader', 'inputs': {'vae_name': FILES['vae'][0]}},
        'first': {'class_type': 'LoadImage', 'inputs': {'image': image}},
        'fit': {'class_type': 'ImageResizeKJv2', 'inputs': {
            'image': ['first', 0], 'width': 480, 'height': 720, 'upscale_method': 'lanczos',
            'keep_proportion': 'crop', 'pad_color': '0, 0, 0', 'crop_position': 'center', 'divisible_by': 2, 'device': 'cpu'}},
        'anchor': {'class_type': 'VAEEncode', 'inputs': {'pixels': ['fit', 0], 'vae': ['vae', 0]}},
        'negative': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['clip', 0], 'text': parameters.get('negative', NEGATIVE)}},
        'noise': {'class_type': 'RandomNoise', 'inputs': {'noise_seed': seed}},
        'no_noise': {'class_type': 'DisableNoise', 'inputs': {}},
        'sampler': {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': 'euler'}},
        'schedule': {'class_type': 'BasicScheduler', 'inputs': {'model': ['high_lightning', 0], 'scheduler': 'simple', 'steps': 8, 'denoise': 1}},
        'sigmas': {'class_type': 'SplitSigmas', 'inputs': {'sigmas': ['schedule', 0], 'step': 4}},
    }
    for index, side in enumerate(('high', 'low')):
        value[side] = {'class_type': 'UnetLoaderGGUF', 'inputs': {'unet_name': FILES['diffusion_models'][index]}}
        value[side + '_shift'] = {'class_type': 'ModelSamplingSD3', 'inputs': {'model': [side, 0], 'shift': 6}}
        value[side + '_svi'] = {'class_type': 'LoraLoaderModelOnly', 'inputs': {
            'model': [side + '_shift', 0], 'lora_name': FILES['loras'][index], 'strength_model': 1}}
        value[side + '_lightning'] = {'class_type': 'LoraLoaderModelOnly', 'inputs': {
            'model': [side + '_svi', 0], 'lora_name': FILES['loras'][3] if index else LIGHTNING_HIGH, 'strength_model': 1}}
    for index, prompt in enumerate(parameters['segment_prompts']):
        part = f'part{index + 1}'
        value[part + '_text'] = {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['clip', 0], 'text': prompt}}
        value[part] = {'class_type': 'WanImageToVideoSVIPro', 'inputs': {
            'positive': [part + '_text', 0], 'negative': ['negative', 0], 'anchor_samples': ['anchor', 0],
            'length': 81, 'motion_latent_count': 0 if index == 0 else 1}}
        if index:
            value[part]['inputs']['prev_samples'] = [f'part{index}_low', 0]
        for side in ('high', 'low'):
            value[part + '_guide_' + side] = {'class_type': 'ScheduledCFGGuidance', 'inputs': {
                'model': [side + '_lightning', 0], 'positive': [part, 0], 'negative': [part, 1],
                'cfg': 1, 'start_percent': 0, 'end_percent': 1}}
            value[part + '_' + side] = {'class_type': 'SamplerCustomAdvanced', 'inputs': {
                'noise': ['noise' if side == 'high' else 'no_noise', 0], 'guider': [part + '_guide_' + side, 0],
                'sampler': ['sampler', 0], 'sigmas': ['sigmas', 0 if side == 'high' else 1],
                'latent_image': [part, 2] if side == 'high' else [part + '_high', 0]}}
        value[part + '_decode'] = {'class_type': 'VAEDecode', 'inputs': {'samples': [part + '_low', 0], 'vae': ['vae', 0]}}
        if index:
            value[part + '_merge'] = {'class_type': 'ImageBatchExtendWithOverlap', 'inputs': {
                'source_images': ['part1_decode', 0] if index == 1 else ['part2_merge', 2],
                'new_images': [part + '_decode', 0], 'overlap': 5, 'overlap_side': 'source', 'overlap_mode': 'linear_blend'}}
    value['video'] = {'class_type': 'CreateVideo', 'inputs': {'images': ['part3_merge', 2], 'fps': 16}}
    value['save'] = {'class_type': 'SaveVideo', 'inputs': {
        'video': ['video', 0], 'filename_prefix': 'qianmi_svi/clip', 'format': 'mp4', 'format.codec': 'h264',
        'format.codec.encoding': 're-encode', 'format.codec.encoding.crf': 18}}
    return value


def ensure_models():
    if not PYTHON.is_file() or not (COMFY / 'main.py').is_file():
        raise ComfyWorkflowError('請先安裝千迷 AI 的 ComfyUI Portable 執行環境。')
    for pack in ('ComfyUI-GGUF', 'ComfyUI-KJNodes'):
        if not (COMFY / 'custom_nodes' / pack / '__init__.py').is_file():
            raise ComfyWorkflowError('高耗能模式尚未安裝完成，請執行 python -m tools.install_svi。')
    for folder, names in FILES.items():
        for name in names:
            target = COMFY / 'models' / folder / name
            if target.is_file():
                continue
            source = MODELS / folder / name
            if not source.is_file():
                raise ComfyWorkflowError(f'高耗能模式缺少模型：{name}')
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(source, target)
    if not (COMFY / 'models' / 'loras' / LIGHTNING_HIGH).is_file():
        raise ComfyWorkflowError('Lightning LoRA 尚未轉換完成，請執行 python -m tools.install_svi。')


def stop_server(process):
    with task_scope(None):
        try:
            if process.poll() is None:
                request_json('/free', {'unload_models': True, 'free_memory': True}, timeout=5, url=URL)
        except (OSError, ValueError):
            LOG.warning('SVI cleanup API unavailable; releasing the owned process instead')
        finally:
            try:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    process.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    raise CancellationFailed('高耗能生成程序未確認退出，已停止佇列以避免記憶體持續佔用。') from None
            except OSError:
                raise CancellationFailed('無法確認高耗能生成程序已退出，已停止佇列。') from None


def run(parameters, seed, output, progress, source):
    ensure_models()
    try:
        queue = request_json('/queue', url='http://127.0.0.1:8188')
    except URLError as exc:
        if not isinstance(exc.reason, ConnectionRefusedError):
            raise ComfyWorkflowError('無法確認 Comfy Desktop 是否閒置，請確認服務狀態後再試。') from None
        queue = {}
    if queue.get('queue_running') or queue.get('queue_pending'):
        raise ComfyWorkflowError('Comfy Desktop 正在生成，請等候任務完成後再使用高耗能模式。')
    release_models()
    try:
        with socket.create_connection(('127.0.0.1', 8192), timeout=.5):
            raise ComfyWorkflowError('高耗能服務的 8192 連接埠已被占用，請先關閉占用服務。')
    except OSError:
        pass
    control = CURRENT.get()
    with image_input(source) as image:
        value = graph(parameters, seed, image)
        progress('正在準備高耗能模式，首次載入兩個主模型需要較長時間…')
        runtime = ROOT / '.runtime'
        runtime.mkdir(exist_ok=True)
        with (runtime / 'svi_comfy.log').open('ab') as log:
            process = subprocess.Popen([str(PYTHON), '-s', str(COMFY / 'main.py'), '--listen', '127.0.0.1',
                '--port', '8192', '--disable-auto-launch', '--lowvram', '--cache-none',
                '--output-directory', str(runtime / 'svi_output')], cwd=COMFY, stdout=log, stderr=log,
                creationflags=FLAGS)
        try:
            for _ in range(180):
                if control:
                    control.check()
                if process.poll() is not None:
                    raise ComfyWorkflowError('高耗能服務啟動失敗，請查看 .runtime/svi_comfy.log。')
                try:
                    nodes = request_json('/object_info', url=URL)
                    absent = {node['class_type'] for node in value.values()} - nodes.keys()
                    if absent:
                        raise ComfyWorkflowError('高耗能模式缺少節點：' + '、'.join(sorted(absent)))
                    break
                except OSError:
                    time.sleep(1)
            else:
                raise ComfyWorkflowError('高耗能服務啟動逾時，請查看 .runtime/svi_comfy.log。')
            progress('正在依序生成三段影片，請等候完成；可隨時強制終止。')
            results = execute_video(value, output, 'SVI 三段影片', url=URL, log_path='.runtime/svi_comfy.log')
            progress('影片已儲存，正在釋放模型與快取…', results)
            return results
        finally:
            stop_server(process)
            if control:
                control.prompt_id = None

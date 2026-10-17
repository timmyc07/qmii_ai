"""Run the author-recommended Qwen Image NSFW Adv LoKr group."""
import time
from urllib.parse import urlencode
from urllib.request import urlopen

from .superduper import COMFY, URL, ensure_server, image_input, request_json

FILES = (
    'models/diffusion_models/qwen_image_fp8_e4m3fn.safetensors',
    'models/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors',
    'models/vae/qwen_image_vae.safetensors',
    'models/loras/Qwen-Image-Lightning-8steps-V2.0-bf16.safetensors',
    'models/loras/qwen-image_nsfw_adv_v1.0.safetensors',
)


def ensure_comfy():
    missing = [path for path in FILES if not (COMFY / path).is_file()]
    if missing:
        raise RuntimeError('NSFW Adv 群組尚未安裝完成：' + '、'.join(missing))
    ensure_server({'UNETLoader', 'CLIPLoader', 'LoraLoaderModelOnly', 'KSampler', 'SaveImage'})
    sampler = request_json('/object_info/KSampler').get('KSampler', {}).get('input', {}).get('required', {})
    samplers = sampler.get('sampler_name', [[]])[0]
    schedulers = sampler.get('scheduler', [[]])[0]
    if 'res_2s' not in samplers or 'bong_tangent' not in schedulers:
        raise RuntimeError('NSFW Adv 群組缺少 RES4LYF 的 res_2s 或 bong_tangent。')


def graph(parameters, prompt, seed, image=None):
    value = {
        '1': {'class_type': 'UNETLoader', 'inputs': {
            'unet_name': 'qwen_image_fp8_e4m3fn.safetensors', 'weight_dtype': 'default'}},
        '2': {'class_type': 'LoraLoaderModelOnly', 'inputs': {
            'model': ['1', 0], 'lora_name': 'Qwen-Image-Lightning-8steps-V2.0-bf16.safetensors',
            'strength_model': parameters.get('lightning_strength', .45)}},
        '3': {'class_type': 'LoraLoaderModelOnly', 'inputs': {
            'model': ['2', 0], 'lora_name': 'qwen-image_nsfw_adv_v1.0.safetensors',
            'strength_model': parameters.get('lokr_strength', 1)}},
        '4': {'class_type': 'ModelSamplingAuraFlow', 'inputs': {'model': ['3', 0], 'shift': 3.1}},
        '5': {'class_type': 'CLIPLoader', 'inputs': {
            'clip_name': 'qwen_2.5_vl_7b_fp8_scaled.safetensors', 'type': 'qwen_image', 'device': 'default'}},
        '6': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['5', 0], 'text': prompt}},
        '7': {'class_type': 'CLIPTextEncode', 'inputs': {
            'clip': ['5', 0], 'text': parameters.get('negative', '')}},
        '8': {'class_type': 'EmptySD3LatentImage', 'inputs': {
            'width': parameters.get('width', 1024), 'height': parameters.get('height', 1536), 'batch_size': 1}},
        '9': {'class_type': 'KSampler', 'inputs': {
            'model': ['4', 0], 'positive': ['6', 0], 'negative': ['7', 0], 'latent_image': ['8', 0],
            'seed': seed, 'steps': parameters.get('steps', 10), 'cfg': parameters.get('cfg', 1),
            'sampler_name': 'res_2s', 'scheduler': 'bong_tangent', 'denoise': 1}},
        '10': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'qwen_image_vae.safetensors'}},
        '11': {'class_type': 'VAEDecode', 'inputs': {'samples': ['9', 0], 'vae': ['10', 0]}},
        '12': {'class_type': 'SaveImage', 'inputs': {
            'images': ['11', 0], 'filename_prefix': 'qianmi_nsfw_adv'}},
    }
    if image:
        value['13'] = {'class_type': 'LoadImage', 'inputs': {'image': image}}
        value['14'] = {'class_type': 'ImageScale', 'inputs': {
            'image': ['13', 0], 'upscale_method': 'lanczos', 'width': parameters.get('width', 1024),
            'height': parameters.get('height', 1536), 'crop': 'center'}}
        value['8'] = {'class_type': 'VAEEncode', 'inputs': {'pixels': ['14', 0], 'vae': ['10', 0]}}
        value['9']['inputs']['denoise'] = parameters.get('denoise', .6)
    return value


def run(parameters, prompt, seed, output, progress, source=None):
    progress('正在檢查模型與啟動 NSFW Adv 服務…')
    ensure_comfy()
    progress('正在載入 NSFW Adv 模型與生成圖片（LoKr + Lightning + RES4LYF）…')
    with image_input(source) as image:
        prompt_id = request_json('/prompt', {'prompt': graph(parameters, prompt, seed, image)}, 30)['prompt_id']
        for _ in range(7200):
            history = request_json(f'/history/{prompt_id}', timeout=30)
            if prompt_id in history:
                status = history[prompt_id].get('status', {})
                if status.get('status_str') == 'error':
                    raise RuntimeError('NSFW Adv 群組執行失敗，請查看 .runtime/superduper.log。')
                images = history[prompt_id].get('outputs', {}).get('12', {}).get('images', [])
                if images:
                    progress('圖片生成完成，正在下載並儲存作品…')
                    image = images[-1]
                    query = urlencode({key: image[key] for key in ('filename', 'subfolder', 'type')})
                    with urlopen(URL + '/view?' + query, timeout=120) as response:
                        output.write_bytes(response.read())
                    return
            time.sleep(1)
    raise RuntimeError('NSFW Adv 群組工作流逾時。')

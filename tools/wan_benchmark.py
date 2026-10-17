"""Experimental silent Wan 2.2 TI2V-5B path, kept out of UI until measured."""
import math

from mobile.parameters import Parameters
from mobile.superduper import COMFY, ComfyWorkflowError, ensure_server, image_input
from mobile.h3 import execute_video
from tools.install_wan import FILES


def frames(duration):
    return 1 + 4 * math.ceil((duration * 24 - 1) / 4)


def graph(parameters, prompt, seed, image=None):
    params = Parameters.model_validate(parameters).model_dump(exclude_none=True)
    if set(params) - {'width', 'height', 'duration', 'seed', 'steps', 'cfg', 'negative', 'video_crf'}:
        raise ValueError('Wan 基準僅支援尺寸、片長、種子、步數、CFG、負面提示詞與 CRF；不產生音訊或支援尾幀。')
    width, height = params.get('width', 896), params.get('height', 512)
    if max(width, height) > 1280 or min(width, height) > 704:
        raise ValueError('Wan 基準尺寸短邊最多 704、長邊最多 1280。')
    names = list(FILES)
    value = {
        'model': {'class_type': 'UNETLoader', 'inputs': {'unet_name': names[0].split('/')[-1], 'weight_dtype': 'default'}},
        'clip': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': names[1].split('/')[-1], 'type': 'wan', 'device': 'default'}},
        'vae': {'class_type': 'VAELoader', 'inputs': {'vae_name': names[2].split('/')[-1]}},
        'shift': {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['model', 0], 'shift': 8}},
        'positive': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['clip', 0], 'text': prompt}},
        'negative': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['clip', 0], 'text': params.get('negative', '')}},
        'latent': {'class_type': 'Wan22ImageToVideoLatent', 'inputs': {
            'vae': ['vae', 0], 'width': width, 'height': height, 'length': frames(params.get('duration', 5.875)), 'batch_size': 1}},
        'sample': {'class_type': 'KSampler', 'inputs': {
            'model': ['shift', 0], 'positive': ['positive', 0], 'negative': ['negative', 0], 'latent_image': ['latent', 0],
            'seed': seed, 'steps': params.get('steps', 20), 'cfg': params.get('cfg', 5),
            'sampler_name': 'uni_pc', 'scheduler': 'simple', 'denoise': 1}},
        'decode': {'class_type': 'VAEDecode', 'inputs': {'samples': ['sample', 0], 'vae': ['vae', 0]}},
        'video': {'class_type': 'CreateVideo', 'inputs': {
            'images': ['decode', 0], 'fps': 24, 'bit_depth': 8, 'color_space': 'sRGB', 'codec': 'none'}},
        'save': {'class_type': 'SaveVideo', 'inputs': {
            'video': ['video', 0], 'filename_prefix': 'qianmi_wan/clip', 'format': 'mp4', 'format.codec': 'h264',
            'format.codec.encoding': 're-encode', 'format.codec.encoding.crf': params.get('video_crf', 18)}},
    }
    if image:
        value['first'] = {'class_type': 'LoadImage', 'inputs': {'image': image}}
        value['latent']['inputs']['start_image'] = ['first', 0]
    return value


def run(parameters, prompt, seed, output, progress, source=None):
    missing = [name for name in FILES if not (COMFY / 'models' / name).is_file()]
    if missing:
        raise ComfyWorkflowError('Wan 缺少模型，請執行 python -m tools.install_wan：' + '、'.join(missing))
    with image_input(source) as image:
        value = graph(parameters, prompt, seed, image)
        ensure_server({node['class_type'] for node in value.values()})
        progress('正在生成 Wan 無聲影片…')
        return execute_video(value, output, 'Wan')

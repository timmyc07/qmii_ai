"""Wan 2.2 native 5B and the reviewed two-stage 14B image-to-video recipe."""
from pathlib import Path
import time

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .chroma_templates import TemplateDependencyError

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ('wan', 'wan_template')
HIGH = 'wan22EnhancedNSFWSVICamera_nsfwFASTMOVEV2Q8H.gguf'
LOW = 'Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf'


class VideoSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    width: int = Field(default=640, ge=256, le=832, multiple_of=32)
    height: int = Field(default=384, ge=256, le=832, multiple_of=32)
    frames: int = Field(default=49, ge=5, le=121)
    fps: int = Field(default=24, ge=8, le=32)
    steps: int = Field(default=20, ge=4, le=40)
    cfg: float = Field(default=5, ge=1, le=10, allow_inf_nan=False)
    negative: str = Field(default='blurry, low quality, distorted, static, subtitles', max_length=4000)

    @model_validator(mode='after')
    def check_budget(self):
        if self.frames % 4 != 1 or self.width * self.height > 480 * 832:
            raise ValueError('影片幀數需為 4n+1，解析度不可超過 832 × 480。')
        return self


def template_defaults():
    return VideoSettings(width=480, height=832, frames=113, fps=16, steps=6, cfg=1)


def validate_input(workflow, image_count):
    if workflow == 'wan' and image_count > 1:
        raise ValueError('Wan 2.2 最多接受 1 張起始圖片；無圖片時使用文字生成影片。')
    if workflow == 'wan_template' and image_count != 1:
        raise ValueError('Wan 2.2 雙模型範本需要 1 張起始圖片。')


def requirements(workflow):
    common = ['text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors']
    return common + (['diffusion_models/wan2.2_ti2v_5B_fp16.safetensors', 'vae/wan2.2_vae.safetensors']
                     if workflow == 'wan' else ['unet/' + HIGH, 'unet/' + LOW,
                                               'vae/wan_2.1_vae.safetensors', 'clip_vision/clip_vision_h.safetensors'])


def build_workflow(workflow, prompt, seed, name, images=(), settings=None, lora=None, strength=1):
    validate_input(workflow, len(images))
    cfg = VideoSettings.model_validate(settings or (template_defaults() if workflow == 'wan_template' else VideoSettings()))
    def node(kind, **inputs):
        return dict(class_type=kind, inputs=inputs)
    graph = {
        'clip': node('CLIPLoader', clip_name='umt5_xxl_fp8_e4m3fn_scaled.safetensors', type='wan', device='cpu'),
        'positive': node('CLIPTextEncode', clip=['clip', 0], text=prompt),
        'negative': node('CLIPTextEncode', clip=['clip', 0], text=cfg.negative),
        'vae': node('VAELoader', vae_name='wan2.2_vae.safetensors' if workflow == 'wan' else 'wan_2.1_vae.safetensors'),
        'decode': node('VAEDecodeTiled', samples=['sample', 0], vae=['vae', 0], tile_size=256,
                       overlap=64, temporal_size=16, temporal_overlap=4),
        'video': node('CreateVideo', images=['decode', 0], fps=cfg.fps),
        'save': node('SaveVideo', video=['video', 0], filename_prefix=name, format='mp4',
                     **{'format.codec': 'h264', 'format.codec.encoding': 'auto'}),
    }
    if images:
        graph['image'] = node('LoadImage', image=images[0])
    if workflow == 'wan':
        if lora:
            raise ValueError('14B LoRA 不適用於 Wan 2.2 5B。')
        graph['model'] = node('UNETLoader', unet_name='wan2.2_ti2v_5B_fp16.safetensors', weight_dtype='default')
        graph['sampling'] = node('ModelSamplingSD3', model=['model', 0], shift=8)
        graph['latent'] = node('Wan22ImageToVideoLatent', vae=['vae', 0], width=cfg.width, height=cfg.height,
                               length=cfg.frames, batch_size=1, **({'start_image': ['image', 0]} if images else {}))
        graph['sample'] = node('KSampler', model=['sampling', 0], positive=['positive', 0], negative=['negative', 0],
                               latent_image=['latent', 0], seed=seed, steps=cfg.steps, cfg=cfg.cfg,
                               sampler_name='uni_pc', scheduler='simple', denoise=1)
    else:
        graph['high'] = node('UnetLoaderGGUF', unet_name=HIGH)
        graph['low'] = node('UnetLoaderGGUF', unet_name=LOW)
        if lora:
            graph['lora'] = node('LoraLoaderModelOnly', model=['high', 0], lora_name=lora, strength_model=strength)
        graph['sampling'] = node('ModelSamplingSD3', model=['lora' if lora else 'high', 0], shift=8)
        graph['sampling_low'] = node('ModelSamplingSD3', model=['low', 0], shift=8)
        graph['vision'] = node('CLIPVisionLoader', clip_name='clip_vision_h.safetensors')
        graph['vision_encode'] = node('CLIPVisionEncode', clip_vision=['vision', 0], image=['image', 0], crop='none')
        graph['scale'] = node('ImageScale', image=['image', 0], upscale_method='nearest-exact',
                              width=cfg.width, height=cfg.height, crop='center')
        graph['latent'] = node('WanImageToVideo', positive=['positive', 0], negative=['negative', 0],
                               vae=['vae', 0], clip_vision_output=['vision_encode', 0], start_image=['scale', 0],
                               width=cfg.width, height=cfg.height, length=cfg.frames, batch_size=1)
        sample = dict(positive=['latent', 0], negative=['latent', 1], steps=cfg.steps, cfg=cfg.cfg,
                      sampler_name='euler', scheduler='simple', noise_seed=seed)
        split = cfg.steps // 2
        graph['sample_high'] = node('KSamplerAdvanced', **sample, model=['sampling', 0], latent_image=['latent', 2],
                                    add_noise='enable', start_at_step=0, end_at_step=split, return_with_leftover_noise='enable')
        graph['sample'] = node('KSamplerAdvanced', **sample, model=['sampling_low', 0], latent_image=['sample_high', 0],
                               add_noise='disable', start_at_step=split, end_at_step=cfg.steps, return_with_leftover_noise='disable')
    return graph


def status(workflow, model_root, node_info=None):
    missing = [name for name in requirements(workflow) if not (model_root / name).is_file() or not (model_root / name).stat().st_size]
    graph = build_workflow(workflow, '', 0, 'check', ['check.png'] if workflow == 'wan_template' else [])
    classes = {node['class_type'] for node in graph.values()}
    missing_nodes = sorted(classes - node_info.keys()) if node_info is not None else []
    missing_choices = []
    if node_info is not None:
        for node in graph.values():
            schema = node_info.get(node['class_type'], {}).get('input', {}).get('required', {})
            for key in ('unet_name', 'clip_name', 'vae_name'):
                choices = schema.get(key, [None])[0]
                if key in node['inputs'] and isinstance(choices, list) and node['inputs'][key] not in choices:
                    missing_choices.append(node['inputs'][key])
    return dict(available=not missing and not missing_nodes and not missing_choices,
                missingModels=missing, missingNodes=missing_nodes + ['ComfyUI 尚未載入模型：' + name for name in missing_choices])


def validate_dependencies(workflow, model_root, node_info):
    value = status(workflow, model_root, node_info)
    if not value['available']:
        raise TemplateDependencyError('Wan 2.2 缺少依賴：' + '、'.join(value['missingModels'] + value['missingNodes']))


def wait_video(prompt_id, comfy_json, timeout=7200):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            entry = comfy_json('/history/' + prompt_id).get(prompt_id)
        except OSError:
            time.sleep(2)
            continue
        if entry:
            status = entry.get('status', {})
            if status.get('status_str') == 'error':
                raise RuntimeError('Wan 2.2 影片生成失敗，請查看 ComfyUI 日誌。')
            # Read only our SaveVideo output, never a preview or last-frame image.
            for item in entry.get('outputs', {}).get('save', {}).get('images', []):
                if item.get('type') == 'output' and item.get('filename', '').lower().endswith('.mp4'):
                    return '/'.join(filter(None, [item.get('subfolder', ''), item['filename']]))
            if status.get('completed'):
                raise RuntimeError('Wan 2.2 未產生 MP4 影片。')
        time.sleep(2)
    raise TimeoutError('Wan 2.2 影片生成逾時。')

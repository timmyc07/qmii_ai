"""Validated image and H3 generation overrides."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


def recipe_defaults():
    return {'quick': dict(steps=8, cfg=1), 'reference': dict(steps=8, cfg=1),
            'superduper': dict(steps=40, cfg=2, lora_strength=.8),
            'nsfw_adv': dict(steps=10, cfg=1, lokr_strength=1, lightning_strength=.45)}


class Parameters(BaseModel):
    model_config = ConfigDict(extra='forbid')
    steps: int | None = Field(default=None, ge=4, le=60)
    cfg: float | None = Field(default=None, ge=1, le=15, allow_inf_nan=False)
    seed: int | None = Field(default=None, ge=0, le=9007199254740991)
    width: int | None = Field(default=None, ge=256, le=2048, multiple_of=32)
    height: int | None = Field(default=None, ge=256, le=2048, multiple_of=32)
    negative: str | None = Field(default=None, max_length=4000)
    lora_strength: float | None = Field(default=None, ge=0, le=2, allow_inf_nan=False)
    lokr_strength: float | None = Field(default=None, ge=0, le=2, allow_inf_nan=False)
    lightning_strength: float | None = Field(default=None, ge=0, le=2, allow_inf_nan=False)
    denoise: float | None = Field(default=None, ge=.05, le=1, allow_inf_nan=False)
    duration: float | None = Field(default=None, ge=1, le=15, allow_inf_nan=False)
    video_profile: Literal['turbo4', 'turbo8', 'base'] | None = None
    sampler: Literal['euler', 'res_multistep'] | None = None
    shift_video: float | None = Field(default=None, ge=.01, le=100, allow_inf_nan=False)
    shift_audio: float | None = Field(default=None, ge=.01, le=100, allow_inf_nan=False)
    resize_method: Literal['nearest-exact', 'bilinear', 'area', 'bicubic', 'lanczos'] | None = None
    crop: Literal['center', 'disabled'] | None = None
    video_audio: bool | None = Field(default=None, strict=True)
    video_crf: int | None = Field(default=None, ge=0, le=51)
    end_frame: Literal['none', 'first', 'custom'] | None = None
    identity_prompt: bool | None = Field(default=None, strict=True)
    refmod: bool | None = Field(default=None, strict=True)


def validate_parameters(value, workflow=None):
    result = Parameters.model_validate(value).model_dump(exclude_none=True)
    if workflow == 'h3_image':
        allowed = {'width', 'height', 'duration', 'seed', 'video_profile', 'steps', 'sampler',
                   'shift_video', 'shift_audio', 'lora_strength', 'resize_method', 'crop',
                   'video_audio', 'video_crf', 'end_frame', 'identity_prompt', 'refmod'}
        if set(result) - allowed:
            raise ValueError('H3 使用 CFG 蒸餾模型與完整去噪，請移除 CFG、負面提示詞與圖片重繪參數。')
        profile = result.get('video_profile', 'turbo4')
        expected_steps = {'turbo4': 4, 'turbo8': 8}.get(profile)
        if expected_steps is not None and result.get('steps', expected_steps) != expected_steps:
            raise ValueError('Turbo 步數必須與所選 4 步／8 步 LoRA 配對。')
        if profile == 'base' and (result.get('steps', 20) < 20 or 'lora_strength' in result):
            raise ValueError('原版 H3 至少使用 20 步，且不載入 Turbo LoRA。')
        width, height = result.get('width', 512), result.get('height', 896)
        if max(width, height) > 1344 or min(width, height) > 768:
            raise ValueError('H3 尺寸短邊最多 768、長邊最多 1344，且須為 32 的倍數。')
    elif 'refmod' in result:
        raise ValueError('RefMod 僅支援 MiniMax H3，無法套用到 Qwen 圖片模型。')
    elif set(result) & {'duration', 'video_profile', 'sampler', 'shift_video', 'shift_audio',
                        'resize_method', 'crop', 'video_audio', 'video_crf', 'end_frame', 'identity_prompt'}:
        raise ValueError('影片參數僅適用於圖片生影片模式。')
    return result


def validate_h3_sources(parameters, sources, last_image=None):
    if not 1 <= len(sources) <= 4:
        raise ValueError('圖片生影片需要 1 至 4 張首幀圖片，每張各自生成一支影片。')
    if parameters.get('end_frame') == 'custom':
        if not last_image:
            raise ValueError('自選尾幀時另需一張尾幀圖片。')
    elif last_image is not None:
        raise ValueError('只有自選尾幀模式可提供尾幀圖片。')

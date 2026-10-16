"""Validated Qwen Image Turbo generation overrides."""
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


def validate_parameters(value, workflow=None):
    result = Parameters.model_validate(value).model_dump(exclude_none=True)
    if workflow == 'h3_image':
        allowed = {'width', 'height', 'duration', 'seed'}
        if set(result) - allowed:
            raise ValueError('H3 使用固定 4 步 Turbo 配方，請移除圖片模式參數。')
        width, height = result.get('width', 512), result.get('height', 896)
        if max(width, height) > 1344 or min(width, height) > 768:
            raise ValueError('H3 尺寸短邊最多 768、長邊最多 1344，且須為 32 的倍數。')
    return result

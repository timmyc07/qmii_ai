"""Validated per-job overrides; only expose parameters wired to a recipe."""
from pydantic import BaseModel, ConfigDict, Field
from . import wan


def recipe_defaults():
    return {
        'quick': dict(steps=8, cfg=1), 'reference': dict(steps=8, cfg=1),
        'pose': dict(steps=50, cfg=2.5, width=1152, height=1728, negative=''),
        'pose_edit': dict(steps=20, cfg=3, denoise=1, negative=''),
        'flux': dict(steps=20, cfg=3.5, width=1024, height=1024),
        'chroma': dict(steps=26, cfg=3.8, width=1024, height=1024, negative='low quality, blurry, deformed, unfinished'),
        'chroma_hades': dict(steps=10, cfg=4, detail_steps=30, detail_cfg=5, denoise=.5, bbox_dilation=15, sam_dilation=0, feather=5, noise_mask_feather=20),
        'chroma_full': {}, 'wan': wan.VideoSettings().model_dump(), 'wan_template': wan.template_defaults().model_dump(),
    }


class Parameters(BaseModel):
    model_config = ConfigDict(extra='forbid')
    steps: int | None = Field(default=None, ge=4, le=60)
    cfg: float | None = Field(default=None, ge=1, le=15, allow_inf_nan=False)
    denoise: float | None = Field(default=None, ge=.05, le=1, allow_inf_nan=False)
    seed: int | None = Field(default=None, ge=0, le=9007199254740991)
    width: int | None = Field(default=None, ge=256, le=1728, multiple_of=32)
    height: int | None = Field(default=None, ge=256, le=1728, multiple_of=32)
    frames: int | None = Field(default=None, ge=5, le=121)
    fps: int | None = Field(default=None, ge=8, le=32)
    negative: str | None = Field(default=None, max_length=4000)
    detail_steps: int | None = Field(default=None, ge=4, le=60)
    detail_cfg: float | None = Field(default=None, ge=1, le=15, allow_inf_nan=False)
    bbox_dilation: int | None = Field(default=None, ge=0, le=64)
    sam_dilation: int | None = Field(default=None, ge=0, le=64)
    feather: int | None = Field(default=None, ge=0, le=64)
    noise_mask_feather: int | None = Field(default=None, ge=0, le=64)


def validate_parameters(workflow, has_images, value):
    value = Parameters.model_validate(value).model_dump(exclude_none=True)
    allowed = {'seed'}
    if workflow in ('quick', 'reference', 'pose', 'chroma', 'flux', *wan.WORKFLOWS):
        allowed.update(('steps', 'cfg'))
    if workflow in ('chroma', 'flux') or workflow == 'pose' and not has_images or workflow in wan.WORKFLOWS:
        allowed.update(('width', 'height'))
    if workflow == 'pose':
        allowed.add('negative')
        if has_images:
            allowed.add('denoise')
    if workflow == 'chroma_hades':
        allowed.update(('steps', 'cfg', 'denoise', 'detail_steps', 'detail_cfg', 'bbox_dilation', 'sam_dilation', 'feather', 'noise_mask_feather'))
    if workflow == 'chroma' or workflow in wan.WORKFLOWS:
        allowed.add('negative')
    if workflow in wan.WORKFLOWS:
        allowed.update(('frames', 'fps'))
        defaults = wan.template_defaults() if workflow == 'wan_template' else wan.VideoSettings()
        wan.VideoSettings.model_validate({**defaults.model_dump(), **{k: v for k, v in value.items() if k != 'seed'}})
    if value.keys() - allowed:
        raise ValueError('目前工作流不支援這些參數：' + '、'.join(sorted(value.keys() - allowed)))
    return value

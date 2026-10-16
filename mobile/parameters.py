"""Validated Qwen Image Turbo generation overrides."""
from pydantic import BaseModel, ConfigDict, Field


def recipe_defaults():
    return {'quick': dict(steps=8, cfg=1), 'reference': dict(steps=8, cfg=1)}


class Parameters(BaseModel):
    model_config = ConfigDict(extra='forbid')
    steps: int | None = Field(default=None, ge=4, le=60)
    cfg: float | None = Field(default=None, ge=1, le=15, allow_inf_nan=False)
    seed: int | None = Field(default=None, ge=0, le=9007199254740991)
    width: int | None = Field(default=None, ge=256, le=2048, multiple_of=32)
    height: int | None = Field(default=None, ge=256, le=2048, multiple_of=32)
    negative: str | None = Field(default=None, max_length=4000)


def validate_parameters(value):
    return Parameters.model_validate(value).model_dump(exclude_none=True)

"""Reusable generation parameters, without temporary attachments or credentials."""
import json
from pathlib import Path
import secrets

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .gpu import gpu_lock
from .parameters import Parameters, validate_parameters
from .maintenance import LABELS


class RecipeInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    workflow: str
    prompt: str = Field(min_length=1, max_length=8000)
    parameters: Parameters = Field(default_factory=Parameters)
    precise_mode: bool = False

    @model_validator(mode='after')
    def validate_recipe(self):
        if self.workflow not in LABELS or not self.name.strip() or not self.prompt.strip():
            raise ValueError('請填寫配方名稱、提示詞與有效模式。')
        validate_parameters(self.parameters.model_dump(exclude_none=True), self.workflow)
        if self.workflow == 'svi_image' and (not self.parameters.segment_prompts or self.precise_mode):
            raise ValueError('SVI 配方需要三段提示詞，不使用精準模式。')
        return self


class Recipes:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        return json.loads(self.path.read_text(encoding='utf-8')) if self.path.is_file() else []

    def change(self, recipe=None, recipe_id=None):
        with gpu_lock(path=self.path.with_suffix('.lock'), timeout=10):
            items = self.read()
            if recipe is not None:
                if len(items) >= 100:
                    raise ValueError('最多儲存 100 份配方，請先刪除不使用的配方。')
                items.append(dict(id=secrets.token_hex(16), **recipe.model_dump(exclude_none=True)))
            else:
                items = [item for item in items if item['id'] != recipe_id]
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self.path)
            return dict(recipes=items)

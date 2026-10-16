"""Host settings shared by the desktop bridge and authenticated studio API."""
import hashlib
import json
from pathlib import Path
import secrets

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .gpu import gpu_lock
from .parameters import Parameters, validate_parameters

ROOT = Path(__file__).resolve().parents[1]


class Preset(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=100)
    prompt: str = Field(max_length=8000)


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    presets: list[Preset] = Field(default_factory=list, max_length=100)
    preciseMode: bool = False
    generation: dict[str, Parameters] = Field(default_factory=dict, max_length=10)
    revision: str = ''

    @model_validator(mode='after')
    def validate_generation(self):
        for key, value in self.generation.items():
            if key not in ('quick', 'reference', 'superduper', 'nsfw_adv'):
                raise ValueError('不支援的參數模式。')
            validate_parameters(value.model_dump(exclude_none=True))
        return self


class SettingsStore:
    def __init__(self, path=None):
        self.path = Path(path or ROOT / 'output' / 'qianmi_settings.json')

    def _read(self):
        if self.path.exists():
            data = self.path.read_bytes()
            value = json.loads(data)
        else:
            data = b''
            presets = self.path.parent / 'prompt_templates.json'
            value = dict(presets=json.loads(presets.read_text(encoding='utf-8')) if presets.exists() else [],
                         preciseMode=False)
            for preset in value['presets']:
                preset.setdefault('id', secrets.token_hex(16))
        value.pop('fixedPrompt', None)
        value['revision'] = hashlib.sha256(data).hexdigest()
        return Settings.model_validate(value).model_dump()

    def read(self):
        with gpu_lock(path=self.path.with_suffix('.lock'), timeout=10):
            return self._read()

    def save(self, value):
        value = Settings.model_validate(value).model_dump()
        if len({item['id'] for item in value['presets']}) != len(value['presets']):
            raise ValueError('按鈕識別碼不可重複。')
        with gpu_lock(path=self.path.with_suffix('.lock'), timeout=10):
            if value.pop('revision') != self._read()['revision']:
                raise ValueError('設定已由其他設備更新，請重新載入後再儲存。')
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self.path)
            return self._read()

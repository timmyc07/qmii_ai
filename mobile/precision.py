"""Rewrite image prompts with the user's Qwen Image 2.1 precision template."""
import json
from pathlib import Path
import time

from .superduper import COMFY, RUNTIME, ensure_server, request_json

TEMPLATE = RUNTIME / 'precision_prompt.md'
T2I_MODEL = 'qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors'
I2I_MODEL = 'qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors'


def _first_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            result = _first_text(item)
            if result:
                return result
    if isinstance(value, dict):
        for item in value.values():
            result = _first_text(item)
            if result:
                return result
    return ''


def _positive_prompt(text):
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        if text.strip():
            return text.strip()
        raise RuntimeError('精準模式沒有產生提示詞。')
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError('精準模式回傳格式錯誤。') from exc
    prompt = value.get('positive_prompt') or value.get('rewritten_prompt')
    if not isinstance(prompt, str) or not prompt.strip():
        raise RuntimeError('精準模式沒有產生提示詞。')
    return prompt.strip()


def rewrite(prompt, has_images, seed, progress):
    model = I2I_MODEL if has_images else T2I_MODEL
    missing = [path for path in (TEMPLATE, COMFY / 'models' / 'text_encoders' / model) if not path.is_file()]
    if missing:
        raise RuntimeError('精準模式尚未安裝完成：' + '、'.join(path.name for path in missing))
    ensure_server({'CLIPLoader', 'TextGenerate', 'PreviewAny'})
    progress('精準模式正在重寫提示詞…')
    system = TEMPLATE.read_text(encoding='utf-8')
    graph = {
        '1': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': model, 'type': 'stable_diffusion',
                                                    'device': 'default'}},
        '2': {'class_type': 'TextGenerate', 'inputs': {'clip': ['1', 0], 'prompt': prompt, 'max_length': 8192,
                                                       'mtp': 'auto', 'sampling_mode': 'on',
                                                       'sampling_mode.seed': seed, 'sampling_mode.temperature': .7,
                                                       'sampling_mode.min_p': .05, 'sampling_mode.top_k': 20,
                                                       'sampling_mode.top_p': .95,
                                                       'sampling_mode.presence_penalty': 1.5,
                                                       'sampling_mode.repetition_penalty': 1.05,
                                                       'thinking': False, 'use_default_template': True,
                                                       'system_prompt': system}},
        '3': {'class_type': 'PreviewAny', 'inputs': {'source': ['2', 0]}}
    }
    prompt_id = request_json('/prompt', {'prompt': graph}, 30)['prompt_id']
    for _ in range(1800):
        history = request_json(f'/history/{prompt_id}', timeout=30)
        if prompt_id in history:
            status = history[prompt_id].get('status', {})
            if status.get('status_str') == 'error':
                raise RuntimeError('精準模式執行失敗，請查看 .runtime/superduper.log。')
            output = history[prompt_id].get('outputs', {}).get('3')
            if output:
                rewritten = _positive_prompt(_first_text(output))
                request_json('/free', {'unload_models': True, 'free_memory': True})
                return rewritten
        time.sleep(1)
    raise RuntimeError('精準模式重寫提示詞逾時。')

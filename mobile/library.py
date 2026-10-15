"""Reviewed local asset catalog; clients submit IDs, never filesystem paths."""
import json
from pathlib import Path
from . import chroma_templates, flux, wan
from .parameters import recipe_defaults

ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = Path(r'D:\AI\ComfyUI-Models')
CATALOG = json.loads((ROOT / 'config' / 'creation_library.json').read_text(encoding='utf-8'))


def catalog(model_root=MODEL_ROOT):
    loras = []
    try:
        from .generation import comfy_json
        node_info = comfy_json('/object_info')
    except (OSError, ValueError):
        node_info = None
    checkpoint = model_root / 'checkpoints' / flux.MODEL
    flux_ready = checkpoint.is_file() and checkpoint.stat().st_size > 0
    for item in CATALOG['loras']:
        path = model_root / 'loras' / item['file']
        installed = path.is_file() and path.stat().st_size > 0
        dependency_ready = (flux_ready if item['workflow'] == 'flux' else
                            wan.status('wan_template', model_root, node_info)['available'] if item['workflow'] == 'wan_template' else True)
        loras.append(dict(item, installed=installed, available=installed and bool(item['modes']) and dependency_ready,
                          dependencyReady=dependency_ready))
    return dict(loras=loras, defaults=recipe_defaults(), templates=[dict(item, **(wan.status(item['id'], model_root, node_info) if item['id'] in wan.WORKFLOWS else chroma_templates.status(item['id'], model_root)))
                                       for item in CATALOG['templates']])


def resolve_lora(lora_id, workflow, has_images, strength=1.0, model_root=MODEL_ROOT):
    if not 0 <= strength <= 2:
        raise ValueError('LoRA 強度需介於 0 與 2。')
    if not lora_id:
        return None
    item = next((item for item in CATALOG['loras'] if item['id'] == lora_id), None)
    if not item or item['workflow'] != workflow or not item['modes']:
        raise ValueError('LoRA 與目前工作流不相容。')
    if ('edit' if has_images else 't2i') not in item['modes']:
        raise ValueError('此 LoRA 不支援圖片編輯，請先移除參考圖片。' if has_images else '此 LoRA 需要先上傳參考圖片。')
    if workflow == 'flux':
        flux.validate_models(model_root)
    path = model_root / 'loras' / item['file']
    if not path.is_file() or not path.stat().st_size:
        raise ValueError('LoRA 尚未匯入，請先執行 tools/import-library.ps1。')
    return item

"""Reviewed Chroma recipes with explicit input and dependency requirements."""
from copy import deepcopy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRAPHS = json.loads((ROOT / 'config' / 'chroma_workflows.json').read_text(encoding='utf-8'))
READY = ROOT / '.runtime' / 'chroma' / 'ready.json'
MODEL_INPUTS = {'UNETLoader': ('unet_name', 'diffusion_models'),
                'CLIPLoaderGGUF': ('clip_name', 'text_encoders'),
                'CLIPLoader': ('clip_name', 'text_encoders'),
                'VAELoader': ('vae_name', 'vae'),
                'LoraLoaderModelOnly': ('lora_name', 'loras'),
                'ControlNetLoader': ('control_net_name', 'controlnet'),
                'UpscaleModelLoader': ('model_name', 'upscale_models'),
                'SAMLoader': ('model_name', 'sams'),
                'UltralyticsDetectorProvider': ('model_name', 'ultralytics')}


class TemplateDependencyError(RuntimeError):
    """Bounded diagnostics from the reviewed recipe, never upstream prompts."""


def validate_input(workflow, image_count):
    if workflow == 'chroma_hades' and image_count:
        raise ValueError('chromaHDSimpleWorkflowMulti_v30.zip 使用文字生圖，請先移除參考圖片。')
    if workflow == 'chroma_full' and not 1 <= image_count <= 2:
        raise ValueError('comfyuiChroma1HdFull_v10.zip 需要 1 張姿態參考圖，可另外加入第 2 張色彩參考圖。')


def requirements(workflow):
    files = set()
    for node in GRAPHS[workflow].values():
        if node['class_type'] in MODEL_INPUTS:
            name, folder = MODEL_INPUTS[node['class_type']]
            files.add(folder + '/' + node['inputs'][name])
    if workflow == 'chroma_full':
        files.update('annotators/lllyasviel/Annotators/' + name for name in ['body_pose_model.pth', 'hand_pose_model.pth', 'facenet.pth'])
    return sorted(files)


def status(workflow, model_root, ready_path=READY):
    missing = [name for name in requirements(workflow)
               if not (model_root / name).is_file() or not (model_root / name).stat().st_size]
    try:
        classes = set(json.loads(ready_path.read_text(encoding='utf-8'))['classes'])
    except (OSError, ValueError, KeyError):
        classes = set()
    missing_nodes = sorted({node['class_type'] for node in GRAPHS[workflow].values()} - classes)
    return dict(available=not missing and not missing_nodes, missingModels=missing, missingNodes=missing_nodes)


def build_workflow(workflow, prompt, seed, name, images=()):
    validate_input(workflow, len(images))
    values = {'$prompt': prompt, '$seed': seed, '$name': name,
              '$pose': images[0] if images else '', '$color': images[-1] if images else ''}
    graph = deepcopy(GRAPHS[workflow])
    for node in graph.values():
        node['inputs'] = {key: values.get(value, value) if isinstance(value, str) else value
                          for key, value in node['inputs'].items()}
    return graph


def validate_dependencies(workflow, model_root, node_info):
    missing = [name for name in requirements(workflow)
               if not (model_root / name).is_file() or not (model_root / name).stat().st_size]
    if missing:
        raise TemplateDependencyError('範本缺少模型：' + '、'.join(missing))
    missing_nodes = {node['class_type'] for node in GRAPHS[workflow].values()} - node_info.keys()
    if missing_nodes:
        raise TemplateDependencyError('範本缺少節點，請完成安裝後重啟 ComfyUI：' + '、'.join(sorted(missing_nodes)))
    for node in GRAPHS[workflow].values():
        schema = node_info[node['class_type']]['input']
        missing_inputs = schema.get('required', {}).keys() - node['inputs'].keys()
        if missing_inputs:
            raise TemplateDependencyError('範本缺少節點輸入 ' + node['class_type'] + '：' + '、'.join(sorted(missing_inputs)))
        fields = {**schema.get('required', {}), **schema.get('optional', {})}
        for name, value in node['inputs'].items():
            if isinstance(value, list) and len(value) == 2 and name in fields:
                source = GRAPHS[workflow][value[0]]
                outputs = node_info[source['class_type']]['output']
                expected = fields[name][0]
                actual = outputs[value[1]] if 0 <= value[1] < len(outputs) else None
                if isinstance(expected, str) and expected != '*' and actual not in (expected, '*'):
                    raise TemplateDependencyError(f'範本連線類型不符 {node["class_type"]}／{name}：需要 {expected}，收到 {actual}。')
            if isinstance(value, str) and not value.startswith('$') and name in fields:
                choices = fields[name][0]
                if isinstance(choices, list) and value not in choices:
                    raise TemplateDependencyError(f'ComfyUI 不支援範本設定 {node["class_type"]}／{name}：{value}；請確認節點版本與模型路徑。')

"""Run the imported Qwen Image 2.1 SuperDuper workflow through dedicated ComfyUI."""
import json
from contextlib import contextmanager
import logging
import os
from pathlib import Path
import socket
import subprocess
from tempfile import TemporaryDirectory
import time
import uuid
from urllib.parse import urlencode
from urllib.error import URLError
from urllib.request import Request, urlopen
from .cancellation import CURRENT

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(r'D:\AI\QwenImage21SuperDuper')
PORTABLE = RUNTIME / 'ComfyUI_windows_portable'
COMFY = PORTABLE / 'ComfyUI'
PYTHON = PORTABLE / 'python_embeded' / 'python.exe'
WORKFLOW = RUNTIME / 'qwenImage21SuperDuper_v2.json'
URL = 'http://127.0.0.1:8191'
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
LOG = logging.getLogger('qianmi.mobile')


class ComfyWorkflowError(RuntimeError):
    """A prompt-free error safe to display in the shared job queue."""


def workflow_error(name, status, graph):
    for kind, value in status.get('messages', []):
        if kind == 'execution_error':
            node = graph.get(str(value.get('node_id')), {}).get('class_type', '未知節點')
            return ComfyWorkflowError(f'{name} 在 {node} 節點執行失敗，請查看電腦的 ComfyUI 日誌。')
    return ComfyWorkflowError(f'{name} 工作流執行失敗，請查看電腦的 ComfyUI 日誌。')
REQUIRED_NODES = {'APG', 'FreSca', 'FaceDetailer', 'UltralyticsDetectorProvider', 'TextEncodeQwenImage21',
                  'SplitImageWithAlpha'}
REQUIRED_FILES = (
    'models/diffusion_models/redqw21UNLOCKEDV2TI2I_redqw21UNLOCKEDV2_int8.safetensors',
    'models/text_encoders/qwen3vl_8b_int8_convrot.safetensors',
    'models/vae/qwen_image_2.1_vae_bf16.safetensors',
    'models/loras/pussyV2.safetensors',
    'models/loras/qwen2.1_penisV01_000004956_comfy.safetensors',
    'models/ultralytics/bbox/face_yolov8m.pt',
    'models/ultralytics/bbox/female-breast-v4.7.pt',
    'models/ultralytics/bbox/pussyV2.pt',
    'models/ultralytics/segm/cockAndBallDetection_v20.pt',
    'models/sams/sam_vit_b_01ec64.pth',
)
REMOVED = {55, 60, 81, 97, 98, 99, 100, 103, 104, 105, 111, 114, 117, 118, 119, 122, 126}
REWIRES = {
    (83, 'model'): ['80', 0],
    (82, 'clip'): ['83', 1],
    (106, 'model'): ['83', 0],
    (110, 'image'): ['8', 0],
    (123, 'clip'): ['83', 1],
    (121, 'model'): ['123', 0],
    (121, 'clip'): ['123', 1],
    (56, 'images'): ['121', 0],
}


def request_json(path, payload=None, timeout=10, *, url=URL):
    control = CURRENT.get()
    if control:
        control.check()
        if path == '/prompt':
            control.prompt_id = str(uuid.uuid4())
            control.comfy_url = url
            payload = {**payload, 'prompt_id': control.prompt_id}
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(url + path, data=data, headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=timeout) as response:
        content = response.read()
        result = json.loads(content) if content else {}
    if control:
        control.check()
    return result


def release_models():
    """Called under the shared GPU lock before switching to the CLI engine."""
    try:
        queue = request_json('/queue')
    except URLError as exc:
        if isinstance(exc.reason, ConnectionRefusedError):
            return
        raise ComfyWorkflowError('無法確認 ComfyUI 狀態，已停止模型切換。') from None
    if queue.get('queue_running') or queue.get('queue_pending'):
        raise ComfyWorkflowError('ComfyUI 仍有生成任務，請待完成後再切換快速生成。')
    request_json('/free', {'unload_models': True, 'free_memory': True})
    # /free schedules cleanup on ComfyUI's worker; HTTP 200 is not its completion.
    for _ in range(60):
        time.sleep(1)
        devices = request_json('/system_stats')['devices']
        if all(device['torch_vram_total'] - device['torch_vram_free'] <= 256 * 1024**2 for device in devices):
            return
    raise ComfyWorkflowError('ComfyUI 尚未釋放顯存，已停止模型切換，請查看主機日誌。')


def dependencies():
    missing = []
    if not PYTHON.is_file() or not (COMFY / 'main.py').is_file():
        missing.append('ComfyUI Portable')
    if not WORKFLOW.is_file():
        missing.append(WORKFLOW.name)
    missing.extend(path for path in REQUIRED_FILES if not (COMFY / path).is_file())
    return missing


def ensure_server(required_nodes=()):
    if not PYTHON.is_file() or not (COMFY / 'main.py').is_file():
        raise RuntimeError('ComfyUI Portable 尚未安裝完成。')
    try:
        nodes = request_json('/object_info')
        absent = set(required_nodes) - nodes.keys()
        if absent:
            raise ComfyWorkflowError('ComfyUI 缺少節點：' + '、'.join(sorted(absent)))
        return
    except OSError:
        pass
    try:
        with socket.create_connection(('127.0.0.1', 8191), timeout=.5):
            raise RuntimeError('8191 連接埠已被其他服務占用。')
    except OSError:
        pass
    output = ROOT / '.runtime' / 'superduper-output'
    output.mkdir(parents=True, exist_ok=True)
    log_path = ROOT / '.runtime' / 'superduper.log'
    with log_path.open('ab') as log:
        child = subprocess.Popen([str(PYTHON), '-s', str(COMFY / 'main.py'), '--listen', '127.0.0.1',
                                  '--port', '8191', '--disable-auto-launch', '--lowvram',
                                  '--output-directory', str(output)], cwd=COMFY, stdout=log, stderr=log,
                                 creationflags=FLAGS)
    LOG.info('Started SuperDuper ComfyUI pid=%s', child.pid)
    for _ in range(180):
        if child.poll() is not None:
            break
        try:
            nodes = request_json('/object_info')
            absent = set(required_nodes) - nodes.keys()
            if absent:
                raise ComfyWorkflowError('ComfyUI 缺少節點：' + '、'.join(sorted(absent)))
            return
        except OSError:
            time.sleep(1)
    raise RuntimeError('SuperDuper ComfyUI 啟動失敗，請查看 .runtime/superduper.log。')


def ensure_comfy():
    missing = dependencies()
    if missing:
        raise RuntimeError('SuperDuper 尚未安裝完成：' + '、'.join(missing))
    ensure_server(REQUIRED_NODES)


@contextmanager
def image_input(source):
    if source is None:
        yield None
        return
    from PIL import Image
    folder = COMFY / 'input'
    folder.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='qianmi_', dir=folder) as directory:
        target = Path(directory) / 'source.png'
        with Image.open(source) as image:
            image.convert('RGB').save(target)
        yield target.relative_to(folder).as_posix()


def compile_workflow(parameters, prompt, seed, image=None):
    workflow = json.loads(WORKFLOW.read_text(encoding='utf-8'))
    links = {link[0]: [str(link[1]), link[2]] for link in workflow['links']}
    graph = {}
    for node in workflow['nodes']:
        node_id = node['id']
        if node_id in REMOVED or node.get('mode', 0) != 0:
            continue
        inputs = dict(node.get('widgets_values_named') or {})
        for item in node.get('inputs', []):
            if item.get('link') is not None:
                inputs[item['name']] = links[item['link']]
        for (target, name), value in REWIRES.items():
            if target == node_id:
                inputs[name] = value
        graph[str(node_id)] = {'class_type': node['type'], 'inputs': inputs,
                               '_meta': {'title': node.get('title', node['type'])}}

    width, height = parameters.get('width', 1024), parameters.get('height', 1536)
    steps = parameters.get('steps', 40)
    split = max(1, min(steps - 1, round(steps * 23 / 40)))
    graph['62']['inputs'].update(width=width, height=height, batch_size=1)
    graph['82']['inputs']['prompt'] = prompt if 'STZK' in prompt else f'STZK, {prompt}'
    if 'negative' in parameters:
        graph['82']['inputs']['negative_prompt'] = parameters['negative']
    graph['90']['inputs']['seed'] = seed
    graph['88']['inputs'].update(steps=steps, end_at_step=split)
    graph['89']['inputs'].update(steps=steps, start_at_step=split, cfg=parameters.get('cfg', 2))
    strength = parameters.get('lora_strength', .8)
    graph['83']['inputs'].update(strength_model=strength, strength_clip=strength)
    graph['123']['inputs']['lora_name'] = 'qwen2.1_penisV01_000004956_comfy.safetensors'
    if image:
        graph['130'] = {'class_type': 'LoadImage', 'inputs': {'image': image}}
        graph['131'] = {'class_type': 'ImageScale', 'inputs': {
            'image': ['130', 0], 'upscale_method': 'lanczos', 'width': width, 'height': height, 'crop': 'center'}}
        graph['82']['inputs'].update({'images.image_1': ['131', 0], 'resolution': 0})
        graph['88']['inputs']['latent_image'] = ['82', 2]
        del graph['62']
    # Qwen 2.1 VAE returns RGBA; SAM and every subsequent detailer require RGB.
    for node_id, node in list(graph.items()):
        if node['class_type'] == 'FaceDetailer':
            rgb_id = f'rgb_{node_id}'
            graph[rgb_id] = {'class_type': 'SplitImageWithAlpha', 'inputs': {'image': node['inputs']['image']}}
            node['inputs']['image'] = [rgb_id, 0]
    graph['56']['inputs']['filename_prefix'] = 'qianmi_superduper'
    return graph


def run(parameters, prompt, seed, output, progress, source=None):
    ensure_comfy()
    progress('正在載入 SuperDuper 工作流與局部細修 LoRA…')
    with image_input(source) as image:
        graph = compile_workflow(parameters, prompt, seed, image)
        prompt_id = request_json('/prompt', {'prompt': graph}, 30)['prompt_id']
        for _ in range(7200):
            history = request_json(f'/history/{prompt_id}', timeout=30)
            if prompt_id in history:
                status = history[prompt_id].get('status', {})
                if status.get('status_str') == 'error':
                    raise workflow_error('SuperDuper', status, graph)
                images = history[prompt_id].get('outputs', {}).get('56', {}).get('images', [])
                if images:
                    image = images[-1]
                    query = urlencode({key: image[key] for key in ('filename', 'subfolder', 'type')})
                    with urlopen(URL + '/view?' + query, timeout=120) as response:
                        output.write_bytes(response.read())
                    return
            time.sleep(1)
    raise RuntimeError('SuperDuper 工作流逾時。')

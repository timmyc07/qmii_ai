"""Reuse the installed workflow and the desktop's existing Turbo recipe."""
import importlib.util
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time
import urllib.request

from .gpu import gpu_lock

LOG = logging.getLogger('qianmi.mobile')
ROOT = Path(__file__).resolve().parents[1]
POSE = ROOT / '.runtime' / 'qwen21-nsfw-pose-skill'
TURBO = Path(r'D:\AI\Qwen-Image-2.1-Turbo')
MODELS = Path(r'D:\AI\ComfyUI-Models')
COMFY = Path(os.environ['LOCALAPPDATA']) / 'Comfy-Desktop' / 'ComfyUI-Installs' / 'ComfyUI' / 'ComfyUI'
SHARED = Path(os.environ['LOCALAPPDATA']) / 'Comfy-Desktop' / 'ComfyUI-Shared'
COMFY_URL = 'http://127.0.0.1:8188'
LORA = 'qwen2_1-femaledVaginus-nsfw-v1_3-fine_L22-31.safetensors'
EDIT_LORA = 'qwen21-nsfw-image-edit.safetensors'
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def comfy_json(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(COMFY_URL + path, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=5) as response:
        content = response.read()
        return json.loads(content) if content else {}


def ensure_comfy():
    try:
        if 'system' in comfy_json('/system_stats'):
            return
    except OSError:
        pass
    try:
        with socket.create_connection(('127.0.0.1', 8188), timeout=.5):
            raise RuntimeError('8188 連接埠被非 ComfyUI 服務占用。')
    except OSError:
        pass
    python = COMFY / '.venv' / 'Scripts' / 'python.exe'
    if not python.is_file() or not (POSE / 'scripts' / 'qwen_pose_test.py').is_file():
        raise RuntimeError('請先完成 ComfyUI 與工作流安裝。')
    args = [str(python), str(COMFY / 'main.py'), '--listen', '127.0.0.1', '--port', '8188',
            '--disable-auto-launch', '--extra-model-paths-config', str(POSE / 'install' / 'windows_extra_model_paths.yaml'),
            '--input-directory', str(SHARED / 'input'), '--output-directory', str(SHARED / 'output')]
    with (ROOT / '.runtime' / 'mobile' / 'comfyui.log').open('ab') as log:
        child = subprocess.Popen(args, cwd=COMFY, stdout=log, stderr=log, creationflags=FLAGS)
    LOG.info('Started ComfyUI pid=%s', child.pid)
    for _ in range(120):
        try:
            if 'system' in comfy_json('/system_stats'):
                return
        except OSError:
            pass
        if child.poll() is not None:
            break
        time.sleep(1)
    raise RuntimeError('ComfyUI 啟動失敗，請在電腦查看啟動日誌。')


def pose_runner():
    os.environ['MEDIA_LOCK_FILE'] = str(POSE / '.media-task.lock')
    spec = importlib.util.spec_from_file_location('qianmi_pose_runtime', POSE / 'scripts' / 'qwen_pose_test.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_pose(runner, cfg):
    workflow, _ = runner.build_workflow(cfg['mode'], cfg)
    with runner.media_lock(exclusive=False, wait_timeout=1800):
        prompt_id = runner.queue_prompt(workflow)
        try:
            result = runner.wait_and_get_image(prompt_id)
            runner.download_view(result, Path(cfg['out']))
        except Exception:
            LOG.warning('Cancelling mobile ComfyUI prompt id=%s', prompt_id)
            # Only cancel this gateway's own job, never the user's other work.
            for _ in range(120):
                try:
                    runner._http_json('POST', COMFY_URL + '/queue', {'delete': [prompt_id]}, timeout=5)
                    runner._http_json('POST', COMFY_URL + '/interrupt', {'prompt_id': prompt_id}, timeout=5)
                    queued = runner._http_json('GET', COMFY_URL + '/queue', timeout=5)
                    if not any(item[1] == prompt_id for key in ('queue_running', 'queue_pending') for item in queued.get(key, [])):
                        break
                except OSError:
                    pass
                time.sleep(1)
            else:
                # Hold the workstation lock until the uncertain task has ended.
                while True:
                    try:
                        queued = runner._http_json('GET', COMFY_URL + '/queue', timeout=5)
                        if not any(item[1] == prompt_id for key in ('queue_running', 'queue_pending') for item in queued.get(key, [])):
                            break
                    except OSError:
                        pass
                    time.sleep(5)
            raise


def generate(payload, sources, output_dir, progress):
    results = []
    progress('等待電腦可用…')
    with gpu_lock():
        if payload['workflow'] == 'pose':
            progress('正在準備 Qwen 2.1 模型…')
            ensure_comfy()
            runner = pose_runner()
        else:
            # ComfyUI may retain most of the VRAM after its previous job.
            try:
                comfy_json('/free', {'unload_models': True, 'free_memory': True})
            except OSError:
                pass
        for index, source in enumerate(sources or [None]):
            progress(f'正在生成第 {index + 1}/{max(1, len(sources))} 張…')
            output = output_dir / f'{index}.png'
            seed = secrets.randbelow(2**63)
            if payload['workflow'] == 'pose':
                cfg = dict(mode='edit' if source else 't2i', name=f'mobile_{output_dir.name}_{index}',
                           prompt=payload['prompt'], negative='', out=str(output), seed=seed,
                           steps=20 if source else 50, cfg=3 if source else 2.5,
                           sampler='er_sde', scheduler='beta', denoise=1.0,
                           width=1152, height=1728, resolution=1024, lora_strength=1.0)
                if source:
                    cfg['image_name'] = runner.upload_image(source)
                    cfg['source'] = str(source)
                    if (MODELS / 'loras' / EDIT_LORA).is_file() and any(k in payload['prompt'].lower() for k in ['脫衣', '脱衣', '裸體', '裸体', '裸露', 'nude', 'undress', 'remove clothes', 'nsfw']):
                        cfg['lora'] = EDIT_LORA
                else:
                    cfg['lora'] = LORA
                run_pose(runner, cfg)
            else:
                run_turbo(payload['prompt'], source, output, seed)
            if not output.is_file() or not output.stat().st_size:
                raise RuntimeError('模型未產生圖片，請在電腦查看日誌。')
            # Do not ship embedded prompts/workflow metadata to the phone.
            from PIL import Image
            with Image.open(output) as image:
                clean = image.convert('RGB')
                clean.save(output, format='PNG')
            results.append(output.name)
            progress(f'已完成 {index + 1}/{max(1, len(sources))} 張', list(results))
    return results


def run_turbo(prompt, source, output, seed):
    models = TURBO / 'models'
    prompt_file = output.parent / '.prompt.txt'
    prompt_file.write_text(prompt, encoding='utf-8')
    args = [str(TURBO / 'sd-cli.exe'), '--diffusion-model', str(models / 'Qwen-Image-2.1-Turbo-AD-Q4_K.gguf'),
            '--llm', str(models / 'Qwen-Image-2.1-Turbo-Abliterated-Uncensored-AD-Q4_K.gguf'),
            '--vae', str(models / 'qwen_image_2.1_vae_bf16.safetensors'), '--prompt-file', str(prompt_file),
            '--steps', '8', '--cfg-scale', '1.0', '--sampling-method', 'euler',
            '--sigmas', '1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0',
            '-W', '1024', '-H', '1024', '--diffusion-fa', '-o', str(output), '--backend', 'cuda0',
            '--auto-fit', 'on', '--max-vram', 'cuda0=9', '--seed', str(seed)]
    if source:
        args += ['--llm_vision', str(models / 'mmproj-Qwen-Image-2.1-Turbo-Abliterated-Uncensored-BF16.gguf'),
                 '--ref-image-args', 'preset=qwen', '-r', str(source)]
    try:
        result = subprocess.run(args, cwd=TURBO, capture_output=True, timeout=1200, creationflags=FLAGS)
        if result.returncode:
            LOG.error('Turbo failed exit=%s', result.returncode)
            raise RuntimeError('快速生成失敗，請檢查電腦上的模型與顯示卡。')
    finally:
        prompt_file.unlink(missing_ok=True)

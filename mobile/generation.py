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
from . import chroma, chroma_templates, flux, wan
from .parameters import validate_parameters
from .library import resolve_lora

LOG = logging.getLogger('qianmi.mobile')
ROOT = Path(__file__).resolve().parents[1]
POSE = ROOT / '.runtime' / 'qwen21-nsfw-pose-skill'
TURBO = Path(r'D:\AI\Qwen-Image-2.1-Turbo')
MODELS = Path(r'D:\AI\ComfyUI-Models')
COMFY = Path(os.environ['LOCALAPPDATA']) / 'Comfy-Desktop' / 'ComfyUI-Installs' / 'ComfyUI' / 'ComfyUI'
SHARED = Path(os.environ['LOCALAPPDATA']) / 'Comfy-Desktop' / 'ComfyUI-Shared'
COMFY_URL = 'http://127.0.0.1:8188'
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
    paths = [str(ROOT / 'config' / 'windows_extra_model_paths.yaml')]
    templates = ROOT / '.runtime' / 'chroma' / 'extra_paths.yaml'
    if templates.is_file():
        paths.append(str(templates))
    args = [str(python), str(COMFY / 'main.py'), '--listen', '127.0.0.1', '--port', '8188',
            '--disable-auto-launch', '--extra-model-paths-config', *paths,
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
    run_comfy_workflow(runner, workflow, Path(cfg['out']))


def run_comfy_workflow(runner, workflow, output, result_reader=None):
    with runner.media_lock(exclusive=False, wait_timeout=1800):
        prompt_id = runner.queue_prompt(workflow)
        try:
            result = result_reader(prompt_id) if result_reader else runner.wait_and_get_image(prompt_id)
            runner.download_view(result, output)
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
    if payload['workflow'] not in ('quick', 'reference', 'pose', 'chroma', 'flux', *chroma_templates.GRAPHS, *wan.WORKFLOWS):
        raise RuntimeError('不支援的工作流。')
    if payload['workflow'] == 'flux' and sources:
        raise RuntimeError('FLUX.1-dev 僅支援文字生圖，請先移除參考圖片。')
    if payload['workflow'] == 'chroma' and sources:
        raise RuntimeError('Chroma1-HD 僅支援文字生圖，請先移除參考圖片。')
    chroma_templates.validate_input(payload['workflow'], len(sources))
    wan.validate_input(payload['workflow'], len(sources))
    params = validate_parameters(payload['workflow'], bool(sources), payload.get('parameters', {}))
    def new_seed(index=0):
        return (params['seed'] + index) % 9007199254740992 if 'seed' in params else secrets.randbelow(2**53)
    selected_lora = resolve_lora(payload.get('lora', ''), payload['workflow'], bool(sources),
                                 payload.get('lora_strength', 1.0), MODELS)
    results = []
    progress('等待電腦可用…')
    with gpu_lock():
        if payload['workflow'] in wan.WORKFLOWS:
            progress('正在準備 Wan 2.2 影片模型…')
            ensure_comfy()
            wan.validate_dependencies(payload['workflow'], MODELS, comfy_json('/object_info'))
            runner = pose_runner()
            images = [runner.upload_image(source) for source in sources]
            defaults = wan.template_defaults() if payload['workflow'] == 'wan_template' else wan.VideoSettings()
            video_settings = {**defaults.model_dump(), **{k: v for k, v in params.items() if k != 'seed'}}
            graph = wan.build_workflow(payload['workflow'], payload['prompt'], new_seed(), 'wan_' + output_dir.name,
                                       images, video_settings, selected_lora['file'] if selected_lora else None,
                                       payload.get('lora_strength', 1))
            progress('正在生成影片，這可能需要較長時間…')
            output = output_dir / '0.mp4'
            run_comfy_workflow(runner, graph, output, lambda pid: wan.wait_video(pid, comfy_json))
            if not output.is_file() or not output.stat().st_size:
                raise RuntimeError('Wan 2.2 未產生影片。')
            progress('影片生成完成', ['0.mp4'])
            return ['0.mp4']
        if payload['workflow'] in ('pose', 'chroma', 'flux', *chroma_templates.GRAPHS):
            progress('正在準備 FLUX.1-dev 模型…' if payload['workflow'] == 'flux' else '正在準備 Chroma1-HD 模型…' if payload['workflow'] == 'chroma' else '正在準備 Qwen 2.1 模型…')
            if payload['workflow'] == 'flux':
                flux.validate_models(MODELS)
            if payload['workflow'] == 'chroma':
                chroma.validate_models(MODELS)
            ensure_comfy()
            runner = pose_runner()
            if payload['workflow'] in chroma_templates.GRAPHS:
                chroma_templates.validate_dependencies(payload['workflow'], MODELS, comfy_json('/object_info'))
                runner.TIMEOUT = 7200
        else:
            # ComfyUI may retain most of the VRAM after its previous job.
            try:
                comfy_json('/free', {'unload_models': True, 'free_memory': True})
            except OSError:
                pass
        if payload['workflow'] in chroma_templates.GRAPHS:
            progress('正在執行 chromaHDSimpleWorkflowMulti_v30.zip 人臉修復與 2 倍放大…' if payload['workflow'] == 'chroma_hades'
                     else '正在執行 comfyuiChroma1HdFull_v10.zip 姿態參考與五階段放大，這可能需要較長時間…')
            images = [runner.upload_image(source) for source in sources]
            graph = chroma_templates.build_workflow(payload['workflow'], payload['prompt'],
                                                     new_seed(), 'template_' + output_dir.name, images)
            if payload['workflow'] == 'chroma_hades':
                for key in ('steps', 'cfg'):
                    if key in params:
                        graph['c142']['inputs'][key] = params[key]
                for key in ('denoise', 'bbox_dilation', 'sam_dilation', 'feather', 'noise_mask_feather', 'detail_steps', 'detail_cfg'):
                    if key in params:
                        graph['c146']['inputs'][key.removeprefix('detail_')] = params[key]
            output = output_dir / '0.png'
            run_comfy_workflow(runner, graph, output)
            if not output.is_file() or not output.stat().st_size:
                raise RuntimeError('範本未產生圖片，請查看 ComfyUI 日誌。')
            from PIL import Image
            with Image.open(output) as image:
                image.convert('RGB').save(output, format='PNG')
            progress('範本生成完成', ['0.png'])
            return ['0.png']
        if payload['workflow'] == 'reference':
            if len(sources) < 2:
                raise RuntimeError('多圖參考生成至少需要 2 張參考圖片。')
            progress(f'正在讀取提示詞並融合 {len(sources)} 張參考圖片…')
            output = output_dir / '0.png'
            reference_prompt = (
                f"請根據以下參考圖片重新創作一張全新的單一圖片。參考圖片依序標記為 "
                f"{'、'.join(f'<image{i}>' for i in range(1, len(sources) + 1))}。"
                "請依照使用者提示詞，參考圖片中的主體、風格、材質、色彩或構圖來重新生成；"
                f"不要把參考圖片直接拼貼、排列、重疊或顯示在輸出中。使用者提示詞：\n{payload['prompt']}"
            )
            run_turbo(reference_prompt, sources, output, new_seed(), **({'parameters': params} if params else {}))
            if not output.is_file() or not output.stat().st_size:
                raise RuntimeError('模型未產生圖片，請在電腦查看日誌。')
            from PIL import Image
            with Image.open(output) as image:
                image.convert('RGB').save(output, format='PNG')
            progress('多圖參考生成完成', ['0.png'])
            return ['0.png']
        for index, source in enumerate(sources or [None]):
            progress(f'正在生成第 {index + 1}/{max(1, len(sources))} 張…')
            output = output_dir / f'{index}.png'
            seed = new_seed(index)
            if payload['workflow'] == 'pose':
                cfg = dict(mode='edit' if source else 't2i', name=f'mobile_{output_dir.name}_{index}',
                           prompt=payload['prompt'], negative='', out=str(output), seed=seed,
                           steps=20 if source else 50, cfg=3 if source else 2.5,
                           sampler='er_sde', scheduler='beta', denoise=1.0,
                           width=1152, height=1728, resolution=1024,
                           lora_strength=payload.get('lora_strength', 1.0))
                if source:
                    cfg['image_name'] = runner.upload_image(source)
                    cfg['source'] = str(source)
                if selected_lora:
                    cfg['lora'] = selected_lora['file']
                cfg.update({key: value for key, value in params.items() if key != 'seed'})
                run_pose(runner, cfg)
            elif payload['workflow'] == 'flux':
                workflow = flux.build_workflow(payload['prompt'], seed, f'flux_{output_dir.name}_{index}',
                                               selected_lora['file'] if selected_lora else None,
                                               payload.get('lora_strength', 1.0))
                if 'steps' in params: workflow['7']['inputs']['steps'] = params['steps']
                if 'cfg' in params: workflow['3']['inputs']['guidance'] = params['cfg']
                for key in ('width', 'height'):
                    if key in params: workflow['13']['inputs'][key] = params[key]
                run_comfy_workflow(runner, workflow, output)
            elif payload['workflow'] == 'chroma':
                workflow = chroma.build_workflow(payload['prompt'], seed, f'chroma_{output_dir.name}_{index}')
                if 'steps' in params: workflow['13']['inputs']['steps'] = params['steps']
                if 'cfg' in params: workflow['10']['inputs']['cfg'] = params['cfg']
                if 'negative' in params: workflow['6']['inputs']['text'] = params['negative']
                for key in ('width', 'height'):
                    if key in params: workflow['7']['inputs'][key] = params[key]
                run_comfy_workflow(runner, workflow, output)
            else:
                run_turbo(payload['prompt'], [source] if source else [], output, seed, **({'parameters': params} if params else {}))
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


def run_turbo(prompt, sources, output, seed, parameters=None):
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
    params = parameters or {}
    for key, flag in [('steps', '--steps'), ('cfg', '--cfg-scale')]:
        if key in params:
            args[args.index(flag) + 1] = str(params[key])
    if 'steps' in params and params['steps'] != 8:
        index = args.index('--sigmas')
        del args[index:index + 2]
    if sources:
        args += ['--llm_vision', str(models / 'mmproj-Qwen-Image-2.1-Turbo-Abliterated-Uncensored-BF16.gguf'),
                 '--ref-image-args', 'preset=qwen']
        if len(sources) > 1:
            args += ['--increase-ref-index']
        for source in sources:
            args += ['-r', str(source)]
    try:
        result = subprocess.run(args, cwd=TURBO, capture_output=True, timeout=1200, creationflags=FLAGS)
        if result.returncode:
            LOG.error('Turbo failed exit=%s', result.returncode)
            raise RuntimeError('快速生成失敗，請檢查電腦上的模型與顯示卡。')
    finally:
        prompt_file.unlink(missing_ok=True)

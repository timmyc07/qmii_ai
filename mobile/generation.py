"""Run the local Qwen Image 2.1 Turbo recipe."""
import logging
import os
from pathlib import Path
import secrets
import subprocess

from .gpu import gpu_lock
from .cancellation import run_process, task_scope
from .parameters import validate_parameters, validate_h3_sources

LOG = logging.getLogger('qianmi.mobile')
TURBO = Path(r'D:\AI\Qwen-Image-2.1-Turbo')
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def generate(payload, sources, output_dir, progress):
    workflow = payload['workflow']
    if workflow not in ('quick', 'reference', 'superduper', 'nsfw_adv', 'h3_image'):
        raise RuntimeError('不支援的生成模式。')
    if workflow == 'reference' and len(sources) < 2:
        raise RuntimeError('多圖參考生成至少需要 2 張參考圖片。')
    params = validate_parameters(payload.get('parameters', {}), workflow)
    if workflow == 'h3_image':
        validate_h3_sources(params, sources, payload.get('last_image'))

    def new_seed(index=0):
        return (params['seed'] + index) % 9007199254740992 if 'seed' in params else secrets.randbelow(2**53)

    progress('等待電腦可用…')
    control = payload.get('_control')
    with gpu_lock(check=control.check if control else None), task_scope(control):
        prompt = payload['prompt']
        if workflow == 'h3_image':
            from .h3 import ComfyWorkflowError, run
            results = []
            for index, source in enumerate(sources):
                progress(f'正在生成第 {index + 1}/{len(sources)} 支影片…')
                try:
                    results.extend(run(params, prompt, new_seed(index), output_dir / f'{index}.mp4',
                                       lambda message: progress(f'第 {index + 1}/{len(sources)} 支：{message}'),
                                       source, payload.get('last_image')))
                except Exception as exc:
                    detail = str(exc) if isinstance(exc, ComfyWorkflowError) else '請確認電腦的模型服務與顯示卡狀態。'
                    raise ComfyWorkflowError(f'第 {index + 1}/{len(sources)} 支影片生成失敗，已保留 {len(results)} 支完成的影片。{detail}') from None
                progress(f'已完成 {len(results)}/{len(sources)} 支影片', list(results))
            return results
        if payload.get('precise_mode'):
            from .precision import apply_rules
            prompt = apply_rules(prompt, workflow, bool(sources))
        if workflow in ('superduper', 'nsfw_adv'):
            if workflow == 'superduper':
                from .superduper import run
            else:
                from .nsfw_adv import run
            results = []
            for index, source in enumerate(sources or [None]):
                progress(f'正在生成第 {index + 1}/{max(1, len(sources))} 張…')
                output = output_dir / f'{index}.png'
                run(params, prompt, new_seed(index), output, progress, source=source)
                clean_output(output)
                results.append(output.name)
                progress(f'已完成 {len(results)}/{max(1, len(sources))} 張', list(results))
            return results

        if workflow == 'reference':
            progress(f'正在融合 {len(sources)} 張參考圖片…')
            output = output_dir / '0.png'
            labels = '、'.join(f'<image{i}>' for i in range(1, len(sources) + 1))
            prompt = (f'請根據以下參考圖片重新創作一張全新的單一圖片。參考圖片依序標記為 {labels}。'
                      '請依照使用者提示詞，參考圖片中的主體、風格、材質、色彩或構圖來重新生成；'
                      f'不要把參考圖片直接拼貼、排列、重疊或顯示在輸出中。使用者提示詞：\n{prompt}')
            run_turbo(prompt, sources, output, new_seed(), params)
            clean_output(output)
            progress('多圖參考生成完成', ['0.png'])
            return ['0.png']

        results = []
        for index, source in enumerate(sources or [None]):
            progress(f'正在生成第 {index + 1}/{max(1, len(sources))} 張…')
            output = output_dir / f'{index}.png'
            run_turbo(prompt, [source] if source else [], output, new_seed(index), params)
            clean_output(output)
            results.append(output.name)
            progress(f'已完成 {index + 1}/{max(1, len(sources))} 張', list(results))
        return results


def clean_output(output):
    if not output.is_file() or not output.stat().st_size:
        raise RuntimeError('模型未產生圖片，請在電腦查看日誌。')
    from PIL import Image
    with Image.open(output) as image:
        image.convert('RGB').save(output, format='PNG')


def run_turbo(prompt, sources, output, seed, parameters=None):
    from .superduper import release_models
    release_models()
    models = TURBO / 'models'
    prompt_file = output.parent / '.prompt.txt'
    prompt_file.write_text(prompt, encoding='utf-8')
    negative_file = output.parent / '.negative.txt'
    args = [str(TURBO / 'sd-cli.exe'), '--diffusion-model', str(models / 'Qwen-Image-2.1-Turbo-AD-Q4_K.gguf'),
            '--llm', str(models / 'Qwen-Image-2.1-Turbo-Abliterated-Uncensored-AD-Q4_K.gguf'),
            '--vae', str(models / 'qwen_image_2.1_vae_bf16.safetensors'), '--prompt-file', str(prompt_file),
            '--steps', '8', '--cfg-scale', '1.0', '--sampling-method', 'euler',
            '--sigmas', '1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0',
            '-W', '1024', '-H', '1024', '--diffusion-fa', '-o', str(output), '--backend', 'cuda0',
            '--auto-fit', 'on', '--max-vram', 'cuda0=9', '--seed', str(seed)]
    params = parameters or {}
    for key, flag in [('steps', '--steps'), ('cfg', '--cfg-scale'), ('width', '-W'), ('height', '-H')]:
        if key in params:
            args[args.index(flag) + 1] = str(params[key])
    if params.get('negative'):
        negative_file.write_text(params['negative'], encoding='utf-8')
        args += ['--negative-prompt-file', str(negative_file)]
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
        result = run_process(args, cwd=TURBO, timeout=1200, creationflags=FLAGS)
        if result.returncode:
            LOG.error('Turbo failed exit=%s', result.returncode)
            raise RuntimeError('快速生成失敗，請檢查電腦上的模型與顯示卡。')
    finally:
        prompt_file.unlink(missing_ok=True)
        negative_file.unlink(missing_ok=True)

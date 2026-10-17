"""Reproducible local GPU benchmarks using the application's real runners.

Run with ComfyUI Portable Python (its existing aiohttp, psutil and av packages).
Reports and media stay under ignored output/; GPU generation requires --run.
"""
import argparse
import asyncio
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mobile import generation, h3, nsfw_adv, superduper
from mobile.gpu import gpu_lock
from mobile.settings import source_revision
from tools import wan_benchmark

ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=30, creationflags=generation.FLAGS)
    if result.returncode:
        raise RuntimeError(f'無法讀取版本：{Path(args[0]).name}')
    return result.stdout.strip() or result.stderr.strip()


def inventory():
    import psutil
    import torch
    files = []
    for folder in (generation.TURBO / 'models', superduper.COMFY / 'models'):
        for path in sorted(folder.rglob('*')):
            if path.is_file() and path.suffix in ('.gguf', '.safetensors', '.pt', '.pth'):
                files.append(dict(path=str(path), bytes=path.stat().st_size, mtime_ns=path.stat().st_mtime_ns))
    sources = [superduper.WORKFLOW, superduper.COMFY / 'comfyui_version.py',
               superduper.COMFY / 'comfy_extras' / 'nodes_minimax_h3.py',
               ROOT / 'docs' / 'benchmark_cases.json',
               Path(__file__), ROOT / 'tools' / 'wan_benchmark.py',
               superduper.COMFY / 'comfy_extras' / 'nodes_wan.py', generation.TURBO / 'sd-cli.exe']
    versions = {}
    for path in sources:
        if path.is_file():
            versions[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    memory = psutil.virtual_memory()
    return dict(recorded_at=datetime.now(timezone.utc).isoformat(), source_revision=source_revision(),
                git_head=command(['git', 'rev-parse', 'HEAD']),
                gpu=command(['nvidia-smi', '--query-gpu=name,driver_version,memory.total,memory.used', '--format=csv']),
                ram_total_bytes=memory.total, ram_available_bytes=memory.available,
                python=command([str(superduper.PYTHON), '--version']), torch=torch.__version__, cuda=torch.version.cuda,
                qwen_version=command([str(generation.TURBO / 'sd-cli.exe'), '--version']),
                source_sha256=versions, models=files,
                memory_policy='ComfyUI 原生 offload；不調整 pagefile、reserve-vram、cache 或 attention 套件')


def media_info(path):
    if path.suffix == '.png':
        from PIL import Image
        with Image.open(path) as image:
            image.load()
            return dict(file=path.name, width=image.width, height=image.height, bytes=path.stat().st_size)
    import av
    with av.open(str(path)) as video:
        stream = video.streams.video[0]
        count = 0
        picks = {}
        middle = stream.frames // 2
        for frame in video.decode(stream):
            if count in (0, middle):
                picks[count] = frame.to_image()
            last = frame.to_image()
            count += 1
        if not count:
            raise RuntimeError('影片沒有可解碼影格。')
        images = []
        for label, image in zip(('start', 'middle', 'end'), (picks[0], picks.get(middle, last), last)):
            target = path.with_name(f'{path.stem}_{label}.png')
            image.save(target)
            images.append(target.name)
        has_audio = bool(video.streams.audio)
        audio_samples = 0
        if has_audio:
            with av.open(str(path)) as audio:
                audio_samples = sum(frame.samples for frame in audio.decode(audio=0))
            if not audio_samples:
                raise RuntimeError('影片音軌沒有可解碼樣本。')
        return dict(file=path.name, width=stream.width, height=stream.height, frames=count,
                    fps=float(stream.average_rate), duration_seconds=float(stream.duration * stream.time_base),
                    audio=has_audio, audio_samples=audio_samples, bytes=path.stat().st_size, review_frames=images)


class NodeTimings:
    def __init__(self):
        self.current = None
        self.started = None
        self.seconds = {}
        self.cached = []

    def event(self, kind, data, now):
        if kind == 'execution_cached':
            self.cached.extend(data['nodes'])
        if kind in ('executing', 'execution_success', 'execution_error', 'execution_interrupted'):
            if self.current is not None:
                self.seconds[self.current] = self.seconds.get(self.current, 0) + now - self.started
            self.current = data.get('node') if kind == 'executing' else None
            self.started = now


async def measure(case, directory, suite, inventory_file):
    import aiohttp
    import psutil
    target = directory / case['id']
    target.mkdir(parents=True, exist_ok=True)
    save(target / 'case.json', case)
    sources = [(directory / name).resolve() for name in case['sources']]
    if any(not source.is_relative_to(directory.resolve()) or not source.is_file() for source in sources):
        raise ValueError('基準來源圖片缺少；請先執行 quick／quick_edit 案例。')
    result = dict(case=case['id'], workflow=case['workflow'], parameters=case['parameters'], success=False,
                  inventory_file=inventory_file, quality_review='待檢視輸出；不以任務成功當作品質合格', sample_interval_seconds=1)
    result['source_sha256'] = {name: hashlib.sha256(source.read_bytes()).hexdigest()
                               for name, source in zip(case['sources'], sources)}
    timings, graphs, histories, samples = NodeTimings(), [], [], []
    log_path = ROOT / '.runtime' / 'superduper.log'
    log_offset = log_path.stat().st_size if log_path.exists() else 0
    client_id = uuid.uuid4().hex
    original_request = superduper.request_json
    original_run = subprocess.run

    def request(path, payload=None, timeout=10):
        if path == '/prompt':
            queue = original_request('/queue')
            if queue.get('queue_running') or queue.get('queue_pending'):
                raise RuntimeError('ComfyUI 有其他工作，停止基準以免混入併發結果。')
            graphs.append(payload['prompt'])
            save(target / 'graph.json', payload['prompt'])
            payload = {**payload, 'client_id': client_id}
        value = original_request(path, payload, timeout)
        if path.startswith('/history/') and value:
            histories.append(value)
        return value

    def execute(args, *positional, **kwargs):
        value = original_run(args, *positional, **kwargs)
        if Path(args[0]).name == 'sd-cli.exe':
            log = (value.stdout or b'') + (value.stderr or b'')
            (target / 'qwen.log').write_bytes(log)
            text = log.decode('utf-8', errors='replace')
            result['qwen_reported_timings'] = [line for line in text.splitlines()
                                               if re.search(r'(load|generat|sampl|decod).*\d+(\.\d+)?\s*(s|ms)\b', line, re.I)]
        return value

    def run():
        with patch.object(generation, 'gpu_lock', return_value=nullcontext()), \
                patch.object(generation.subprocess, 'run', side_effect=execute), \
                patch.object(superduper, 'request_json', side_effect=request), \
                patch.object(h3, 'request_json', side_effect=request), \
                patch.object(nsfw_adv, 'request_json', side_effect=request):
            progress = lambda message, results=None: print(f'{case["id"]}: {message}', flush=True)
            if case['workflow'] == 'wan':
                return wan_benchmark.run(case['parameters'], case['prompt'], case['parameters']['seed'],
                                         target, progress, sources[0] if sources else None)
            return generation.generate(case, sources, target, progress)

    async def sample():
        while True:
            memory = psutil.virtual_memory()
            gpu = await asyncio.to_thread(command, ['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'])
            samples.append(dict(seconds=time.perf_counter() - started, vram_mib=float(gpu.splitlines()[0]),
                                ram_used_bytes=memory.total - memory.available, ram_available_bytes=memory.available))
            await asyncio.sleep(1)

    async def listen(ws):
        async for message in ws:
            if message.type == aiohttp.WSMsgType.TEXT:
                event = json.loads(message.data)
                data = event.get('data', {})
                if data.get('prompt_id'):
                    timings.event(event['type'], data, time.perf_counter())

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(superduper.URL.replace('http:', 'ws:') + '/ws?clientId=' + client_id) as ws:
            listener = asyncio.create_task(listen(ws))
            started = time.perf_counter()
            sampler = asyncio.create_task(sample())
            try:
                names = await asyncio.to_thread(run)
                result['generation_seconds'] = time.perf_counter() - started
                sampler.cancel()
                await asyncio.gather(sampler, return_exceptions=True)
                result['outputs'] = [await asyncio.to_thread(media_info, target / name) for name in names]
                result['success'] = True
            except Exception as exc:
                result.setdefault('generation_seconds', time.perf_counter() - started)
                result['error'] = str(exc)
            finally:
                sampler.cancel()
                listener.cancel()
                await asyncio.gather(sampler, listener, return_exceptions=True)
    result['node_seconds'] = {key: round(value, 3) for key, value in timings.seconds.items()}
    result['cached_nodes'] = timings.cached
    result['node_types'] = {key: node['class_type'] for graph in graphs for key, node in graph.items()}
    result['loader_node_seconds'] = sum(value for key, value in timings.seconds.items()
                                        if result['node_types'].get(key) in ('UNETLoader', 'CLIPLoader', 'VAELoader', 'LoraLoaderModelOnly'))
    result['sampler_node_seconds'] = sum(value for key, value in timings.seconds.items()
                                         if result['node_types'].get(key) in ('KSampler', 'KSamplerAdvanced', 'SamplerCustomAdvanced'))
    result['cached_sampling'] = any(result['node_types'].get(key) in ('KSampler', 'KSamplerAdvanced', 'SamplerCustomAdvanced')
                                     for key in timings.cached)
    result['measurement_valid'] = bool(samples) and not result['cached_sampling'] and (not graphs or bool(timings.seconds))
    if sampler.done() and not sampler.cancelled() and sampler.exception() is not None:
        result['measurement_valid'] = False
        result['measurement_error'] = str(sampler.exception())
    if listener.done() and not listener.cancelled():
        result['measurement_valid'] = False
        result['measurement_error'] = str(listener.exception()) if listener.exception() else 'ComfyUI 計時連線提前中斷。'
    result['peak_vram_mib'] = max((sample['vram_mib'] for sample in samples), default=None)
    result['peak_system_ram_used_bytes'] = max((sample['ram_used_bytes'] for sample in samples), default=None)
    result['minimum_system_ram_available_bytes'] = min((sample['ram_available_bytes'] for sample in samples), default=None)
    if log_path.exists() and case['workflow'] not in ('quick', 'reference'):
        with log_path.open('rb') as log:
            log.seek(log_offset)
            content = log.read()
        (target / 'comfy.log').write_bytes(content)
        result['memory_warnings'] = [line for line in content.decode('utf-8', errors='replace').splitlines()
                                      if re.search(r'out of memory|\bOOM\b|tiled.*decod', line, re.I)]
    save(target / 'samples.json', samples)
    save(target / 'history.json', histories)
    save(target / 'result.json', result)
    suite.append(result)
    save(directory / 'results.json', suite)
    write_table(directory, suite)
    print(f'{case["id"]}: success={result["success"]}, seconds={result["generation_seconds"]:.1f}', flush=True)
    return result['success'] and result['measurement_valid']


def write_table(directory, results):
    rows = ['# 本機生成基準', '', 'VRAM 與 RAM 為約每秒取樣的整機占用，包含桌面及其他程序，不是模型獨占或瞬時峰值。',
            '節點時間包含該節點內的延遲載入；採樣時間含 diffusion model 載入，不能宣稱為純推論時間。',
            '', '| 案例 | 成功 | 總秒數 | VRAM MiB | 整機 RAM GiB | 輸出／音訊 |', '| --- | --- | --- | --- | --- | --- |']
    for result in results:
        outputs = ', '.join(f'{item["width"]}×{item["height"]}' +
                            (f' / {item["duration_seconds"]:.3f}s / ' + ('有聲' if item['audio'] else '無聲')
                             if 'audio' in item else '') for item in result.get('outputs', []))
        ram = result.get('peak_system_ram_used_bytes')
        ram_text = f'{ram / 2**30:.2f}' if ram is not None else '未量測'
        vram = result.get('peak_vram_mib', '未量測')
        success = '快取，須重測' if result.get('cached_sampling') else str(result['success'])
        rows.append(f'| {result["case"]} | {success} | {result["generation_seconds"]:.2f} | '
                    f'{vram} | {ram_text} | {outputs} |')
    (directory / 'comparison.md').write_text('\n'.join(rows) + '\n', encoding='utf-8')


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='實際使用 GPU 執行案例；預設只盤點')
    parser.add_argument('--case', action='append', help='僅執行指定案例，可重複')
    parser.add_argument('--output', type=Path, default=ROOT / 'output' / 'benchmarks' / datetime.now().strftime('%Y%m%d_%H%M%S'))
    args = parser.parse_args()
    cases = json.loads((ROOT / 'docs' / 'benchmark_cases.json').read_text(encoding='utf-8'))['cases']
    if args.case:
        unknown = set(args.case) - {case['id'] for case in cases}
        if unknown:
            parser.error('未知案例：' + ', '.join(sorted(unknown)))
        cases = [case for case in cases if case['id'] in args.case]
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    # Hold the application's GPU lock across setup, every case and model switches.
    with gpu_lock():
        inventory_file = 'inventory_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json'
        save(directory / inventory_file, inventory())
        if not args.run:
            print(directory / inventory_file)
            return
        setup_started = time.perf_counter()
        superduper.ensure_server()
        save(directory / ('comfy_' + inventory_file), dict(setup_seconds=time.perf_counter() - setup_started,
                                                          stats=superduper.request_json('/system_stats')))
        results_path = directory / 'results.json'
        suite = json.loads(results_path.read_text(encoding='utf-8')) if results_path.exists() else []
        failed = False
        for case in cases:
            failed = not await measure(case, directory, suite, inventory_file) or failed
        if failed:
            raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())

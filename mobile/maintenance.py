"""Read-only workflow checks and explicitly previewed artwork cleanup."""
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import time

from pydantic import BaseModel, ConfigDict, Field

from .settings import ROOT

LABELS = dict(quick='快速生成', reference='多圖參考', superduper='SuperDuper',
              nsfw_adv='NSFW Adv', h3_image='H3 圖片生影片', svi_image='SVI 高耗能影片')


def workflow_check(workflow, parameters=None, has_images=True, info=None):
    from . import generation, superduper, nsfw_adv, h3, svi
    parameters = parameters or {}
    missing, nodes, graph = [], [], {}
    repair = 'powershell -ExecutionPolicy Bypass -File tools\\install-superduper.ps1'
    if workflow in ('quick', 'reference'):
        files = [generation.TURBO / 'sd-cli.exe'] + [generation.TURBO / 'models' / name for name in (
            'Qwen-Image-2.1-Turbo-AD-Q4_K.gguf',
            'Qwen-Image-2.1-Turbo-Abliterated-Uncensored-AD-Q4_K.gguf',
            'qwen_image_2.1_vae_bf16.safetensors')]
        if has_images:
            files.append(generation.TURBO / 'models/mmproj-Qwen-Image-2.1-Turbo-Abliterated-Uncensored-BF16.gguf')
        repair = '請依 docs/INSTALL.md 補齊 Qwen Turbo 執行環境與模型。'
    else:
        files = [superduper.PYTHON, superduper.COMFY / 'main.py']
        if workflow == 'superduper':
            files += [superduper.WORKFLOW, *[superduper.COMFY / name for name in superduper.REQUIRED_FILES]]
            if superduper.WORKFLOW.is_file():
                try:
                    graph = superduper.compile_workflow(parameters, '', 0, 'check.png' if has_images else None)
                except (OSError, ValueError, KeyError, TypeError):
                    missing.append('SuperDuper 工作流格式與目前配方不符')
        elif workflow == 'nsfw_adv':
            files += [superduper.COMFY / name for name in nsfw_adv.FILES]
            graph = nsfw_adv.graph(parameters, '', 0, 'check.png' if has_images else None)
        else:
            module = h3 if workflow == 'h3_image' else svi
            for folder, names in module.FILES.items():
                for name in names:
                    if workflow == 'h3_image' and folder == 'loras':
                        profile = parameters.get('video_profile', 'turbo4')
                        if profile == 'base' or name != names[0 if profile == 'turbo4' else 1]:
                            continue
                    target = superduper.COMFY / 'models' / folder / name
                    files.append(target if target.is_file() else module.MODELS / folder / name)
            if workflow == 'h3_image':
                graph = h3.graph(parameters, '', 0, 'check.png', 'last.png' if parameters.get('end_frame') == 'custom' else None)
                if parameters.get('refmod'):
                    files.append(superduper.COMFY / 'custom_nodes/ComfyUI-MiniMaxH3Mod/__init__.py')
                repair = '請依 docs/H3.md 補齊模型；RefMod：python -m tools.install_refmod'
            else:
                files.append(superduper.COMFY / 'models/loras' / svi.LIGHTNING_HIGH)
                files += [superduper.COMFY / 'models/loras' / parameters[key]['name']
                          for key in ('high_lora', 'low_lora') if parameters.get(key)]
                files += [superduper.COMFY / 'custom_nodes' / pack / '__init__.py'
                          for pack in ('ComfyUI-GGUF', 'ComfyUI-KJNodes')]
                graph = svi.graph({'segment_prompts': ['', '', ''], **parameters}, 0, 'check.png')
                repair = 'python -m tools.install_svi'
        if info is not None:
            nodes = sorted({node['class_type'] for node in graph.values()} - info.keys())
            for node in graph.values():
                required = info.get(node['class_type'], {}).get('input', {}).get('required', {})
                for key in ('unet_name', 'clip_name', 'vae_name', 'lora_name', 'sampler_name', 'scheduler'):
                    value = node['inputs'].get(key)
                    definition = required.get(key)
                    if not isinstance(value, str) or not definition:
                        continue
                    choices = definition[0]
                    if choices == 'COMBO' and len(definition) > 1:
                        choices = definition[1].get('options', [])
                    if isinstance(choices, list) and value not in choices:
                        # H3/SVI create model hard links when starting their runtime.
                        if workflow in ('h3_image', 'svi_image') and key in ('unet_name', 'clip_name', 'vae_name', 'lora_name'):
                            continue
                        missing.append(f'{node["class_type"]} 尚未辨識 {value}')
    missing += [str(path) for path in files if not path.is_file() or path.stat().st_size == 0]
    return dict(workflow=workflow, name=LABELS[workflow], ready=not missing and not nodes,
                missing=missing, missing_nodes=nodes, runtime_checked=info is not None,
                repair=repair)


def health():
    from .superduper import URL, request_json
    from .svi import URL as SVI_URL
    live, stats = {}, {}
    for key, url in (('comfy', URL), ('svi', SVI_URL)):
        try:
            live[key] = request_json('/object_info', timeout=2, url=url)
            stats[key] = request_json('/system_stats', timeout=2, url=url)
        except (OSError, ValueError, TimeoutError):
            live[key] = None
    return dict(workflows=[workflow_check(key, info=live['svi' if key == 'svi_image' else 'comfy']) for key in LABELS],
                runtimes=stats, note='未啟動的服務只檢查本機檔案；顯存與 RAM 顯示即時占用，不保證任意尺寸都可生成。')


def safe_file(path, root):
    root, path = Path(root).absolute(), Path(path).absolute()
    if not path.is_relative_to(root):
        return False
    for parent in (path, *path.parents):
        if parent.is_symlink() or parent.is_junction():
            return False
        if parent == root:
            return path.is_file()
    return False


def directory_size(root):
    if not Path(root).exists():
        return 0
    def scan_error(error):
        raise error
    total, seen = 0, set()
    for directory, folders, files in os.walk(root, followlinks=False, onerror=scan_error):
        folders[:] = [name for name in folders if not (Path(directory) / name).is_symlink()
                      and not (Path(directory) / name).is_junction()]
        for name in files:
            path = Path(directory) / name
            if safe_file(path, root):
                stat = path.stat()
                key = (stat.st_dev, stat.st_ino)
                if key not in seen:
                    total += stat.st_size
                    seen.add(key)
    return total


class CleanupInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    days: int = Field(default=30, ge=1, le=3650, strict=True)
    token: str = Field(default='', max_length=64)


class Maintenance:
    def __init__(self, store):
        self.store = store
        self.previews = {}

    def storage(self):
        from .generation import TURBO
        from .superduper import COMFY
        from .h3 import MODELS as H3_MODELS
        from .svi import MODELS as SVI_MODELS
        roots = [('作品與設定', self.store.output), ('上傳與生成暫存', self.store.state / 'uploads'),
                 ('未發布生成暫存', self.store.state / 'results'), ('Qwen 模型', TURBO / 'models'),
                 ('ComfyUI 模型', COMFY / 'models'), ('H3 模型來源', H3_MODELS), ('SVI 模型來源', SVI_MODELS)]
        items = []
        for name, path in roots:
            try:
                items.append(dict(name=name, bytes=directory_size(path), available=path.is_dir()))
            except OSError:
                items.append(dict(name=name, bytes=None, available=False))
        return dict(items=items, free_bytes=shutil.disk_usage(self.store.output).free,
                    note='同一分類內的硬連結不重複計算；分類之間可能共用模型。清理只處理已結束任務的過期作品。')

    def preview(self, days):
        cutoff = time.time() - days * 86400
        candidates = []
        with self.store.connect() as db:
            rows = db.execute("SELECT id,results FROM jobs WHERE status IN ('completed','failed','cancelled')").fetchall()
        for row in rows:
            for name in json.loads(row['results']):
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}/' + re.escape(row['id']) + r'_\d+\.(png|mp4)', name):
                    continue
                path = self.store.output / name
                if safe_file(path, self.store.output):
                    stat = path.stat()
                    if stat.st_mtime < cutoff:
                        candidates.append(dict(name=name, bytes=stat.st_size, modified=stat.st_mtime_ns,
                                               inode=stat.st_ino, job_id=row['id']))
        now = time.time()
        self.previews = {key: value for key, value in self.previews.items() if value[0] > now - 600}
        if len(self.previews) >= 16:
            self.previews.pop(next(iter(self.previews)))
        token = secrets.token_hex(24)
        self.previews[token] = (now, candidates)
        return dict(token=token, days=days, count=len(candidates), bytes=sum(item['bytes'] for item in candidates),
                    files=[item['name'] for item in candidates])

    def cleanup(self, token):
        preview = self.previews.pop(token, None)
        if preview is None or time.time() - preview[0] > 600:
            raise ValueError('清理預覽已過期，請重新預覽。')
        removed, failed = [], []
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for item in preview[1]:
                path = self.store.output / item['name']
                row = db.execute('SELECT status,results FROM jobs WHERE id=?', (item['job_id'],)).fetchone()
                if not row or row['status'] not in ('completed', 'failed', 'cancelled'):
                    continue
                if not safe_file(path, self.store.output):
                    continue
                stat = path.stat()
                if (stat.st_size, stat.st_mtime_ns, stat.st_ino) != (item['bytes'], item['modified'], item['inode']):
                    continue
                try:
                    path.unlink()
                except OSError:
                    failed.append(item['name'])
                    continue
                results = [name for name in json.loads(row['results']) if name != item['name']]
                db.execute('UPDATE jobs SET results=? WHERE id=?', (json.dumps(results), item['job_id']))
                removed.append(item)
        return dict(count=len(removed), bytes=sum(item['bytes'] for item in removed), failed=failed)

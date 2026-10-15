"""Install pinned public dependencies for the reviewed Chroma template graphs."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.runtime' / 'chroma'
MODELS = Path(r'D:\AI\ComfyUI-Models')
COMFY = Path(os.environ['LOCALAPPDATA']) / 'Comfy-Desktop' / 'ComfyUI-Installs' / 'ComfyUI' / 'ComfyUI'
MANIFEST = json.loads((ROOT / 'config' / 'chroma_dependencies.json').read_text(encoding='utf-8'))
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def run(args, cwd=ROOT):
    subprocess.run([str(arg) for arg in args], cwd=cwd, check=True, creationflags=FLAGS)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(item):
    path = MODELS / item['target']
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.stat().st_size == item['size'] and digest(path) == item['sha256']:
            print('Verified:', item['target'], flush=True)
            return
        raise RuntimeError(f'Existing file differs: {path}')
    partial = path.with_suffix(path.suffix + '.part')
    url = f"https://huggingface.co/{item['repo']}/resolve/main/{item['file']}"
    print('Downloading:', item['target'], flush=True)
    run(['curl.exe', '--fail', '--location', '--retry', '5', '--retry-delay', '3',
         '--continue-at', '-', '--silent', '--show-error', '--output', partial, url])
    if partial.stat().st_size != item['size'] or digest(partial) != item['sha256']:
        raise RuntimeError(f'Download verification failed: {item["target"]}')
    partial.replace(path)
    print('Installed:', item['target'], flush=True)


def install_nodes():
    node_root = STATE / 'nodes'
    node_root.mkdir(parents=True, exist_ok=True)
    for item in MANIFEST['nodes']:
        target = node_root / item['repo'].split('/')[-1]
        if not target.exists():
            run(['git', 'init', target])
            run(['git', 'remote', 'add', 'origin', 'https://github.com/' + item['repo']], target)
            run(['git', 'fetch', '--depth', '1', 'origin', item['commit']], target)
            run(['git', 'checkout', '--detach', 'FETCH_HEAD'], target)
        current = subprocess.check_output(['git', '-C', str(target), 'rev-parse', 'HEAD'], text=True).strip()
        if current != item['commit']:
            raise RuntimeError(f'Existing node checkout differs: {target}')
        run(['git', 'submodule', 'update', '--init', '--recursive', '--depth', '1'], target)
    python = COMFY / '.venv' / 'Scripts' / 'python.exe'
    # Keep the installed GPU stack and Qwen tokenizer unchanged. SAM2 and the
    # auxiliary preprocessors not used by these graphs are intentionally absent.
    code = 'import importlib.metadata as m; print(chr(10).join(n+"=="+m.version(n) for n in ["torch","torchvision","numpy","transformers","tokenizers","huggingface-hub"]))'
    constraints = STATE / 'constraints.txt'
    constraints.write_bytes(subprocess.check_output([str(python), '-c', code]))
    packages = ['gguf>=0.13.0', 'sentencepiece', 'protobuf', 'color-matcher', 'matplotlib', 'mss',
                'opencv-python-headless', 'pywavelets', 'segment-anything', 'scikit-image', 'piexif',
                'dill', 'ultralytics>=8.3.162', 'omegaconf', 'addict', 'yacs', 'trimesh', 'rtree',
                'scikit-learn', 'einops', 'ftfy', 'timm', 'iopath']
    run([python, '-m', 'pip', 'install', '--constraint', constraints, *packages])
    # ComfyUI discovers local custom nodes through the same extra-path mechanism
    # as models; no files in the user's ComfyUI checkout need to be modified.
    paths = 'qianmi_chroma_nodes:\n  base_path: ' + STATE.as_posix() + '\n  custom_nodes: nodes\n'
    (STATE / 'extra_paths.yaml').write_text(paths, encoding='utf-8')
    # Preprocessor weights are already downloaded and verified by --models.
    aux = node_root / 'comfyui_controlnet_aux'
    aux_config = dict(annotator_ckpts_path=(MODELS / 'annotators').as_posix(),
                      custom_temp_path=(STATE / 'temp').as_posix(),
                      USE_SYMLINKS=False, EP_list=['CPUExecutionProvider'])
    (aux / 'config.yaml').write_text(json.dumps(aux_config), encoding='utf-8')
    print('Node installation complete.', flush=True)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['nodes', 'models', 'verify', 'velvet'])
    parser.add_argument('--file', type=Path, help='Downloaded Velvet Chroma v2 FP16 model')
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    if args.action == 'nodes':
        install_nodes()
    elif args.action == 'models':
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(download, MANIFEST['models']))
    elif args.action == 'velvet':
        if not args.file or not args.file.is_file():
            parser.error('velvet requires --file pointing to the completed model download')
        item = MANIFEST['manual_models']['velvet']
        expected = item['sha256']
        if args.file.stat().st_size != item['size'] or digest(args.file) != expected:
            raise RuntimeError('File is not the verified Velvet Chroma v2.0 FP16 model.')
        target = MODELS / item['target']
        if target.exists():
            if digest(target) != expected:
                raise RuntimeError('Existing Velvet model differs; refusing to overwrite.')
        elif args.file.resolve() != target.resolve():
            partial = target.with_suffix('.safetensors.part')
            shutil.copyfile(args.file, partial)
            if digest(partial) != expected:
                raise RuntimeError('Velvet copy verification failed.')
            partial.replace(target)
        print('Verified and installed Velvet Chroma v2.0 FP16.', flush=True)
    else:
        sys.path.insert(0, str(ROOT))
        from mobile.generation import ensure_comfy, comfy_json
        from mobile.chroma_templates import GRAPHS, validate_dependencies
        ensure_comfy()
        info = comfy_json('/object_info')
        (STATE / 'ready.json').write_text(json.dumps(dict(classes=list(info))), encoding='utf-8')
        for workflow in GRAPHS:
            try:
                validate_dependencies(workflow, MODELS, info)
                print(workflow + ': ready', flush=True)
            except RuntimeError as exc:
                print(workflow + ': ' + str(exc), flush=True)


if __name__ == '__main__':
    main()

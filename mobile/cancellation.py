"""Cancel only the current job's CLI process or ComfyUI prompt."""
from contextlib import contextmanager
from contextvars import ContextVar
import subprocess
import threading
import time

CURRENT = ContextVar('qianmi_task_control', default=None)


class GenerationCancelled(RuntimeError):
    pass


class CancellationFailed(RuntimeError):
    pass


class TaskControl:
    def __init__(self):
        self.cancelled = threading.Event()
        self.prompt_id = None
        self.comfy_url = None

    def check(self):
        if self.cancelled.is_set():
            raise GenerationCancelled('任務已終止，已完成的輸出仍保留。')

    def finish(self):
        if not self.cancelled.is_set() or not self.prompt_id:
            return
        from .superduper import request_json
        endpoint = {'url': self.comfy_url} if self.comfy_url else {}
        try:
            request_json(f'/api/jobs/{self.prompt_id}/cancel', {}, timeout=5, **endpoint)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                queue = request_json('/queue', timeout=5, **endpoint)
                if not any(row[1] == self.prompt_id for row in queue.get('queue_running', []) + queue.get('queue_pending', [])):
                    return
                time.sleep(.25)
        except Exception:
            raise CancellationFailed('無法確認模型已停止，請檢查 ComfyUI 服務。') from None
        raise CancellationFailed('模型尚未確認停止，請查看主機日誌。')


@contextmanager
def task_scope(control):
    token = CURRENT.set(control)
    try:
        if control:
            control.check()
        yield
    finally:
        CURRENT.reset(token)
        if control:
            control.finish()


def run_process(args, cwd, timeout, creationflags):
    control = CURRENT.get()
    if control is None:
        return subprocess.run(args, cwd=cwd, capture_output=True, timeout=timeout, creationflags=creationflags)
    control.check()
    process = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags)
    deadline = time.monotonic() + timeout
    try:
        while True:
            control.check()
            try:
                stdout, stderr = process.communicate(timeout=.25)
                control.check()
                return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(args, timeout) from None
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()

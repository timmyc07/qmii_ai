"""Task-owned sampling telemetry; never forward engine logs or prompt text."""
import json
import math
import re
import threading
import time


class SamplingProgress:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = None
        self.connection_lost = False

    def reset(self):
        with self.lock:
            self.data = None
            self.connection_lost = False

    def update(self, node, step, total, seconds=None, label='本輪採樣'):
        if (type(step) not in (int, float) or type(total) not in (int, float)
                or not math.isfinite(step) or not math.isfinite(total)
                or int(step) != step or int(total) != total or not 0 <= step <= total <= 10000 or total == 0):
            return
        now = time.monotonic()
        with self.lock:
            previous = self.data
            same = previous and previous['node'] == node and previous['total'] == total and step >= previous['step']
            if same and step == previous['step']:
                return
            rate = None
            if same and previous['step'] > 0 and step > previous['step']:
                interval = (now - previous['updated']) / (step - previous['step'])
                if interval > 0:
                    rate = interval if previous['seconds_per_step'] is None else .3 * interval + .7 * previous['seconds_per_step']
            if type(seconds) in (int, float) and math.isfinite(seconds) and seconds > 0:
                rate = seconds
            self.connection_lost = False
            self.data = dict(node=node, step=int(step), total=int(total), label=label,
                             seconds_per_step=rate, updated=now, state='sampling' if step < total else 'complete')

    def idle(self):
        with self.lock:
            if self.data:
                self.data['state'] = 'complete' if self.data['step'] == self.data['total'] else 'paused'

    def disconnected(self):
        with self.lock:
            self.connection_lost = True
            if self.data:
                self.data['state'] = 'disconnected'

    def snapshot(self):
        with self.lock:
            if not self.data:
                return {'state': 'disconnected'} if self.connection_lost else None
            value = self.data.copy()
        value.pop('node')
        value['age_seconds'] = max(0, time.monotonic() - value.pop('updated'))
        rate = value['seconds_per_step']
        value['remaining_seconds'] = (value['total'] - value['step']) * rate if rate is not None else None
        return value


class ComfyProgress:
    def __init__(self, sampling, prompt_id, graph, url):
        import websocket
        self.websocket = websocket
        self.sampling, self.prompt_id, self.graph = sampling, prompt_id, graph
        self.url = url.replace('http:', 'ws:').replace('https:', 'wss:') + '/ws?clientId=' + prompt_id
        self.stop = threading.Event()
        self.ws = None
        sampling.reset()
        self.connect()
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def connect(self):
        try:
            self.ws = self.websocket.create_connection(self.url, timeout=3, http_no_proxy=['127.0.0.1', 'localhost'])
            self.ws.settimeout(.25)
        except (OSError, self.websocket.WebSocketException):
            self.ws = None
            self.sampling.disconnected()

    def event(self, message):
        data = message.get('data', {})
        if not isinstance(data, dict) or data.get('prompt_id') != self.prompt_id:
            return
        node = str(data.get('node'))
        if message.get('type') == 'executing':
            self.sampling.idle()
        elif message.get('type') == 'progress':
            kind = self.graph.get(node, {}).get('class_type', '').lower()
            if 'sampler' not in kind and 'detailer' not in kind:
                return
            part = re.fullmatch(r'part([1-3])_(high|low)', node)
            label = f'第 {part[1]}/3 段 · {"高噪" if part[2] == "high" else "低噪"}採樣' if part else '局部細修採樣' if 'detailer' in kind else '本輪採樣'
            self.sampling.update(node, data.get('value'), data.get('max'), label=label)

    def read(self):
        try:
            while not self.stop.is_set():
                if self.ws is None:
                    if self.stop.wait(1):
                        break
                    self.connect()
                    continue
                try:
                    message = self.ws.recv()
                    if message == '':
                        raise self.websocket.WebSocketConnectionClosedException()
                    if isinstance(message, str):
                        value = json.loads(message)
                        if isinstance(value, dict):
                            self.event(value)
                except self.websocket.WebSocketTimeoutException:
                    continue
                except (OSError, self.websocket.WebSocketException):
                    self.sampling.disconnected()
                    self.ws.close(timeout=.2)
                    self.ws = None
                except (ValueError, TypeError):
                    continue
        finally:
            if self.ws:
                self.ws.close(timeout=.2)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=4)


class CliProgress:
    def __init__(self, sampling):
        self.sampling, self.buffer = sampling, ''

    def feed(self, chunk):
        self.buffer += chunk.decode('utf-8', errors='replace')
        end = 0
        for match in re.finditer(r'(?:^|[\r\n])[ \t]*\|[=> ]+\|\s*(\d+)/(\d+)\s*-\s*(\d+(?:\.\d+)?)(s/it|it/s)\b', self.buffer):
            speed = float(match[3])
            self.sampling.update('cli', int(match[1]), int(match[2]),
                                 seconds=speed if match[4] == 's/it' else 1 / speed if speed > 0 else None)
            end = match.end()
        self.buffer = self.buffer[end:][-4096:]

"""Estimate all remaining work from complete, measured task profiles."""
from statistics import median
import threading
import time


class TaskTiming:
    def __init__(self, outputs=1, profiles=()):
        self.lock = threading.RLock()
        self.outputs = outputs
        self.engines = self.finished_outputs = 0
        self.engine_active = False
        self.reliable = True
        self.graph = {}
        self.done = {}
        self.speed_ratio = 1
        self.baseline = {}
        keys = {key for profile in profiles for key in profile}
        for key in keys:
            values = [profile[key] for profile in profiles if key in profile]
            rates = [value['rate'] for value in values if value.get('rate')]
            self.baseline[key] = dict(kind=values[0]['kind'], seconds=median(value['seconds'] for value in values),
                                      steps=median(value['steps'] for value in values), rate=median(rates) if rates else None)
        self.current = self.stage('prepare:0', 'prepare')

    @staticmethod
    def stage(key, kind):
        return dict(key=key, kind=kind, started=time.monotonic(), steps=0, completed=0, rate=None,
                    round_step=0, round_total=0, prior_steps=0)

    def advance(self, key, kind):
        if self.current and self.current['key'] == key:
            return
        if self.current:
            value = self.current
            self.done[value['key']] = dict(kind=value['kind'], seconds=max(0, time.monotonic() - value['started']),
                                           steps=value['steps'], rate=value['rate'])
        self.done.pop(key, None)
        self.current = self.stage(key, kind) if key else None

    def begin_engine(self, graph=None):
        with self.lock:
            self.prefix = str(self.engines)
            self.engines += 1
            self.engine_active = True
            self.graph = graph or {}
            self.advance(self.prefix + (':submit' if graph is not None else ':cli'), 'submit' if graph is not None else 'cli')

    def executing(self, node):
        with self.lock:
            if not self.engine_active:
                return
            if node is None:
                self.engine_finished()
            elif str(node) not in self.graph:
                self.reliable = False
            else:
                self.advance(f'{self.prefix}:node:{node}', self.graph.get(str(node), {}).get('class_type', 'node'))

    def cached(self, nodes):
        with self.lock:
            for node in nodes:
                if str(node) in self.graph:
                    self.done.setdefault(f'{self.prefix}:node:{node}',
                                         dict(kind=self.graph[str(node)]['class_type'], seconds=0, steps=0, rate=None))

    def sample(self, node, step, total, rate):
        with self.lock:
            if not self.engine_active or not self.current:
                return
            if self.graph and self.current['key'] != f'{self.prefix}:node:{node}':
                self.reliable = False
                self.executing(node)
            value = self.current
            if not value['round_total'] or step < value['round_step'] or total != value['round_total']:
                value['prior_steps'] += value['round_step']
                value['steps'] = value['prior_steps'] + total
            value.update(round_step=step, round_total=total, completed=value['prior_steps'] + step)
            if rate:
                value['rate'] = rate
                previous = self.baseline.get(value['key'], {})
                if previous.get('rate'):
                    self.speed_ratio = rate / previous['rate']
            if value['kind'] == 'cli' and step == total:
                self.advance(self.prefix + ':decode', 'decode')

    def engine_finished(self):
        with self.lock:
            if self.engine_active:
                self.engine_active = False
                self.advance(self.prefix + ':save', 'save')

    def output_finished(self, count):
        with self.lock:
            if count > self.finished_outputs:
                self.finished_outputs = count
                self.advance(f'prepare:{count}' if count < self.outputs else 'finish', 'prepare' if count < self.outputs else 'finish')

    def finish(self):
        with self.lock:
            self.advance(None, '')
            return dict(self.done) if self.reliable and self.engines == self.outputs and self.finished_outputs == self.outputs else {}

    def disconnected(self):
        with self.lock:
            self.reliable = False

    def remaining(self):
        with self.lock:
            if not self.reliable or not self.baseline or not self.current or self.current['key'] not in self.baseline:
                return None
            ratios = {}
            for key, actual in self.done.items():
                previous = self.baseline.get(key)
                if previous and previous['seconds'] > 0 and actual['seconds'] > 0 and not previous['steps'] and not actual['steps']:
                    ratios.setdefault(actual['kind'], []).append(actual['seconds'] / previous['seconds'])
            remaining = 0
            for key, previous in self.baseline.items():
                if key in self.done:
                    continue
                factor = median(ratios[previous['kind']]) if previous['kind'] in ratios else 1
                sampling = min(previous['seconds'], previous['steps'] * (previous['rate'] or 0))
                overhead = max(0, previous['seconds'] - sampling) * factor
                if key != self.current['key']:
                    remaining += overhead + sampling * self.speed_ratio
                    continue
                value = self.current
                elapsed = max(0, time.monotonic() - value['started'])
                rate = value['rate'] or (previous['rate'] or 0) * self.speed_ratio
                if rate:
                    work = max(previous['steps'], value['steps']) - value['completed']
                    spent_overhead = max(0, elapsed - value['completed'] * rate)
                    remaining += max(0, work) * rate + max(0, overhead - spent_overhead)
                else:
                    remaining += max(0, overhead - elapsed)
            return remaining

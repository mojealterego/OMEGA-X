"""Integrated deterministic simulator; all outputs are modeled quantities."""
from dataclasses import asdict
from .cache import CacheHierarchy
from .fabric import Fabric
from .model import Workload, Profile
from .scheduler import Scheduler
from .prefetch import MarkovPrefetcher
from collections import OrderedDict

class OmegaRuntime:
    def __init__(self, profile: Profile):
        self.profile = profile
        self.scheduler = Scheduler(profile)
        self.cache = CacheHierarchy(profile)
        self.fabric = Fabric(profile)
        self.prefetcher = MarkovPrefetcher()

    def run(self, tasks: list[Workload]) -> dict:
        placements = self.scheduler.assign(tasks)
        placements_by_id = {p.task_id: p for p in placements}
        total_latency_ns = 0.0
        prefetches = 0
        useful = 0
        prefetched: OrderedDict[tuple[int, str], None] = OrderedDict()
        for task in tasks:
            p = placements_by_id[task.task_id]
            for address in task.trace:
                access = self.cache.access(address, p.unit if p.domain.value == 'P' else p.unit + 8, p.domain)
                total_latency_ns += access.latency_ns
                key = (address // self.cache.c['line_bytes'], p.domain.value)
                if key in prefetched and access.level == 'l3':
                    useful += 1
                prefetched.pop(key, None)
                self.fabric.register(address, p.unit)
                line = address // self.cache.c['line_bytes']
                self.prefetcher.observe(task.task_id, line)
                for predicted in self.prefetcher.predict(task.task_id, line):
                    prefetches += 1
                    self.cache.l3.access(predicted * self.cache.c['line_bytes'], p.domain)
                    predicted_key = (predicted, p.domain.value)
                    prefetched[predicted_key] = None
                    prefetched.move_to_end(predicted_key)
                    if len(prefetched) > 4096:
                        prefetched.popitem(last=False)
        if not self.cache.l3.invariant():
            raise AssertionError('L3 partition invariant violated')
        end_ns = max((p.finish_ns for p in placements), default=0)
        return {
            'schema_version': 1,
            'interpretation': 'DETERMINISTIC_SIMULATION_ONLY',
            'tasks': len(tasks),
            'modeled_makespan_ns': end_ns,
            'modeled_trace_latency_ns': round(total_latency_ns, 6),
            'placements': [{**asdict(p), 'domain': p.domain.value} for p in placements],
            'cache_hits': self.cache.stats,
            'modeled_prefetches': prefetches,
            'modeled_useful_prefetches': useful,
            'cache_evictions': {k.value: v for k, v in self.cache.l3.evictions.items()},
            'invariants': {'cache_partition': True, 'unique_task_placement': len(placements_by_id) == len(tasks)},
        }

"""Strict public types and boundary validation for the OMEGA-X offline model."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import json
import math

class Domain(str, Enum):
    P = "P"
    E = "E"
    NPU = "NPU"

class Instruction(str, Enum):
    SCALAR = "SCALAR"
    VECTOR = "VECTOR"
    CACHE = "CACHE"
    BACKGROUND = "BACKGROUND"
    TENSOR = "TENSOR"

@dataclass(frozen=True, slots=True)
class Workload:
    task_id: int
    name: str
    instruction: Instruction
    instructions: int
    working_set_bytes: int
    wait_hz: float = 0.0
    wake_hz: float = 0.0
    vector_fraction: float = 0.0
    sparsity: float = 0.0
    cache_warmth: float = 0.0
    preferred_cpu: int | None = None
    trace: tuple[int, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if type(self.task_id) is not int or not 0 <= self.task_id < 2**63:
            raise ValueError('task_id outside 0..2^63-1')
        if not isinstance(self.name, str) or not 0 < len(self.name) <= 128 or '\x00' in self.name:
            raise ValueError('invalid task name')
        if not isinstance(self.instruction, Instruction):
            raise ValueError('unknown instruction class')
        if type(self.instructions) is not int or not 0 <= self.instructions < 2**63:
            raise ValueError('invalid instruction count')
        if type(self.working_set_bytes) is not int or not 0 <= self.working_set_bytes <= 2**40:
            raise ValueError('invalid working set')
        for value in (self.wait_hz, self.wake_hz):
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1e9:
                raise ValueError('invalid frequency')
        for value in (self.vector_fraction, self.sparsity, self.cache_warmth):
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError('fraction outside [0,1]')
        if not isinstance(self.trace, tuple) or len(self.trace) > 100000 or any(type(a) is not int or not 0 <= a < 2**64 for a in self.trace):
            raise ValueError('invalid address trace')
        if self.preferred_cpu is not None and (type(self.preferred_cpu) is not int or not 0 <= self.preferred_cpu < 8):
            raise ValueError('preferred_cpu must be P-core 0..7')

@dataclass(frozen=True, slots=True)
class Profile:
    data: dict

    def __post_init__(self) -> None:
        p = self.data
        if not isinstance(p, dict) or type(p.get('schema_version')) is not int or p['schema_version'] != 1:
            raise ValueError('invalid topology schema')
        if any(type(p.get(k)) is not int or not 1 <= p[k] <= 1024 for k in ('p_cores', 'e_cores', 'npu_units')):
            raise ValueError('invalid topology')
        c = p['cache']
        ways = c['l3_ways']
        if any(type(c.get(k)) is not int for k in ('l3_ways','p_ways','l3_bytes','line_bytes','max_resident_lines')):
            raise ValueError('invalid cache configuration types')
        if not 2 <= ways <= 64 or not 0 < c['p_ways'] < ways or not 1024 <= c['l3_bytes'] <= 2**30:
            raise ValueError('invalid L3 partition')
        if c['line_bytes'] not in (32,64,128) or c['l3_bytes'] % (ways * c['line_bytes']):
            raise ValueError('invalid cache line geometry')
        if not 0 < c['max_resident_lines'] <= 1_000_000:
            raise ValueError('invalid resident memory limit')
        sched = p['scheduler']
        weights = [sched['weight_warmth'], sched['weight_speedup'], sched['weight_criticality']]
        if any(not isinstance(w, (int,float)) or isinstance(w,bool) or not math.isfinite(w) or w < 0 for w in weights):
            raise ValueError('invalid priority weights')
        if not math.isclose(sum(weights), 1.0, abs_tol=1e-9):
            raise ValueError('priority weights must sum to one')
        for group in ('latency_ns', 'bandwidth_bytes_per_ns'):
            if not all(isinstance(v, (int,float)) and not isinstance(v,bool) and math.isfinite(v) and v > 0
                       for v in p[group].values()):
                raise ValueError('invalid modeled parameters')
        limits = p['limits']
        if type(limits['max_tasks']) is not int or not 1 <= limits['max_tasks'] <= 4096:
            raise ValueError('invalid task limit')
        if type(limits['max_payload_bytes']) is not int or not 1 <= limits['max_payload_bytes'] <= 64*1024*1024:
            raise ValueError('invalid arena limit')

def load_profile(path: str | Path) -> Profile:
    with Path(path).open(encoding='utf-8') as stream:
        return Profile(json.load(stream))


def workload_from_dict(data: dict) -> Workload:
    allowed = {f.name for f in Workload.__dataclass_fields__.values()}
    if set(data) - allowed:
        raise ValueError('unknown workload keys')
    return Workload(**{**data, 'instruction': Instruction(data['instruction']), 'trace': tuple(data.get('trace', ()))})

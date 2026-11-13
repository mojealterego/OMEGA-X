"""Deterministic admission and latency-aware scheduling of modeled virtual resources."""
from dataclasses import dataclass
from .model import Workload, Domain, Instruction, Profile
from .telemetry import composite

@dataclass(frozen=True, slots=True)
class Placement:
    task_id: int
    domain: Domain
    unit: int
    score: float
    deadline_ns: int
    start_ns: int
    finish_ns: int

class Scheduler:
    def __init__(self, profile: Profile):
        self.profile = profile
        cfg = profile.data
        self.lanes = {Domain.P: [0] * cfg['p_cores'], Domain.E: [0] * cfg['e_cores'], Domain.NPU: [0] * cfg['npu_units']}

    def assign(self, tasks: list[Workload]) -> list[Placement]:
        cfg = self.profile.data
        if len(tasks) > cfg['limits']['max_tasks'] or len({t.task_id for t in tasks}) != len(tasks):
            raise ValueError('task-count limit or duplicate task ids')
        p_capacity = cfg['cache']['l3_bytes'] * cfg['cache']['p_ways'] // cfg['cache']['l3_ways']
        order = []
        for task in tasks:
            score = composite(task, p_capacity, cfg['scheduler'])
            deadline = round(cfg['scheduler']['quantum_ns'] / max(.05, score))
            order.append((deadline, task.task_id, task, score))
        result = []
        for deadline, _, task, score in sorted(order):
            if task.instruction == Instruction.TENSOR:
                domain = Domain.NPU
            elif task.instruction in (Instruction.VECTOR, Instruction.CACHE) or score >= cfg['scheduler']['priority_threshold']:
                domain = Domain.P
            else:
                domain = Domain.E
            lanes = self.lanes[domain]
            idx = min(range(len(lanes)), key=lambda i: (lanes[i], i))
            if domain == Domain.P and task.cache_warmth >= .5 and task.preferred_cpu is not None:
                preferred = task.preferred_cpu
                if lanes[preferred] <= lanes[idx] + cfg['scheduler']['quantum_ns']:
                    idx = preferred
            start = lanes[idx]
            # Deterministic service approximation; explicitly not hardware execution time.
            nominal = {Domain.P: 3.5, Domain.E: 1.5, Domain.NPU: 5.0}[domain]
            sparse_factor = (1 - task.sparsity / 2) if domain == Domain.NPU else 1.0
            service_ns = max(1, round(task.instructions / nominal * sparse_factor))
            finish = start + service_ns
            lanes[idx] = finish
            result.append(Placement(task.task_id, domain, idx, score, deadline, start, finish))
        return result

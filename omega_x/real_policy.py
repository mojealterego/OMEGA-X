"""Conservative physical CPU placement and actual bounded process execution.

Does not register sched_ext or claim synthetic P/E/NPU hardware. Real CPU IDs are
confined to the current process affinity cpuset and validated again inside workers.
"""
from __future__ import annotations
from dataclasses import dataclass
import os

from .executor import ExecutionRequest, LocalExecutor
from .model import Instruction, Workload
from .topology import PhysicalTopology, detect_topology


@dataclass(frozen=True, slots=True)
class RealPlan:
    task_id: int
    cpu: int
    physical_class: str
    verified_topology: bool
    rationale: str


class PhysicalPlanner:
    def __init__(self, topology: PhysicalTopology):
        self.topology = topology

    def plan(self, workloads: list[Workload]) -> list[RealPlan]:
        if len(workloads) > 4096 or len({t.task_id for t in workloads}) != len(workloads):
            raise ValueError('too many workloads or duplicate identifiers')
        pools = {kind: [c for c in self.topology.cpus if c.kind == kind]
                 for kind in ('P','E','UNCLASSIFIED')}
        counters = {c.cpu_id: 0 for c in self.topology.cpus}
        results = []
        for task in workloads:
            if not isinstance(task, Workload):
                raise ValueError('invalid workload')
            background = task.instruction == Instruction.BACKGROUND
            # A TENSOR descriptor is *not* evidence of a usable physical NPU.
            priority = ('E', 'P', 'UNCLASSIFIED') if background else ('P', 'E', 'UNCLASSIFIED')
            pool = next((pools[klass] for klass in priority if pools[klass]), [])
            if not pool:
                raise RuntimeError('physical topology has no CPUs')
            choice = min(pool, key=lambda c: (counters[c.cpu_id], c.cpu_id))
            counters[choice.cpu_id] += 1
            note = 'CPU fallback: tensor task is not offloaded to NPU' if task.instruction == Instruction.TENSOR else 'Read-only physical affinity policy'
            results.append(RealPlan(task.task_id, choice.cpu_id, choice.kind,
                                    choice.kind != 'UNCLASSIFIED', note))
        return results


class PhysicalExecutor:
    """Dispatch approved real kernels, never arbitrary shell or external commands."""
    def __init__(self):
        self.executor = LocalExecutor()
        self.topology = detect_topology()

    def run(self, requests: list[ExecutionRequest], timeout_s: float = 10, workers: int = 2) -> list[dict]:
        if not 1 <= len(requests) <= 64:
            raise ValueError('requests outside bounded batch')
        if not isinstance(workers, int) or isinstance(workers, bool) or not 1 <= workers <= 16:
            raise ValueError('workers outside [1,16]')
        actual_allowed = frozenset(os.sched_getaffinity(0))
        if any(r.cpu is not None and r.cpu not in actual_allowed for r in requests):
            raise ValueError('requested CPU is not in allowed affinity')
        workloads = [Workload(i, r.kind,
                              Instruction.VECTOR if r.kind == 'saxpy'
                              else Instruction.BACKGROUND if r.kind == 'memory'
                              else Instruction.SCALAR,
                              r.size, r.size)
                     for i, r in enumerate(requests)]
        plans = PhysicalPlanner(self.topology).plan(workloads)
        assigned = [ExecutionRequest(r.kind, r.size, r.cpu if r.cpu is not None else p.cpu)
                    for r, p in zip(requests, plans)]
        results = self.executor.run_batch(assigned, timeout_s=timeout_s,
                                          workers=min(workers, len(actual_allowed)))
        for result in results:
            cpu = result['cpu_affinity']
            known = next((c for c in self.topology.cpus if c.cpu_id == cpu), None)
            result['physical_class'] = known.kind if known is not None else 'UNCLASSIFIED'
            result['cpu_class_source'] = 'sysfs core_type' if known is not None and known.kind != 'UNCLASSIFIED' else 'unknown'
            result['measured'] = True
        return results

"""Transparent EHFI-inspired (not hardware EHFI) classification and deadline input."""
import math
from .model import Workload, Instruction

SPEEDUP = {
 Instruction.SCALAR: 145/105, Instruction.VECTOR: 340/85,
 Instruction.CACHE: 310/92, Instruction.BACKGROUND: 115/110,
 Instruction.TENSOR: 220/65,
}

def criticality(task: Workload) -> float:
    return min(1.0, math.log1p(task.wait_hz * task.wake_hz)/math.log1p(1_000_000.0))

def affinity(task: Workload, p_cache_bytes: int) -> float:
    size = task.working_set_bytes
    if size <= 256 * 1024:
        return .15
    if size <= 3 * 1024**2:
        return .45
    if size <= p_cache_bytes:
        return min(1.0, .75 + (.25 if task.instruction == Instruction.CACHE else .10))
    return .60

def composite(task: Workload, p_cache_bytes: int, scheduler: dict) -> float:
    warm = max(task.cache_warmth, affinity(task, p_cache_bytes))
    speed = min(1.0, SPEEDUP[task.instruction] * (1 + .2 * task.vector_fraction) / 4.0)
    return (scheduler['weight_warmth'] * warm
            + scheduler['weight_speedup'] * speed
            + scheduler['weight_criticality'] * criticality(task))

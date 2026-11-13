"""OMEGA-X v7: bounded, inspectable *virtual* Ryzen/Intel fusion performance model.

Source: 'Wirtualna Architektura Hybrydowa Ryzen-Core.PDF', 12-task benchmark.
The simulator consumes explicit work/resource budgets. It does NOT execute AMD or
Intel machine instructions, synthesize hardware, or establish real-device speedups.
Logical time dilation is disclosed as a synthetic capacity assumption, not a
physical overclock. PDF reference numbers are comparison targets, never outputs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
import math
import random
from typing import Sequence

KINDS = frozenset({'CACHE', 'VECTOR', 'TENSOR', 'BACKGROUND'})
FAULTS = frozenset({'npu_off', 'dram_half', 'p_derate'})
PDF_REFERENCE_MS = {'amd_9850x3d': 773.71, 'intel_285k': 1159.93, 'omega_x': 294.36}
PDF_SPEEDUP_TARGET = {'amd_9850x3d': 2.63, 'intel_285k': 3.94}
MAX_TASKS = 256


def _integer(value: object, label: str, lower: int, upper: int) -> None:
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f'{label} must be an integer in [{lower},{upper}]')


def _number(value: object, label: str, lower: float, upper: float, *, inclusive_zero: bool = False) -> None:
    if (type(value) not in (int, float) or not math.isfinite(value) or
        (value < lower if inclusive_zero else value <= lower) or value > upper):
        raise ValueError(f'{label} outside allowed finite range')


@dataclass(frozen=True, slots=True)
class FusionTask:
    task_id: int
    name: str
    kind: str
    instructions: int
    working_set_bytes: int
    vector_fraction: float
    cache_warmth: float
    tensor_sparsity: float
    memory_access_fraction: float

    def __post_init__(self) -> None:
        _integer(self.task_id, 'task_id', 0, 2**63 - 1)
        if (type(self.name) is not str or not 1 <= len(self.name) <= 96 or
                any(ord(c) < 32 for c in self.name)):
            raise ValueError('invalid task name')
        if type(self.kind) is not str or self.kind not in KINDS:
            raise ValueError('invalid task kind')
        _integer(self.instructions, 'instructions', 1, 10**12)
        _integer(self.working_set_bytes, 'working_set_bytes', 0, 2**34)
        for field in ('vector_fraction', 'cache_warmth', 'tensor_sparsity', 'memory_access_fraction'):
            _number(getattr(self, field), field, 0, 1, inclusive_zero=True)


@dataclass(frozen=True, slots=True)
class Architecture:
    name: str
    p_cores: int
    e_cores: int
    npu_engines: int
    l3_bytes: int
    p_cache_bytes: int
    e_cache_bytes: int
    p_ghz: float
    e_ghz: float
    p_ipc: float
    e_ipc: float
    dram_gb_s: float
    dram_latency_ns: float
    memory_level_parallelism: int
    vector_tflops: float
    npu_tops: float
    cpu_int8_tops: float
    power_budget_watts: int
    p_watts: int
    e_watts: int
    npu_watts: int
    virtual_multiplier: int = 1
    smt_factor: int = 1

    @property
    def logical_threads(self) -> int:
        return self.p_cores * self.smt_factor + self.e_cores

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name or len(self.name) > 64:
            raise ValueError('invalid architecture name')
        for key, low, high in (
            ('p_cores', 1, 128), ('e_cores', 0, 128), ('npu_engines', 0, 64),
            ('l3_bytes', 1, 2**34), ('p_cache_bytes', 0, 2**34),
            ('e_cache_bytes', 0, 2**34), ('memory_level_parallelism', 1, 4096),
            ('power_budget_watts', 1, 100000), ('p_watts', 1, 10000),
            ('e_watts', 0, 10000), ('npu_watts', 0, 10000),
            ('virtual_multiplier', 1, 256), ('smt_factor', 1, 2),
        ):
            _integer(getattr(self, key), key, low, high)
        for key, lower, upper in (
            ('p_ghz', 0, 20), ('p_ipc', 0, 32), ('dram_gb_s', 0, 100000),
            ('dram_latency_ns', 0, 100000), ('vector_tflops', 0, 100000),
            ('cpu_int8_tops', 0, 100000),
        ):
            _number(getattr(self, key), key, lower, upper)
        for key in ('e_ghz', 'e_ipc', 'npu_tops'):
            _number(getattr(self, key), key, 0, 100000, inclusive_zero=True)
        if self.l3_bytes != self.p_cache_bytes + self.e_cache_bytes:
            raise ValueError('cache partitions must exactly sum to L3')
        if (self.e_cores == 0) != (self.e_ghz == 0 and self.e_ipc == 0 and self.e_watts == 0):
            raise ValueError('E-core resource mismatch')
        if (self.npu_engines == 0) != (self.npu_tops == 0 and self.npu_watts == 0):
            raise ValueError('NPU resource mismatch')
        if self.power_budget_watts < max(self.p_watts, self.e_watts, self.npu_watts):
            raise ValueError('power cap cannot admit one compute lane')


_MIB = 1024 * 1024

def _task(task_id: int, name: str, kind: str, instructions_m: int, ws_mib: int,
          vector: float, warmth: float, sparsity: float, mem: float) -> FusionTask:
    return FusionTask(task_id, name, kind, instructions_m * 1_000_000,
                      ws_mib * _MIB, vector, warmth, sparsity, mem)


STANDARD_TASKS = tuple([
    _task(101, 'GameEngine_Main_ECS_BVH_Loop', 'CACHE', 420, 64, .35, .80, 0, .30),
    _task(102, 'GameEngine_Audio_Physics_Sync', 'CACHE', 180, 24, .40, .70, 0, .22),
    _task(103, 'AVX512_RayTracing_SIMD_Kernel_0', 'VECTOR', 550, 48, .95, .65, 0, .12),
    _task(104, 'AVX512_FluidDynamics_FMA_Kernel_1', 'VECTOR', 520, 80, .98, .60, 0, .12),
    _task(105, 'AI_NPC_Transformer_INT8_Sparse_0', 'TENSOR', 600, 32, .85, .25, .55, .06),
    _task(106, 'AI_SuperRes_Upscaler_NPU_Tensor_1', 'TENSOR', 480, 16, .90, .25, .50, .06),
] + [
    _task(201+i, f'Parallel_ShaderCompile_Worker_{i}', 'BACKGROUND', 310, 2,
          .10, .15, 0, .08) for i in range(6)
])

REFERENCE_ARCHITECTURES = {
    'amd_9850x3d': Architecture('amd_9850x3d', 8, 0, 0, 96*_MIB, 96*_MIB, 0,
                               5.6, 0, 2.4, 0, 75, 68.5, 32, 2.8672, 0, 1.8,
                               162, 19, 0, 0, smt_factor=2),
    'intel_285k': Architecture('intel_285k', 8, 16, 1, 36*_MIB, 24*_MIB, 12*_MIB,
                              5.5, 4.6, 2.5, 2.0, 85, 88.4, 28, 2.5856, 13, 1.4,
                              250, 20, 5, 10),
    'omega_x': Architecture('omega_x', 8, 16, 4, 128*_MIB, 96*_MIB, 32*_MIB,
                            5.7, 4.65, 2.8, 2.2, 120, 51.0, 64, 4.6633, 72.9, 3.2,
                            220, 19, 6, 10, smt_factor=2),
}


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _allocate_cache(tasks: Sequence[FusionTask], budget: int) -> dict[int, int]:
    """Deterministic weighted water-filling with exact byte conservation."""
    allocations = {task.task_id: 0 for task in tasks}
    pending = {task.task_id: task for task in tasks if task.working_set_bytes}
    remaining = budget
    while remaining > 0 and pending:
        total_weight = sum((3 if t.kind == 'CACHE' else 2 if t.kind == 'VECTOR' else 1)
                           * (1 + t.cache_warmth) for t in pending.values())
        weights = {i: (3 if t.kind == 'CACHE' else 2 if t.kind == 'VECTOR' else 1)
                   * (1 + t.cache_warmth) for i, t in pending.items()}
        distributed = 0
        for task_id in sorted(pending):
            capacity = pending[task_id].working_set_bytes - allocations[task_id]
            amount = min(capacity, max(1, int(remaining * weights[task_id] / total_weight)))
            amount = min(amount, remaining - distributed)
            allocations[task_id] += amount
            distributed += amount
            if distributed == remaining:
                break
        if distributed == 0:
            raise AssertionError('cache allocator made no progress')
        remaining -= distributed
        pending = {i: t for i, t in pending.items() if allocations[i] < t.working_set_bytes}
    return allocations


def _first_power_safe(start: int, duration: int, watts: int,
                      intervals: list[tuple[int, int, int]], limit: int) -> int:
    """Earliest admissible interval under aggregate modeled power envelope."""
    for _ in range(len(intervals) + 2):
        end = start + duration
        overlaps = [(a, b, w) for a, b, w in intervals if a < end and b > start]
        edges = sorted({start, end} | {max(start, a) for a, _, _ in overlaps} |
                       {min(end, b) for _, b, _ in overlaps})
        conflict_end = None
        for left, right in zip(edges, edges[1:]):
            if sum(w for a, b, w in overlaps if a < right and b > left) + watts > limit:
                conflict_end = min(b for a, b, w in overlaps if a < right and b > left)
                break
        if conflict_end is None:
            return start
        start = max(start + 1, conflict_end)
    raise AssertionError('power admission did not converge')


def _peak_power(intervals: list[tuple[int, int, int]]) -> int:
    edges = []
    for a, b, w in intervals:
        edges.extend(((a, 1, w), (b, 0, -w)))
    peak = current = 0
    for _, _, change in sorted(edges):
        current += change
        peak = max(peak, current)
    return peak


class FusionTwin:
    """Single-host deterministic virtual-time scheduler with cache and DRAM accounting."""

    def __init__(self, architecture: Architecture):
        if not isinstance(architecture, Architecture):
            raise ValueError('validated Architecture required')
        self.architecture = architecture

    def run(self, tasks: Sequence[FusionTask], *, policy: str = 'critical_first',
            faults: tuple[str, ...] = ()) -> dict:
        if policy not in ('critical_first', 'background_first') or type(policy) is not str:
            raise ValueError('unsupported policy')
        if not isinstance(tasks, (list, tuple)) or len(tasks) > MAX_TASKS:
            raise ValueError('task count exceeds bound')
        if any(not isinstance(t, FusionTask) for t in tasks):
            raise ValueError('invalid task type')
        if len({t.task_id for t in tasks}) != len(tasks):
            raise ValueError('duplicate task IDs')
        if type(faults) is not tuple or len(faults) > 3 or any(f not in FAULTS for f in faults) or len(set(faults)) != len(faults):
            raise ValueError('invalid fault list')
        p = self.architecture
        m = p.virtual_multiplier
        if policy == 'critical_first':
            priority = {'CACHE': 0, 'VECTOR': 1, 'TENSOR': 2, 'BACKGROUND': 3}
        else:
            priority = {'BACKGROUND': 0, 'TENSOR': 1, 'VECTOR': 2, 'CACHE': 3}
        ordered = sorted(tasks, key=lambda t: (priority[t.kind], t.task_id))
        domain_of = {t.task_id: ('NPU' if t.kind == 'TENSOR' and p.npu_engines and 'npu_off' not in faults
                                else 'E' if t.kind == 'BACKGROUND' and p.e_cores else 'P') for t in ordered}
        allocations = {}
        cache_summary = {}
        for domain, budget in (('P', p.p_cache_bytes), ('E', p.e_cache_bytes)):
            sub = [t for t in ordered if domain_of[t.task_id] == domain]
            assigned = _allocate_cache(sub, budget)
            allocations.update(assigned)
            cache_summary[domain] = {'budget_bytes': budget, 'allocated_bytes': sum(assigned.values()),
                                     'tasks': len(sub)}
        lanes = {'P': [0]*p.p_cores, 'E': [0]*p.e_cores, 'NPU': [0]*p.npu_engines}
        watts = {'P': p.p_watts, 'E': p.e_watts, 'NPU': p.npu_watts}
        power_intervals: list[tuple[int, int, int]] = []
        memory_intervals: list[tuple[int, int, int]] = []
        memory_free = 0
        outcomes = []
        dram_rate = p.dram_gb_s * m * (0.5 if 'dram_half' in faults else 1)
        for task in ordered:
            domain = domain_of[task.task_id]
            allocated = allocations.get(task.task_id, 0)
            ratio = (allocated / task.working_set_bytes) if task.working_set_bytes else 1.0
            hit_ratio = min(.97, .02 + .95 * task.cache_warmth * ratio)
            # 64-byte synthetic cache line per modeled memory access.
            accesses = task.instructions * task.memory_access_fraction
            misses = accesses * (1 - hit_ratio)
            dram_bytes = math.ceil(misses * 64)
            memory_ns = math.ceil(dram_bytes / dram_rate) if dram_bytes else 0
            # Shared DRAM serializes service; fixed miss latency is hidden by modeled MLP.
            memory_start = memory_free
            memory_end = memory_start + memory_ns
            memory_free = memory_end
            memory_intervals.append((memory_start, memory_end, dram_bytes))
            lane = min(range(len(lanes[domain])), key=lambda i: (lanes[domain][i], i))
            if domain == 'NPU':
                int8_ops = task.instructions * 128 * (1 - task.tensor_sparsity)
                ops_per_ns = p.npu_tops * 1000 * m / p.npu_engines
                compute_ns = math.ceil(int8_ops / ops_per_ns)
            else:
                freq = (p.p_ghz * p.p_ipc if domain == 'P' else p.e_ghz * p.e_ipc) * m
                if domain == 'P' and 'p_derate' in faults:
                    freq *= .5
                compute_ns = math.ceil(task.instructions / freq)
                if task.kind == 'VECTOR':
                    flops = task.instructions * task.vector_fraction * 32
                    per_lane_flops_ns = p.vector_tflops * 1000 * m / p.p_cores
                    compute_ns = max(compute_ns, math.ceil(flops / per_lane_flops_ns))
                elif task.kind == 'TENSOR':
                    int8_ops = task.instructions * 128 * (1 - task.tensor_sparsity)
                    per_lane_ops_ns = p.cpu_int8_tops * 1000 * m / p.p_cores
                    compute_ns = max(compute_ns, math.ceil(int8_ops / per_lane_ops_ns))
            latency_ns = math.ceil(misses * p.dram_latency_ns / (p.memory_level_parallelism * m))
            # Memory-level parallelism hides *latency*, but not DRAM bandwidth.
            compute_ns += latency_ns
            start = max(memory_end, lanes[domain][lane])
            start = _first_power_safe(start, compute_ns, watts[domain], power_intervals,
                                      p.power_budget_watts)
            end = start + compute_ns
            lanes[domain][lane] = end
            power_intervals.append((start, end, watts[domain]))
            outcomes.append({'task_id': task.task_id, 'name': task.name, 'kind': task.kind,
                             'domain': domain, 'lane': lane, 'start_ns': start, 'end_ns': end,
                             'memory_start_ns': memory_start, 'memory_end_ns': memory_end,
                             'dram_bytes': dram_bytes, 'cache_allocated_bytes': allocated,
                             'estimated_cache_hit_ratio': round(hit_ratio, 9),
                             'compute_service_ns': compute_ns})
        outcomes.sort(key=lambda r: r['task_id'])
        peak = _peak_power(power_intervals)
        # A conservative resource-envelope bound, independent of dispatch order.
        memory_lower_bound = math.ceil(sum(x['dram_bytes'] for x in outcomes) / dram_rate)
        domain_bounds = []
        for domain, pool in lanes.items():
            if pool:
                total_service = sum(x['compute_service_ns'] for x in outcomes if x['domain'] == domain)
                domain_bounds.append(math.ceil(total_service / len(pool)))
        lower_bound_ns = max([memory_lower_bound, *domain_bounds], default=0)
        result = {'model': 'OMEGA_X_VIRTUAL_FUSION_V7',
                  'evidence_tier': 'DETERMINISTIC_VIRTUAL_MODEL',
                  'architecture': asdict(p), 'policy': policy, 'faults': list(faults),
                  'completed': len(outcomes), 'makespan_ns': max((x['end_ns'] for x in outcomes), default=0),
                  'peak_modeled_power_watts': peak, 'cache': cache_summary,
                  'dram_total_bytes': sum(x['dram_bytes'] for x in outcomes),
                  'lower_bound_ns': lower_bound_ns,
                  'tasks': outcomes,
                  'invariants': {
                      'all_tasks_once': len(outcomes) == len(tasks),
                      'cache_budget': all(v['allocated_bytes'] <= v['budget_bytes'] for v in cache_summary.values()),
                      'power_cap': peak <= p.power_budget_watts,
                      'nonnegative_time': all(x['end_ns'] >= x['start_ns'] >= x['memory_end_ns'] >= x['memory_start_ns'] for x in outcomes),
                      'bounded_workload': len(outcomes) <= MAX_TASKS,
                      'memory_conservation': sum(b for _, _, b in memory_intervals) == sum(x['dram_bytes'] for x in outcomes),
                      'resource_lower_bound': lower_bound_ns <= max((x['end_ns'] for x in outcomes), default=0),
                      'per_lane_exclusive': self._exclusive(outcomes),
                  }}
        if not all(result['invariants'].values()):
            raise AssertionError('virtual fusion invariant violation')
        result['proof_sha256'] = sha256(_canonical(result)).hexdigest()
        return result

    @staticmethod
    def _exclusive(rows: list[dict]) -> bool:
        for domain in ('P', 'E', 'NPU'):
            for lane in {r['lane'] for r in rows if r['domain'] == domain}:
                intervals = sorted((r['start_ns'], r['end_ns']) for r in rows if r['domain'] == domain and r['lane'] == lane)
                if any(b > c for (_, b), (c, _) in zip(intervals, intervals[1:])):
                    return False
        return True


def compare_architectures(*, policy: str = 'critical_first') -> dict:
    results = {name: FusionTwin(profile).run(STANDARD_TASKS, policy=policy)
               for name, profile in REFERENCE_ARCHITECTURES.items()}
    ms = {name: round(row['makespan_ns'] / 1e6, 6) for name, row in results.items()}
    omega = ms['omega_x']
    payload = {'evidence_tier': 'DETERMINISTIC_VIRTUAL_MODEL',
               'physical_ryzen_intel_fusion_verified': False,
               'source': 'Wirtualna Architektura Hybrydowa Ryzen-Core.PDF',
               'workload_count': len(STANDARD_TASKS),
               'pdf_reference_ms': dict(PDF_REFERENCE_MS),
               'model_makespan_ms': ms,
               'model_vs_pdf_delta_ms': {k: round(ms[k] - PDF_REFERENCE_MS[k], 6) for k in ms},
               'model_speedup_vs_amd': round(ms['amd_9850x3d'] / omega, 6),
               'model_speedup_vs_intel': round(ms['intel_285k'] / omega, 6),
               'results': results,
               'assumption_disclosure': 'IPC, memory access fractions, MLP, power and bandwidth are explicit modeling assumptions, not measured 9850X3D/285K performance; NPU is virtual.',
               'virtual_time_only': True}
    payload['proof_sha256'] = sha256(_canonical(payload)).hexdigest()
    return payload


def solve_virtual_envelope(*, max_multiplier: int = 16) -> dict:
    """Find minimal *synthetic logical-time capacity multiplier* satisfying PDF targets.

    The multiplier is never interpreted as real overclock, measured performance,
    extra physical cores or memory. This is an inverse modeling/feasibility exercise.
    """
    _integer(max_multiplier, 'max_multiplier', 1, 256)
    base = compare_architectures()
    amd_ns = base['results']['amd_9850x3d']['makespan_ns']
    intel_ns = base['results']['intel_285k']['makespan_ns']
    candidates = []
    for multiplier in range(1, max_multiplier + 1):
        profile = replace(REFERENCE_ARCHITECTURES['omega_x'], virtual_multiplier=multiplier)
        for policy in ('critical_first', 'background_first'):
            result = FusionTwin(profile).run(STANDARD_TASKS, policy=policy)
            duration = result['makespan_ns']
            ratios = {'amd': amd_ns / duration, 'intel': intel_ns / duration}
            meets = (duration <= round(PDF_REFERENCE_MS['omega_x'] * 1e6) and
                     ratios['amd'] >= PDF_SPEEDUP_TARGET['amd_9850x3d'] and
                     ratios['intel'] >= PDF_SPEEDUP_TARGET['intel_285k'])
            if meets:
                candidates.append((multiplier, duration, policy, result, ratios))
        if candidates:
            break
    if not candidates:
        raise ValueError('virtual contract cannot be met within bounded synthetic multiplier')
    multiplier, duration, policy, result, ratios = min(candidates, key=lambda r: (r[0], r[1], r[2]))
    payload = {'evidence_tier': 'DETERMINISTIC_VIRTUAL_MODEL',
               'contract_satisfied': True,
               'required_virtual_clock_multiplier': multiplier,
               'selected_policy': policy,
               'verified_makespan_ms': round(duration / 1e6, 6),
               'virtual_speedup_vs_amd_model': round(ratios['amd'], 6),
               'virtual_speedup_vs_intel_model': round(ratios['intel'], 6),
               'target_makespan_ms': PDF_REFERENCE_MS['omega_x'],
               'target_speedup_vs_amd': PDF_SPEEDUP_TARGET['amd_9850x3d'],
               'target_speedup_vs_intel': PDF_SPEEDUP_TARGET['intel_285k'],
               'baseline_model_makespan_ms': base['model_makespan_ms'],
               'omega_model_proof_sha256': result['proof_sha256'],
               'virtual_time_only': True,
               'physical_performance_proven': False,
               'interpretation': 'Logical time dilation of ALL modeled compute, memory bandwidth and latency resources; NOT a hardware throughput or energy measurement.'}
    payload['proof_sha256'] = sha256(_canonical(payload)).hexdigest()
    return payload


def run_sensitivity_campaign(*, seeds: int = 128, seed: int = 20261112) -> dict:
    """Bounded uncertainty sweep; does not infer confidence intervals for hardware.

    Each sample perturbs independently assumed IPC, DRAM bandwidth, MLP and
    memory-access fractions. A deterministic fault is injected in every 5th case.
    """
    _integer(seeds, 'seeds', 1, 512)
    _integer(seed, 'seed', 0, 2**63-1)
    if seed + seeds > 2**63:
        raise ValueError('seed range overflow')
    base = REFERENCE_ARCHITECTURES['omega_x']
    timings = []
    proof_heads = []
    all_pass = True
    for i in range(seeds):
        rng = random.Random(seed + i)
        profile = replace(base,
                          p_ipc=base.p_ipc * rng.uniform(.85, 1.15),
                          e_ipc=base.e_ipc * rng.uniform(.85, 1.15),
                          dram_gb_s=base.dram_gb_s * rng.uniform(.8, 1.2),
                          memory_level_parallelism=max(1, round(base.memory_level_parallelism * rng.uniform(.75, 1.25))))
        tasks = tuple(replace(t, memory_access_fraction=min(1, t.memory_access_fraction * rng.uniform(.8, 1.2)))
                      for t in STANDARD_TASKS)
        faults = (('npu_off',) if i % 5 == 0 else ())
        result = FusionTwin(profile).run(tasks, faults=faults)
        timings.append(result['makespan_ns'] / 1e6)
        proof_heads.append(result['proof_sha256'])
        all_pass &= all(result['invariants'].values())
    timings.sort()
    def quantile(q: float) -> float:
        return round(timings[math.ceil(q * len(timings)) - 1], 6)
    payload = {'model': 'OMEGA_X_V7_SENSITIVITY', 'evidence_tier': 'DETERMINISTIC_VIRTUAL_MODEL',
               'scenarios': seeds, 'seed': seed, 'p05_ms': quantile(.05),
               'p50_ms': quantile(.5), 'p95_ms': quantile(.95),
               'min_ms': round(timings[0], 6), 'max_ms': round(timings[-1], 6),
               'target_ms': PDF_REFERENCE_MS['omega_x'],
               'target_met_count': sum(t <= PDF_REFERENCE_MS['omega_x'] for t in timings),
               'all_invariants_pass': all_pass, 'physical_validation': False,
               'scenario_proofs': proof_heads,
               'uncertainty_scope': 'Selected modeling assumptions varied, NOT hardware measurement error.'}
    payload['proof_sha256'] = sha256(_canonical(payload)).hexdigest()
    return payload

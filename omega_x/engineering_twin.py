"""OMEGA-X external architecture digital twin.

This is a deterministic discrete-resource model, not an emulator of a real AMD/Intel
microarchitecture. Virtual lanes, rates, power and faults are explicit assumptions.
Every simulated operation is bounded, replayable and cryptographically fingerprinted.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import random


KINDS = frozenset(('VECTOR', 'BACKGROUND', 'TENSOR'))
FAULT_KINDS = frozenset(('p_down', 'e_down', 'npu_down', 'fabric_down', 'thermal_derate'))


def _positive(value: int, label: str, upper: int) -> None:
    if type(value) is not int or not 0 < value <= upper:
        raise ValueError(f'{label} must be an integer in [1,{upper}]')


def _nonnegative(value: int, label: str, upper: int) -> None:
    if type(value) is not int or not 0 <= value <= upper:
        raise ValueError(f'{label} must be an integer in [0,{upper}]')


@dataclass(frozen=True, slots=True)
class Profile:
    p_lanes: int = 8
    e_lanes: int = 16
    npu_lanes: int = 4
    p_ops_per_us: int = 3000
    e_ops_per_us: int = 1600
    npu_ops_per_us: int = 8000
    fabric_bytes_per_ns: int = 32
    link_latency_ns: int = 800
    p_lane_watts: int = 20
    e_lane_watts: int = 8
    npu_lane_watts: int = 10
    power_budget_watts: int = 120
    max_tasks: int = 4096

    def __post_init__(self) -> None:
        for name in ('p_lanes', 'e_lanes', 'p_ops_per_us', 'e_ops_per_us',
                     'npu_ops_per_us', 'fabric_bytes_per_ns', 'p_lane_watts',
                     'e_lane_watts', 'npu_lane_watts', 'power_budget_watts', 'max_tasks'):
            _positive(getattr(self, name), name, 100_000_000)
        _nonnegative(self.npu_lanes, 'npu_lanes', 128)
        _nonnegative(self.link_latency_ns, 'link_latency_ns', 10**12)
        if self.p_lanes > 128 or self.e_lanes > 128 or self.max_tasks > 4096:
            raise ValueError('resource model bounds exceeded')
        if self.power_budget_watts < max(self.p_lane_watts, self.e_lane_watts,
                                         self.npu_lane_watts if self.npu_lanes else 0):
            raise ValueError('power budget cannot admit a single operation')


@dataclass(frozen=True, slots=True)
class TwinTask:
    task_id: int
    tenant: str
    kind: str
    ops: int
    transfer_bytes: int
    arrival_ns: int
    deadline_ns: int

    def __post_init__(self) -> None:
        _nonnegative(self.task_id, 'task_id', 2**63 - 1)
        if not isinstance(self.tenant, str) or not (1 <= len(self.tenant) <= 64) or not self.tenant.isascii() or not all(c.isalnum() or c in '-_' for c in self.tenant):
            raise ValueError('invalid tenant')
        if self.kind not in KINDS or type(self.kind) is not str:
            raise ValueError('invalid workload kind')
        _positive(self.ops, 'ops', 2**53)
        _nonnegative(self.transfer_bytes, 'transfer_bytes', 2**30)
        _nonnegative(self.arrival_ns, 'arrival_ns', 10**15)
        _nonnegative(self.deadline_ns, 'deadline_ns', 10**15)
        if self.deadline_ns < self.arrival_ns:
            raise ValueError('deadline precedes arrival')


@dataclass(frozen=True, slots=True)
class Fault:
    kind: str
    start_ns: int
    end_ns: int

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or self.kind not in FAULT_KINDS:
            raise ValueError('unsupported fault')
        _nonnegative(self.start_ns, 'start_ns', 10**15)
        _nonnegative(self.end_ns, 'end_ns', 10**15)
        if self.end_ns <= self.start_ns:
            raise ValueError('fault window is empty')


class DigitalTwin:
    """Finite, single-process simulation of virtual compute lanes and a shared fabric.

    Faults are windows in modeled time; NPU outages select CPU fallback where safe.
    Power is enforced by serialization against overlapping reservations, including
    per-domain lanes. No claim is made about real-world nanosecond accuracy.
    """

    def __init__(self, profile: Profile, seed: int):
        if not isinstance(profile, Profile):
            raise ValueError('profile must be validated')
        _nonnegative(seed, 'seed', 2**63-1)
        self.profile = profile
        self.seed = seed

    @staticmethod
    def _fair_order(tasks: list[TwinTask]) -> list[TwinTask]:
        ordered: list[TwinTask] = []
        groups: dict[int, list[TwinTask]] = defaultdict(list)
        for task in tasks:
            groups[task.arrival_ns].append(task)
        for arrival in sorted(groups):
            tenants: dict[str, deque[TwinTask]] = defaultdict(deque)
            for task in sorted(groups[arrival], key=lambda t: (t.tenant, t.task_id)):
                tenants[task.tenant].append(task)
            while tenants:
                for name in sorted(tuple(tenants)):
                    ordered.append(tenants[name].popleft())
                    if not tenants[name]:
                        del tenants[name]
        return ordered

    @staticmethod
    def _intersects(fault: Fault, start: int, end: int) -> bool:
        return fault.start_ns < end and fault.end_ns > start

    @staticmethod
    def _blocked(faults: tuple[Fault, ...], kind: str, at: int) -> bool:
        return any(f.kind == kind and f.start_ns <= at < f.end_ns for f in faults)

    @classmethod
    def _next_safe(cls, faults: tuple[Fault, ...], kind: str, start: int, duration: int) -> int:
        # Finite: each iteration advances to a strictly larger fault end time.
        while True:
            ends = [f.end_ns for f in faults if f.kind == kind and cls._intersects(f, start, start + duration)]
            if not ends:
                return start
            start = max(ends)

    @staticmethod
    def _power_safe(start: int, duration: int, watts: int,
                    reservations: list[tuple[int, int, int]], limit: int) -> int:
        """Find first start with no interval exceeding aggregate modeled watts."""
        for _ in range(len(reservations) + 1):
            end = start + duration
            overlaps = [(a, b, w) for a, b, w in reservations if a < end and b > start]
            boundaries = sorted({start, end} | {max(a, start) for a, _, _ in overlaps} |
                                {min(b, end) for _, b, _ in overlaps})
            violation = False
            for a, b in zip(boundaries, boundaries[1:]):
                if a >= b:
                    continue
                concurrent = sum(w for x, y, w in overlaps if x < b and y > a)
                if concurrent + watts > limit:
                    # Every conflict involves an existing reservation that will finish.
                    start = min(y for x, y, w in overlaps if x < b and y > a)
                    violation = True
                    break
            if not violation:
                return start
        raise AssertionError('bounded power scheduler failed to progress')

    @staticmethod
    def _peak_power(reservations: list[tuple[int, int, int]]) -> int:
        # End releases are processed before starts at equal timestamp.
        sweep = []
        for start, end, watts in reservations:
            sweep.append((start, 1, watts))
            sweep.append((end, 0, -watts))
        current = peak = 0
        for _, _, delta in sorted(sweep):
            current += delta
            peak = max(peak, current)
            if current < 0:
                raise AssertionError('negative simulated power')
        return peak

    def run(self, tasks: list[TwinTask], faults: list[Fault] | tuple[Fault, ...] = (),
            *, policy: str = 'compat') -> dict:
        if policy not in ('compat', 'earliest_finish') or type(policy) is not str:
            raise ValueError('unsupported scheduling policy')
        if not isinstance(tasks, (tuple, list)) or len(tasks) > self.profile.max_tasks:
            raise ValueError('unbounded task count')
        if any(not isinstance(t, TwinTask) for t in tasks):
            raise ValueError('task types invalid')
        if len({t.task_id for t in tasks}) != len(tasks):
            raise ValueError('duplicate task id')
        if not isinstance(faults, (tuple, list)) or len(faults) > 256 or any(not isinstance(f, Fault) for f in faults):
            raise ValueError('invalid bounded fault list')
        faults = tuple(sorted(faults, key=lambda f: (f.start_ns, f.kind, f.end_ns)))
        rng = random.Random(self.seed)
        available = {'P': [0]*self.profile.p_lanes, 'E': [0]*self.profile.e_lanes,
                     'NPU': [0]*self.profile.npu_lanes}
        powers = {'P': self.profile.p_lane_watts, 'E': self.profile.e_lane_watts,
                  'NPU': self.profile.npu_lane_watts}
        rates = {'P': self.profile.p_ops_per_us, 'E': self.profile.e_ops_per_us,
                 'NPU': self.profile.npu_ops_per_us}
        reservations: list[tuple[int, int, int]] = []
        fabric_free = 0
        out = []
        for task in self._fair_order(tasks):
            preference = ('NPU', 'P', 'E') if task.kind == 'TENSOR' else (
                ('E', 'P') if task.kind == 'BACKGROUND' else ('P', 'E'))
            eligible = [d for d in preference if available[d] and
                        not self._blocked(faults, d.lower()+'_down', task.arrival_ns)]
            if not eligible:
                out.append({'task_id': task.task_id, 'tenant': task.tenant, 'kind': task.kind,
                            'domain': None, 'lane': None, 'status': 'unavailable',
                            'fabric_started_ns': None, 'compute_started_ns': None,
                            'finish_ns': task.arrival_ns, 'latency_ns': 0})
                continue
            jitter = rng.randrange(0, 16)
            transit_ns = (self.profile.link_latency_ns +
                          (task.transfer_bytes + self.profile.fabric_bytes_per_ns - 1)
                          // self.profile.fabric_bytes_per_ns + jitter) if task.transfer_bytes else 0
            fabric_start = max(task.arrival_ns, fabric_free)
            if transit_ns:
                fabric_start = self._next_safe(faults, 'fabric_down', fabric_start, transit_ns)
                fabric_free = fabric_start + transit_ns
            compute_ready = max(task.arrival_ns, fabric_start + transit_ns)
            if policy == 'compat':
                domain = eligible[0]
            else:
                # Same physical/virtual resources for all candidate policies; a
                # candidate may only change placement, never mint new capacity.
                def estimate(domain_name: str) -> tuple[int, int]:
                    lane_id = min(range(len(available[domain_name])),
                                  key=lambda i: (available[domain_name][i], i))
                    cost = max(1, (task.ops*1000 + rates[domain_name] - 1) // rates[domain_name])
                    ready = max(compute_ready, available[domain_name][lane_id])
                    if any(f.kind == 'thermal_derate' and self._intersects(f, ready, ready+cost)
                           for f in faults):
                        cost *= 2
                    for _ in range(len(reservations) + len(faults) + 4):
                        safe = self._next_safe(faults, domain_name.lower()+'_down', ready, cost)
                        safe = self._power_safe(safe, cost, powers[domain_name], reservations,
                                                self.profile.power_budget_watts)
                        if safe == ready:
                            break
                        ready = safe
                    else:
                        raise AssertionError('candidate admission failed to converge')
                    return (ready + cost, preference.index(domain_name))
                domain = min(eligible, key=estimate)
            lane = min(range(len(available[domain])), key=lambda i: (available[domain][i], i))
            compute_ns = max(1, (task.ops * 1000 + rates[domain] - 1)//rates[domain])
            if any(f.kind == 'thermal_derate' and self._intersects(f, compute_ready, compute_ready + compute_ns)
                   for f in faults):
                compute_ns *= 2
            started = max(compute_ready, available[domain][lane])
            for _ in range(len(reservations) + len(faults) + 4):
                safe = self._next_safe(faults, domain.lower()+'_down', started, compute_ns)
                safe = self._power_safe(safe, compute_ns, powers[domain], reservations,
                                        self.profile.power_budget_watts)
                if safe == started:
                    break
                started = safe
            else:
                raise AssertionError('bounded resource admission failed')
            finished = started + compute_ns
            available[domain][lane] = finished
            reservations.append((started, finished, powers[domain]))
            out.append({'task_id': task.task_id, 'tenant': task.tenant, 'kind': task.kind,
                        'domain': domain, 'lane': lane, 'status': ('completed' if finished <= task.deadline_ns
                                                                else 'deadline_miss'),
                        'fabric_started_ns': fabric_start, 'compute_started_ns': started,
                        'finish_ns': finished, 'latency_ns': finished - task.arrival_ns})
        peak = self._peak_power(reservations)
        result = {
            'mode': 'discrete_resource_digital_twin', 'evidence_tier': 'SIMULATED_TESTED',
            'seed': self.seed, 'policy': policy, 'assumptions': asdict(self.profile), 'faults': [asdict(f) for f in faults],
            'jobs': len(tasks), 'completed': sum(x['status']=='completed' for x in out),
            'deadline_misses': sum(x['status']=='deadline_miss' for x in out),
            'unavailable': sum(x['status']=='unavailable' for x in out),
            'peak_power_watts': peak, 'makespan_ns': max((r['finish_ns'] for r in out), default=0),
            'latency_p99_ns': None, 'outcomes': out,
        }
        latencies = sorted(x['latency_ns'] for x in out if x['status'] != 'unavailable')
        if latencies:
            result['latency_p99_ns'] = latencies[math.ceil(len(latencies)*.99)-1]
        result['invariants'] = {
            'conservation': result['completed'] + result['deadline_misses'] + result['unavailable'] == len(tasks),
            'unique_dispatch': len({row['task_id'] for row in out}) == len(tasks),
            'power_budget': peak <= self.profile.power_budget_watts,
            'monotonic_timing': all(row['compute_started_ns'] >= row['fabric_started_ns'] >= task.arrival_ns
                                    and row['finish_ns'] >= row['compute_started_ns']
                                    for row in out for task in tasks if row['task_id'] == task.task_id
                                    and row['status'] != 'unavailable'),
            'bounded_resources': len(out) <= self.profile.max_tasks and
                                 all(len(pool) <= 128 for pool in available.values()),
        }
        if not all(result['invariants'].values()):
            raise AssertionError('simulation invariant failed')
        result['proof_sha256'] = hashlib.sha256(
            json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
        ).hexdigest()
        return result


def run_multiseed_campaign(seeds: int = 50, jobs_per_seed: int = 48, base_seed: int = 20261112) -> dict:
    _positive(seeds, 'seeds', 200)
    _positive(jobs_per_seed, 'jobs_per_seed', 512)
    _nonnegative(base_seed, 'base_seed', 2**63-1)
    results = []
    injected = 0
    for n in range(seeds):
        seed = base_seed + n
        rng = random.Random(seed)
        jobs = [TwinTask(task_id=i, tenant=f'tenant_{rng.randrange(5)}',
                         kind=rng.choice(tuple(sorted(KINDS))),
                         ops=rng.randrange(200, 100_000), transfer_bytes=rng.randrange(0, 64_000),
                         arrival_ns=rng.randrange(0, 50_000), deadline_ns=rng.randrange(150_000, 400_000))
                for i in range(jobs_per_seed)]
        faults = [Fault('fabric_down', 2000, 6000),
                  Fault('npu_down', 8000, 18000),
                  Fault('p_down', 12000, 16000),
                  Fault('thermal_derate', 22000, 30000)]
        injected += len(faults)
        result = DigitalTwin(Profile(), seed).run(jobs, faults)
        results.append({'seed': seed, 'proof_sha256': result['proof_sha256'],
                        'invariants': result['invariants'], 'completed': result['completed'],
                        'deadline_misses': result['deadline_misses'], 'unavailable': result['unavailable'],
                        'peak_power_watts': result['peak_power_watts']})
    summary = {'seeds': seeds, 'jobs': seeds*jobs_per_seed, 'injected_faults': injected,
               'all_invariants_pass': all(all(x['invariants'].values()) for x in results),
               'completed': sum(x['completed'] for x in results),
               'deadline_misses': sum(x['deadline_misses'] for x in results),
               'unavailable': sum(x['unavailable'] for x in results),
               'seed_proofs': [r['proof_sha256'] for r in results],
               'scope': 'DETERMINISTIC_SIMULATION_NOT_PHYSICAL_HARDWARE_VALIDATION'}
    summary['campaign_sha256'] = hashlib.sha256(
        json.dumps(summary, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return summary

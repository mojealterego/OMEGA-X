"""Bounded coherent-memory digital twin with SWMR, fencing and partition safety.

Reference safety model for external CXL/coherence hardware. Not a hardware driver.
The committed backing store and directory are in-process and intentionally synthetic.
"""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass, field
from hashlib import sha256
import json


class CoherenceUnavailable(RuntimeError):
    """Requested coherence transition cannot obtain required acknowledgements."""


class StaleLease(ValueError):
    """Invalidated, expired or forged simulated directory lease."""


@dataclass(frozen=True, slots=True)
class Lease:
    node: int
    line: int
    epoch: int
    version: int
    token: int
    mode: str


@dataclass(slots=True)
class _Entry:
    version: int
    holders: dict[int, int] = field(default_factory=dict)
    writer: int | None = None


class CoherenceTwin:
    """Single-writer/multiple-reader state machine with fencing.

    Partition policy: any proposed write that cannot revoke *every* other holder
    is rejected; a reader cannot acquire from an unreachable modified owner.
    At a directory capacity limit, all local holders are invalidated before
    directory eviction, while committed backing values persist.
    """
    def __init__(self, nodes: int = 3, directory_capacity: int = 65536):
        if type(nodes) is not int or not 2 <= nodes <= 32:
            raise ValueError('nodes out of range [2,32]')
        if type(directory_capacity) is not int or not 1 <= directory_capacity <= 65536:
            raise ValueError('directory capacity out of range [1,65536]')
        self.nodes = nodes
        self.capacity = directory_capacity
        self._links = [[True] * nodes for _ in range(nodes)]
        self._directory: OrderedDict[int, _Entry] = OrderedDict()
        self._memory: dict[int, tuple[int, int]] = {}
        self._epoch = 1
        self._next_token = 0
        self._snoops = 0
        self._invalidations = 0
        self._evictions = 0
        self._denied = 0

    @property
    def directory_size(self) -> int:
        return len(self._directory)

    def _validate(self, node: int, line: int) -> None:
        if type(node) is not int or not 0 <= node < self.nodes:
            raise ValueError('invalid node')
        if type(line) is not int or not 0 <= line <= 2**63 - 1:
            raise ValueError('invalid line')

    def _reachable(self, a: int, b: int) -> bool:
        return self._links[a][b] and self._links[b][a]

    def _entry(self, line: int, requester: int) -> _Entry:
        current = self._directory.get(line)
        if current is not None:
            self._directory.move_to_end(line)
            return current
        if len(self._directory) >= self.capacity:
            old_line, old = next(iter(self._directory.items()))
            if any(not self._reachable(requester, remote) for remote in old.holders):
                self._denied += 1
                raise CoherenceUnavailable('directory eviction lacks remote invalidation ack')
            self._directory.pop(old_line)
            self._snoops += len(old.holders) - int(requester in old.holders)
            self._invalidations += len(old.holders)
            self._evictions += 1
        version = self._memory.get(line, (0, 0))[0]
        created = _Entry(version=version)
        self._directory[line] = created
        return created

    def _grant(self, node: int, line: int, entry: _Entry, mode: str) -> Lease:
        self._next_token += 1
        entry.holders[node] = self._next_token
        entry.writer = node if mode == 'M' else None
        return Lease(node, line, self._epoch, entry.version, self._next_token, mode)

    def _revoke(self, entry: _Entry) -> None:
        self._invalidations += len(entry.holders)
        entry.holders.clear()
        entry.writer = None

    def acquire_shared(self, node: int, line: int) -> Lease:
        self._validate(node, line)
        entry = self._entry(line, node)
        if entry.writer is not None:
            if not self._reachable(node, entry.writer):
                self._denied += 1
                raise CoherenceUnavailable('modified owner unreachable; read rejected')
            self._snoops += int(node != entry.writer)
            entry.writer = None
        return self._grant(node, line, entry, 'S')

    def acquire_exclusive(self, node: int, line: int) -> Lease:
        self._validate(node, line)
        entry = self._entry(line, node)
        # Validate all invalidation acknowledgements *before* changing state.
        unreachable = [other for other in entry.holders if not self._reachable(node, other)]
        if unreachable:
            self._denied += 1
            raise CoherenceUnavailable('cannot invalidate remote cached line')
        self._snoops += len(entry.holders) - int(node in entry.holders)
        self._revoke(entry)
        return self._grant(node, line, entry, 'M')

    def _check_lease(self, lease: Lease) -> _Entry:
        if not isinstance(lease, Lease) or lease.epoch != self._epoch:
            raise StaleLease('epoch mismatch')
        self._validate(lease.node, lease.line)
        entry = self._directory.get(lease.line)
        if (entry is None or entry.version != lease.version or
                entry.holders.get(lease.node) != lease.token or
                (lease.mode == 'M' and entry.writer != lease.node) or
                (lease.mode not in ('S', 'M'))):
            raise StaleLease('lease is revoked or stale')
        return entry

    def read(self, lease: Lease) -> int:
        self._check_lease(lease)
        return self._memory.get(lease.line, (0, 0))[1]

    def write(self, lease: Lease, value: int) -> int:
        if type(value) is not int or not -2**63 <= value < 2**63:
            raise ValueError('value outside signed 64-bit model')
        entry = self._check_lease(lease)
        if lease.mode != 'M' or entry.writer != lease.node:
            raise StaleLease('write requires exclusive lease')
        if entry.version >= 2**63 - 1:
            raise OverflowError('version overflow')
        entry.version += 1
        self._memory[lease.line] = (entry.version, value)
        # Version changed: previous lease is invalid; mint a replacement.
        self._next_token += 1
        entry.holders[lease.node] = self._next_token
        return entry.version

    def partition(self, groups: tuple[tuple[int, ...], ...]) -> None:
        if not isinstance(groups, tuple) or not groups or any(not isinstance(g, tuple) or not g for g in groups):
            raise ValueError('groups must be non-empty tuples')
        flat = [item for group in groups for item in group]
        if any(type(n) is not int for n in flat) or sorted(flat) != list(range(self.nodes)):
            raise ValueError('partition must cover every node exactly once')
        for i in range(self.nodes):
            for j in range(self.nodes):
                self._links[i][j] = any(i in group and j in group for group in groups)

    def heal(self) -> None:
        for row in self._links:
            row[:] = [True] * self.nodes

    def restart(self) -> None:
        """Simulated full-directory crash: persistent memory survives; leases do not."""
        self._epoch += 1
        self._invalidations += sum(len(entry.holders) for entry in self._directory.values())
        self._directory.clear()
        self.heal()

    def invariants(self) -> dict[str, bool]:
        return {
            'single_writer_multiple_reader': all(entry.writer is None or
                                                 (len(entry.holders) == 1 and entry.writer in entry.holders)
                                                 for entry in self._directory.values()),
            'directory_bound': len(self._directory) <= self.capacity,
            'version_matches_persistent_memory': all(entry.version == self._memory.get(line, (0, 0))[0]
                                                     for line, entry in self._directory.items()),
            'symmetric_partition_links': all(self._links[i][j] == self._links[j][i]
                                              for i in range(self.nodes) for j in range(self.nodes)),
            'self_reachability': all(self._links[i][i] for i in range(self.nodes)),
            'unique_tokens_per_active_lease': len({v for entry in self._directory.values()
                                                   for v in entry.holders.values()}) ==
                                              sum(len(entry.holders) for entry in self._directory.values()),
        }

    def report(self) -> dict:
        body = {'mode': 'CXL_like_coherence_state_machine', 'evidence_tier': 'SIMULATED_TESTED',
                'nodes': self.nodes, 'directory_capacity': self.capacity,
                'directory_size': self.directory_size, 'epoch': self._epoch,
                'snoop_messages': self._snoops, 'invalidations': self._invalidations,
                'evictions': self._evictions, 'fail_closed_rejections': self._denied,
                'stored_lines': len(self._memory), 'invariants': self.invariants()}
        if not all(body['invariants'].values()):
            raise AssertionError('coherence invariants violated')
        body['proof_sha256'] = sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        return body


def run_coherence_campaign(seeds: int = 50, rounds: int = 120,
                           base_seed: int = 20261112) -> dict:
    """Multi-seed partition/fencing/memory safety campaign; all outputs modeled."""
    if type(seeds) is not int or not 1 <= seeds <= 200:
        raise ValueError('seeds out of range')
    if type(rounds) is not int or not 1 <= rounds <= 2000:
        raise ValueError('rounds out of range')
    if type(base_seed) is not int or not 0 <= base_seed < 2**63 - seeds:
        raise ValueError('seed out of range')
    import random
    reports = []
    for idx in range(seeds):
        seed = base_seed + idx
        rng = random.Random(seed)
        nodes = (3, 5, 7)[idx % 3]
        twin = CoherenceTwin(nodes=nodes, directory_capacity=16)
        refusals = 0
        actions = {'read': 0, 'write': 0, 'partition': 0, 'heal': 0, 'restart': 0}
        for _ in range(rounds):
            action = rng.randrange(100)
            if action < 45:
                actions['read'] += 1
                try:
                    lease = twin.acquire_shared(rng.randrange(nodes), rng.randrange(64))
                    twin.read(lease)
                except CoherenceUnavailable:
                    refusals += 1
            elif action < 80:
                actions['write'] += 1
                try:
                    lease = twin.acquire_exclusive(rng.randrange(nodes), rng.randrange(64))
                    twin.write(lease, rng.randrange(-10000, 10000))
                except CoherenceUnavailable:
                    refusals += 1
            elif action < 89:
                actions['partition'] += 1
                group = list(range(nodes))
                rng.shuffle(group)
                split = rng.randrange(1, nodes)
                twin.partition((tuple(group[:split]), tuple(group[split:])))
            elif action < 96:
                actions['heal'] += 1
                twin.heal()
            else:
                actions['restart'] += 1
                twin.restart()
            if not all(twin.invariants().values()):
                raise AssertionError(f'coherence safety failed at seed={seed}')
        report = twin.report()
        reports.append({'seed': seed, 'nodes': nodes, 'proof_sha256': report['proof_sha256'],
                        'rejections': refusals, 'invariants': report['invariants'],
                        'actions': actions})
    summary = {'seeds': seeds, 'events': seeds * rounds,
               'all_invariants_pass': all(all(r['invariants'].values()) for r in reports),
               'fail_closed_rejections': sum(r['rejections'] for r in reports),
               'campaign_proofs': [r['proof_sha256'] for r in reports],
               'mode': 'in_process_coherence_simulation',
               'scope': 'SIMULATED_TESTED_NOT_CXL_HARDWARE_VERIFIED'}
    summary['campaign_sha256'] = sha256(json.dumps(summary, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return summary

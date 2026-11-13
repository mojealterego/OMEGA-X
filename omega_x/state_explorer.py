"""Bounded explicit-state model checker for coherence and crash/fencing semantics.

Exhaustively explores *this modeled state machine* to a specified depth; it does
not claim formal proof about hardware, kernel interfaces or infinite executions.
"""
from __future__ import annotations

from collections import deque
import copy
from hashlib import sha256
import json

from .coherence_twin import CoherenceTwin, CoherenceUnavailable, Lease, StaleLease


def _signature(twin: CoherenceTwin, leases: tuple[Lease | None, ...]) -> str:
    """Canonical representation of all state that can affect subsequent actions."""
    return json.dumps({
        'epoch': twin._epoch,
        'token_counter': twin._next_token,
        'memory': sorted((line, version, value)
                         for line, (version, value) in twin._memory.items()),
        'directory': [(line, entry.version, entry.writer, sorted(entry.holders.items()))
                      for line, entry in twin._directory.items()],
        'links': twin._links,
        'leases': [None if lease is None else
                   (lease.node, lease.line, lease.epoch, lease.version, lease.token, lease.mode)
                   for lease in leases],
    }, sort_keys=True, separators=(',', ':'))


def explore_coherence(*, nodes: int = 2, depth: int = 4, capacity: int = 2) -> dict:
    """Explore all generated transitions for two/three nodes, one cache line.

    Each transition checks SWMR, monotonic committed version, stale lease fencing
    and fail-closed rejection. Failing invariant raises with a counterexample trace.
    """
    if type(nodes) is not int or nodes not in (2, 3):
        raise ValueError('exhaustive explorer requires 2 or 3 nodes')
    if type(depth) is not int or not 1 <= depth <= 4:
        raise ValueError('depth outside [1,4]')
    if type(capacity) is not int or not 1 <= capacity <= 4:
        raise ValueError('directory capacity outside [1,4]')
    actions = tuple((action, node) for action in ('shared','exclusive','read','write')
                    for node in range(nodes)) + (('partition', -1), ('heal', -1), ('restart', -1))
    initial = (CoherenceTwin(nodes=nodes, directory_capacity=capacity), tuple(None for _ in range(nodes)))
    queue = deque([(initial[0], initial[1], ())])
    seen = {_signature(*initial)}
    transitions = rejections = stale = 0
    reached_depth = 0
    while queue:
        twin, leases, history = queue.popleft()
        reached_depth = max(reached_depth, len(history))
        if len(history) == depth:
            continue
        for action, node in actions:
            candidate = copy.deepcopy(twin)
            held = list(leases)
            before_mem = dict(candidate._memory)
            before_versions = {line: version for line, (version, _) in before_mem.items()}
            transitions += 1
            try:
                if action == 'shared':
                    held[node] = candidate.acquire_shared(node, 0)
                elif action == 'exclusive':
                    held[node] = candidate.acquire_exclusive(node, 0)
                elif action == 'read':
                    if held[node] is not None:
                        candidate.read(held[node])
                elif action == 'write':
                    if held[node] is not None:
                        # A previous write's lease becomes stale by design.
                        candidate.write(held[node], 100 + node)
                elif action == 'partition':
                    candidate.partition((tuple(range(1)), tuple(range(1, nodes))))
                elif action == 'heal':
                    candidate.heal()
                elif action == 'restart':
                    candidate.restart()
            except (StaleLease, CoherenceUnavailable) as exc:
                rejections += 1
                stale += isinstance(exc, StaleLease)
                if candidate._memory != before_mem:
                    raise AssertionError('rejected operation changed committed memory') from exc
            if any(not ok for ok in candidate.invariants().values()):
                raise AssertionError(f'invariant violated by trace {history + ((action, node),)}')
            if any(candidate._memory.get(line, (0, 0))[0] < version
                   for line, version in before_versions.items()):
                raise AssertionError(f'version rollback by trace {history + ((action, node),)}')
            signature = _signature(candidate, tuple(held))
            if signature not in seen:
                seen.add(signature)
                queue.append((candidate, tuple(held), history + ((action, node),)))
    body = {'mode': 'bounded_explicit_state_exploration',
            'evidence_tier': 'SIMULATED_TESTED',
            'scope': 'FINITE_COHERENCE_MODEL_NOT_REAL_HARDWARE',
            'nodes': nodes, 'depth': depth, 'capacity': capacity,
            'states': len(seen), 'transitions': transitions,
            'denied_operations': rejections, 'rejected_stale_leases': stale,
            'all_invariants_pass': True, 'search_exhausted': True}
    body['proof_sha256'] = sha256(json.dumps(body, sort_keys=True,
                                          separators=(',', ':')).encode()).hexdigest()
    return body

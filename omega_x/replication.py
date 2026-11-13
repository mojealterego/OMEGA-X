"""Deterministic quorum replication twin; no physical network or consensus protocol claims."""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import json
import math
import random


@dataclass
class Node:
    node_id: int
    alive: bool = True
    log: list[str] = field(default_factory=list)


class QuorumTwin:
    """Single-writer modeled log; atomic quorum commit and deterministic failover.

    This is a safety-focused digital twin, not Raft, Paxos or production consensus.
    """
    def __init__(self, nodes: int = 3, seed: int = 0):
        if not isinstance(nodes, int) or nodes not in (3, 5, 7):
            raise ValueError('odd cluster size must be 3, 5 or 7')
        self.nodes = [Node(i) for i in range(nodes)]
        self.quorum = nodes // 2 + 1
        self._links = [[True] * nodes for _ in range(nodes)]
        self.committed: list[str] = []
        self.receipts: list[tuple[int, ...]] = []
        self.leader: int | None = 0
        self.rng = random.Random(seed)
        self.latencies_ns: list[int] = []
        self.rejected = 0

    def _reachable(self, index: int) -> list[int]:
        return [n.node_id for n in self.nodes if n.alive and self._links[index][n.node_id]]

    def elect(self) -> int | None:
        candidates = [n for n in self.nodes if n.alive and len(self._reachable(n.node_id)) >= self.quorum]
        self.leader = min(candidates, key=lambda n: (-len(n.log), n.node_id)).node_id if candidates else None
        return self.leader

    def append(self, item: str) -> bool:
        if not isinstance(item, str) or not item or len(item.encode('utf-8')) > 4096:
            raise ValueError('invalid log item')
        leader = self.elect()
        if leader is None:
            self.rejected += 1
            return False
        acks = self._reachable(leader)
        if len(acks) < self.quorum:
            self.rejected += 1
            return False
        # Atomic committed-prefix replication is the explicit abstraction boundary.
        new_log = self.committed + [item]
        for node_id in acks:
            self.nodes[node_id].log = new_log.copy()
        self.committed.append(item)
        self.receipts.append(tuple(sorted(acks)))
        # Synthetic latency, not an observation of a physical link.
        self.latencies_ns.append(15000 + self.rng.randrange(10000) + len(item.encode()) * 8)
        return True

    def crash(self, node_id: int) -> None:
        self._check_node(node_id)
        self.nodes[node_id].alive = False
        self.elect()

    def recover(self, node_id: int) -> None:
        self._check_node(node_id)
        self.nodes[node_id].alive = True
        self.elect()

    def _check_node(self, node_id: int):
        if isinstance(node_id, bool) or not isinstance(node_id, int) or not 0 <= node_id < len(self.nodes):
            raise ValueError('unknown node id')

    def partition(self, groups: tuple[tuple[int, ...], ...]) -> None:
        flat = [n for group in groups for n in group]
        if sorted(flat) != list(range(len(self.nodes))) or not groups or any(not group for group in groups):
            raise ValueError('partition must cover each node exactly once')
        for i in range(len(self.nodes)):
            for j in range(len(self.nodes)):
                self._links[i][j] = any(i in group and j in group for group in groups)
        self.elect()

    def heal(self) -> None:
        for row in self._links:
            row[:] = [True] * len(self.nodes)
        for node in self.nodes:
            if node.alive:
                node.log = self.committed.copy()
        self.elect()

    def invariants(self) -> dict[str, bool]:
        return {
            'prefix_safety': all(node.log == self.committed[:len(node.log)] for node in self.nodes),
            'quorum_receipts': len(self.receipts) == len(self.committed)
                               and all(len(ack) >= self.quorum and len(set(ack)) == len(ack) for ack in self.receipts),
            'no_uncommitted_ack': len(self.latencies_ns) == len(self.committed),
            'elected_leader_has_committed': self.leader is None or
                                            self.nodes[self.leader].log == self.committed,
            'symmetric_links': all(self._links[i][j] == self._links[j][i]
                                   for i in range(len(self.nodes)) for j in range(len(self.nodes))),
        }


def run_campaign(seed: int, rounds: int = 1000, nodes: int = 3) -> dict:
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**63:
        raise ValueError('invalid seed')
    if not isinstance(rounds, int) or not 0 <= rounds <= 100000:
        raise ValueError('invalid simulation rounds')
    twin = QuorumTwin(nodes, seed)
    rng = random.Random(seed ^ 0xC01DF00D)
    counts = {'append': 0, 'crash': 0, 'recover': 0, 'partition': 0, 'heal': 0, 'probe': 0}
    for seq in range(rounds):
        action = rng.randrange(100)
        if action < 60:
            counts['append'] += 1
            twin.append(f'event-{seq:06d}-{rng.getrandbits(32):08x}')
        elif action < 71:
            counts['crash'] += 1
            twin.crash(rng.randrange(nodes))
        elif action < 82:
            counts['recover'] += 1
            twin.recover(rng.randrange(nodes))
        elif action < 90:
            counts['partition'] += 1
            split = rng.randrange(1, nodes)
            ids = list(range(nodes))
            rng.shuffle(ids)
            twin.partition((tuple(ids[:split]), tuple(ids[split:])))
        elif action < 96:
            counts['heal'] += 1
            twin.heal()
        else:
            counts['probe'] += 1
        if not all(twin.invariants().values()):
            raise AssertionError(f'quorum safety violated at event {seq}')
    times = sorted(twin.latencies_ns)
    p99 = times[math.ceil(len(times) * .99) - 1] if times else None
    state = {'seed': seed, 'rounds': rounds, 'nodes': nodes, 'commits': len(twin.committed),
             'rejected_writes': twin.rejected, 'event_counts': counts,
             'synthetic_p99_ns': p99, 'invariants': twin.invariants(),
             'head_sha256': hashlib.sha256(json.dumps(twin.committed, separators=(',', ':')).encode()).hexdigest()}
    state['sha256'] = hashlib.sha256(json.dumps(state, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return state

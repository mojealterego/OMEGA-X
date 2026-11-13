"""Fault injection and replay as an explicit bounded discrete-event digital twin."""
import hashlib
import json
import random
from dataclasses import dataclass, asdict
from .resilience import CircuitBreaker, checkpoint, recover, retries

@dataclass(frozen=True)
class Event:
    at_ns: int
    node: int
    kind: str

class DeterministicTwin:
    def __init__(self, seed: int, nodes: int = 3):
        if not 1 <= nodes <= 32:
            raise ValueError('node count 1..32')
        self.rng = random.Random(seed)
        self.nodes = nodes
        self.seed = seed
        self.breakers = [CircuitBreaker(3, 2000000) for _ in range(nodes)]

    def run(self, rounds: int = 200) -> dict:
        if not 0 <= rounds <= 100000:
            raise ValueError('bounded rounds required')
        events = []
        successes = failures = rejected = 0
        for seq in range(rounds):
            now_ns = seq * 100000
            node = self.rng.randrange(self.nodes)
            breaker = self.breakers[node]
            if not breaker.allow(now_ns):
                rejected += 1
                events.append(Event(now_ns, node, 'circuit_reject'))
                continue
            failed = self.rng.random() < .12
            breaker.record(now_ns, not failed)
            failures += int(failed)
            successes += int(not failed)
            events.append(Event(now_ns, node, 'failed' if failed else 'success'))
        expected = rounds
        if successes + failures + rejected != expected:
            raise AssertionError('event conservation failed')
        state = {'seed': self.seed, 'events': [asdict(e) for e in events], 'successes': successes, 'failures': failures, 'rejected': rejected}
        blob = checkpoint(state)
        if recover(blob) != state:
            raise AssertionError('checkpoint replay failed')
        digest = hashlib.sha256(blob).hexdigest()
        return {'seed': self.seed, 'rounds': rounds, 'events': len(events), 'successes': successes,
                'failures': failures, 'rejected': rejected, 'state_hash': digest,
                'invariants': {'conservation': True, 'checkpoint_integrity': True,
                               'bounded_retries': len(retries(self.seed, 4)) == 4}}

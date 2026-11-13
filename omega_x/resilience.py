"""Deterministic circuit breaker, retries, idempotency and checkpoint recovery."""
from dataclasses import dataclass
import hashlib
import json
import random

@dataclass
class CircuitBreaker:
    threshold: int
    recovery_ns: int
    failures: int = 0
    reopen_ns: int = 0
    state: str = 'closed'
    probe_in_flight: bool = False

    def allow(self, now_ns: int) -> bool:
        if self.state == 'open' and now_ns >= self.reopen_ns:
            self.state = 'half-open'
            self.probe_in_flight = True
            return True
        if self.state == 'half-open':
            return False
        return self.state != 'open'

    def record(self, now_ns: int, success: bool) -> None:
        self.probe_in_flight = False
        if success:
            self.failures = 0
            self.state = 'closed'
            return
        self.failures += 1
        if self.state == 'half-open' or self.failures >= self.threshold:
            self.state = 'open'
            self.reopen_ns = now_ns + self.recovery_ns


def retries(seed: int, attempts: int, base_ns: int = 1000, cap_ns: int = 1_000_000) -> tuple[int, ...]:
    if not (0 < attempts <= 64 and base_ns > 0 and cap_ns >= base_ns):
        raise ValueError('invalid retry budget')
    rng = random.Random(seed)
    return tuple(rng.randint(0, min(cap_ns, base_ns * (2 ** i))) for i in range(attempts))


def checkpoint(state: dict) -> bytes:
    body = json.dumps(state, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    digest = hashlib.sha256(body).hexdigest()
    return json.dumps({'sha256': digest, 'payload': body.decode()}, sort_keys=True).encode()


def recover(blob: bytes) -> dict:
    record = json.loads(blob)
    data = record['payload'].encode()
    if hashlib.sha256(data).hexdigest() != record['sha256']:
        raise ValueError('checkpoint integrity failed')
    decoded = json.loads(data)
    if not isinstance(decoded, dict):
        raise ValueError('checkpoint must contain object')
    return decoded

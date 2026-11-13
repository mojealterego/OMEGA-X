"""Coherence-directory model and bounded zero-copy user-space transfer arena."""
from collections import OrderedDict
from dataclasses import dataclass
from .model import Profile

@dataclass(frozen=True)
class Transfer:
    bytes: int
    latency_ns: float
    bandwidth_bytes_per_ns: float

class Fabric:
    def __init__(self, profile: Profile):
        self.config = profile.data
        self.capacity = self.config['limits']['max_payload_bytes']
        self.arena = bytearray(self.capacity)
        self.head = 0
        self.snoop: OrderedDict[int, set[int]] = OrderedDict()
        self.snoop_capacity = 65536
        self.written = 0

    def put(self, data: bytes | bytearray | memoryview) -> tuple[memoryview, Transfer]:
        if not 0 < len(data) <= self.capacity:
            raise ValueError('payload beyond arena capacity')
        if self.head + len(data) > self.capacity:
            self.head = 0
        begin = self.head
        self.arena[begin:begin + len(data)] = data
        self.head += len(data)
        self.written += len(data)
        bandwidth = self.config['bandwidth_bytes_per_ns']['p_to_npu']
        return memoryview(self.arena)[begin:self.head], Transfer(len(data), 1.67 + len(data) / bandwidth, bandwidth)

    def register(self, addr: int, owner: int) -> None:
        if addr < 0 or owner < 0:
            raise ValueError('negative address/domain')
        entry = self.snoop.setdefault(addr // 64, set())
        entry.add(owner)
        self.snoop.move_to_end(addr // 64)
        if len(self.snoop) > self.snoop_capacity:
            self.snoop.popitem(last=False)

    def lookup(self, addr: int, requester: int) -> tuple[bool, float]:
        owners = self.snoop.get(addr // 64)
        if not owners:
            return False, 0.0
        return True, self.config['latency_ns']['peer_same' if requester in owners else 'peer_other']

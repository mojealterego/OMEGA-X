"""Bounded deterministic set-associative cache with strict domain way isolation."""
from collections import OrderedDict
from dataclasses import dataclass
from .model import Domain, Profile

class PartitionedCache:
    def __init__(self, capacity_bytes: int, ways: int, p_ways: int, line_bytes: int, max_resident_lines: int):
        if any(type(v) is not int for v in (capacity_bytes, ways, p_ways, line_bytes, max_resident_lines)):
            raise ValueError('invalid cache geometry types')
        if (ways < 2 or not 0 < p_ways < ways or line_bytes <= 0 or
                capacity_bytes < ways * line_bytes or capacity_bytes % (ways * line_bytes) or
                max_resident_lines < 2):
            raise ValueError('invalid cache partition geometry')
        self.set_count = capacity_bytes // (ways * line_bytes)
        self.line_bytes = line_bytes
        self.ways = {Domain.P: p_ways, Domain.E: ways - p_ways}
        self.max_entries = max_resident_lines
        # P-first admission: E insertions never evict resident P lines.
        # The shares below are modeling reference budgets, not strict occupancy ceilings;
        # unused capacity can be borrowed by either domain.
        p_quota = max(1, min(max_resident_lines - 1, max_resident_lines * p_ways // ways))
        self.quotas = {Domain.P: p_quota, Domain.E: max_resident_lines - p_quota}
        self.domain_lru = {Domain.P: OrderedDict(), Domain.E: OrderedDict()}
        self.entries: dict[tuple[int, Domain], OrderedDict[int, None]] = {}
        self.size = 0
        self.evictions = {Domain.P: 0, Domain.E: 0}
        self.clock = 0
        self.global_lru: OrderedDict[tuple[int, Domain, int], None] = OrderedDict()

    def _key(self, address: int, domain: Domain) -> tuple[int, Domain, int]:
        line = address // self.line_bytes
        return (line % self.set_count, domain, line // self.set_count)

    def access(self, address: int, domain: Domain, insert: bool = True) -> bool:
        if domain == Domain.NPU:
            domain = Domain.E
        set_id, domain, tag = self._key(address, domain)
        key = (set_id, domain, tag)
        section = self.entries.get((set_id, domain))
        if section is None and insert:
            section = self.entries.setdefault((set_id, domain), OrderedDict())
        if section is None:
            return False
        hit = tag in section
        if hit:
            section.move_to_end(tag)
            self.global_lru.move_to_end(key)
            self.domain_lru[domain].move_to_end(key)
        elif insert:
            section[tag] = None
            self.global_lru[key] = None
            self.domain_lru[domain][key] = None
            self.size += 1
            if len(section) > self.ways[domain]:
                evicted, _ = section.popitem(last=False)
                del self.global_lru[(set_id, domain, evicted)]
                del self.domain_lru[domain][(set_id, domain, evicted)]
                self.size -= 1
                self.evictions[domain] += 1
            while self.size > self.max_entries:
                # P can reclaim an E-borrowed line; background E may evict E only.
                victim_domain = (Domain.E if domain == Domain.P and self.domain_lru[Domain.E]
                                 else domain)
                (old_set, old_domain, old_tag), _ = self.domain_lru[victim_domain].popitem(last=False)
                self.global_lru.pop((old_set, old_domain, old_tag))
                self.entries[(old_set, old_domain)].pop(old_tag)
                self.size -= 1
                self.evictions[old_domain] += 1
        return hit

    def invariant(self) -> bool:
        return (self.size == len(self.global_lru)
                and self.size == sum(map(len, self.entries.values()))
                and self.size == sum(map(len, self.domain_lru.values()))
                and self.size <= self.max_entries
                and all(set(self.domain_lru[domain]).issubset(self.global_lru) for domain in self.quotas)
                and all(len(values) <= self.ways[domain]
                        for (_, domain), values in self.entries.items()))

class BoundedLRU:
    def __init__(self, lines: int):
        self.lines = lines
        self.entries: OrderedDict[int, None] = OrderedDict()

    def access(self, line: int) -> bool:
        hit = line in self.entries
        self.entries[line] = None
        self.entries.move_to_end(line)
        if len(self.entries) > self.lines:
            self.entries.popitem(last=False)
        return hit

@dataclass(frozen=True)
class Access:
    level: str
    latency_ns: float

class CacheHierarchy:
    def __init__(self, profile: Profile):
        c = profile.data['cache']
        self.latencies = profile.data['latency_ns']
        self.l3 = PartitionedCache(c['l3_bytes'], c['l3_ways'], c['p_ways'], c['line_bytes'], c['max_resident_lines'])
        self.l0: dict[int, BoundedLRU] = {}
        self.l1: dict[int, BoundedLRU] = {}
        self.l2: dict[int, BoundedLRU] = {}
        self.c = c
        self.stats = {key: 0 for key in ('l0', 'l1', 'l2', 'l3', 'dram')}

    def access(self, address: int, cpu_id: int, domain: Domain) -> Access:
        line = address // self.c['line_bytes']
        l0size = self.c['p_l0_bytes'] if domain == Domain.P else self.c['e_l0_bytes']
        l2size = self.c['p_l2_bytes'] if domain == Domain.P else self.c['e_l2_bytes']
        l0 = self.l0.setdefault(cpu_id, BoundedLRU(l0size // self.c['line_bytes']))
        l2 = self.l2.setdefault((domain, cpu_id if domain == Domain.P else cpu_id // 4), BoundedLRU(l2size // self.c['line_bytes']))
        if l0.access(line):
            level = 'l0'
        elif domain == Domain.P and self.l1.setdefault(cpu_id, BoundedLRU(self.c['p_l1_bytes'] // self.c['line_bytes'])).access(line):
            level = 'l1'
        elif l2.access(line):
            level = 'l2'
        elif self.l3.access(address, domain):
            level = 'l3'
        else:
            level = 'dram'
        self.stats[level] += 1
        return Access(level, self.latencies[level])

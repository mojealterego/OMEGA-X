"""Linux-only, read-only physical CPU topology. Virtual topology is never inferred as silicon.

Intel hybrid core_type: 1=Atom/E, 2=Core/P. Unknown/missing sysfs is unclassified.
Sibling information is not interpreted as evidence of processor family or AVX support.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
import os
from pathlib import Path

_VALID_KINDS = frozenset({'P', 'E', 'UNCLASSIFIED'})


@dataclass(frozen=True, slots=True)
class CPUDescriptor:
    cpu_id: int
    kind: str
    numa_node: int

    def __post_init__(self) -> None:
        if type(self.cpu_id) is not int or self.cpu_id < 0:
            raise ValueError('invalid CPU index')
        if self.kind not in _VALID_KINDS:
            raise ValueError('invalid physical CPU class')
        if type(self.numa_node) is not int or self.numa_node < 0:
            raise ValueError('invalid NUMA node')


@dataclass(frozen=True, slots=True)
class PhysicalTopology:
    cpus: tuple[CPUDescriptor, ...]

    def __post_init__(self) -> None:
        if not self.cpus or any(not isinstance(c, CPUDescriptor) for c in self.cpus):
            raise ValueError('CPU topology must be populated')
        if len({c.cpu_id for c in self.cpus}) != len(self.cpus):
            raise ValueError('duplicate physical CPU index')

    def to_dict(self) -> dict:
        return {'cpus': [asdict(c) for c in self.cpus],
                'hybrid_verified': bool({c.kind for c in self.cpus} >= {'P','E'}),
                'source': 'Linux sysfs topology/core_type; unknown classes are not guessed'}


def classify_cpu(*, core_type: int | None, capacity: int | None = None) -> str:
    """Never guess Intel P/E from frequencies or cpu_capacity; these are not ISA evidence."""
    if core_type == 1 and type(core_type) is int:
        return 'E'
    if core_type == 2 and type(core_type) is int:
        return 'P'
    return 'UNCLASSIFIED'


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding='ascii').strip())
    except (OSError, ValueError, UnicodeError):
        return None


def detect_topology(sys_root: str | Path = '/sys/devices/system/cpu') -> PhysicalTopology:
    if not hasattr(os, 'sched_getaffinity'):
        raise RuntimeError('CPU topology discovery requires Linux')
    root = Path(sys_root)
    cpus = []
    for cpu in sorted(os.sched_getaffinity(0)):
        cpu_dir = root / f'cpu{cpu}'
        kind = classify_cpu(core_type=_read_int(cpu_dir / 'topology/core_type'))
        node_ids = []
        try:
            for node in cpu_dir.glob('node[0-9]*'):
                try:
                    node_ids.append(int(node.name[4:]))
                except ValueError:
                    continue
        except OSError:
            pass
        cpus.append(CPUDescriptor(cpu, kind, min(node_ids) if node_ids else 0))
    return PhysicalTopology(tuple(cpus))

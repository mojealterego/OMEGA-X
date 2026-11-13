"""Read-only Linux host discovery; never mistake modeled CPU topology for real silicon."""
from dataclasses import dataclass, asdict
import os
import platform
from pathlib import Path


@dataclass(frozen=True, slots=True)
class HostCapabilities:
    architecture: str
    kernel: str
    allowed_cpus: tuple[int, ...]
    avx2: bool
    avx512: bool
    sched_ext_present: bool
    npu_devices: tuple[str, ...]
    cpu_models: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def detect_host() -> HostCapabilities:
    if not hasattr(os, 'sched_getaffinity'):
        raise RuntimeError('host affinity probe requires Linux')
    allowed = tuple(sorted(os.sched_getaffinity(0)))
    if not allowed:
        raise RuntimeError('no CPUs in process cpuset')
    cpuinfo = Path('/proc/cpuinfo')
    raw = cpuinfo.read_text(errors='replace') if cpuinfo.is_file() else ''
    flags = set()
    models = set()
    for line in raw.splitlines():
        if ':' not in line:
            continue
        key, value = (p.strip() for p in line.split(':', 1))
        if key in ('flags', 'Features'):
            flags.update(value.split())
        if key == 'model name':
            models.add(value)
    npu = tuple(sorted(str(p) for pattern in ('/dev/accel/accel*', '/dev/xdna*')
                       for p in __import__('glob').glob(pattern)))
    return HostCapabilities(platform.machine(), platform.release(), allowed,
                            'avx2' in flags, 'avx512f' in flags,
                            Path('/sys/kernel/sched_ext').exists(), npu, tuple(sorted(models)))


def select_cpu(host: HostCapabilities, cpu: int) -> int:
    if isinstance(cpu, bool) or not isinstance(cpu, int) or cpu not in host.allowed_cpus:
        raise ValueError('CPU outside permitted cpuset')
    return cpu

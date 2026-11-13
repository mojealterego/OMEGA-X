"""Read-only host capability admission for optional sched_ext source code."""
from __future__ import annotations
from pathlib import Path
import json
import platform
import shutil


def inspect_host(sys_path: Path = Path('/sys/kernel/sched_ext'),
                 btf_path: Path = Path('/sys/kernel/btf/vmlinux')) -> dict:
    capabilities = {
        'kernel': platform.release(),
        'sched_ext_sysfs': sys_path.is_dir(),
        'kernel_btf': btf_path.is_file(),
        'clang': shutil.which('clang') is not None,
        'bpftool': shutil.which('bpftool') is not None,
    }
    capabilities['status'] = ('SDK_AND_KERNEL_PROBE_ONLY' if all(
        capabilities[k] for k in ('sched_ext_sysfs','kernel_btf','clang','bpftool'))
        else 'UNAVAILABLE_FOR_KERNEL_RUNTIME_VALIDATION')
    capabilities['bpf_build_verified'] = False
    capabilities['kernel_attach_verified'] = False
    return capabilities


if __name__ == '__main__':
    print(json.dumps(inspect_host(), indent=2, sort_keys=True))

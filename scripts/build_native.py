"""Reproducible, offline native C11 compilation with local compiler; no downloads."""
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def build() -> Path:
    if platform.system() != 'Linux':
        raise RuntimeError('native build supports Linux; Python simulator remains portable')
    src = ROOT / 'native' / 'omega_native.c'
    out = ROOT / 'native' / 'libomegax.so'
    cmd = ['cc', '-std=c11', '-O3', '-fPIC', '-shared', '-Wall', '-Wextra', '-Werror', '-o', str(out), str(src), '-lm']
    subprocess.run(cmd, check=True, cwd=ROOT, timeout=60)
    return out

if __name__ == '__main__':
    print(build())

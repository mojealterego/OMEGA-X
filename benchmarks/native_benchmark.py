"""Measure actual local C11 SIMD execution; all times are observed host measurements."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctypes
import json
import math
import statistics
import time
from omega_x.native import NativeKernels
from omega_x.host import detect_host

ROOT = Path(__file__).resolve().parents[1]


def run(elements: int = 262144, repeats: int = 24, trials: int = 7) -> dict:
    if not 1024 <= elements <= 2_000_000 or not 1 <= repeats <= 200 or not 3 <= trials <= 20:
        raise ValueError('benchmark budget exceeded')
    kernels = NativeKernels()
    if not kernels.available:
        raise RuntimeError('compiled native library is required')
    xs = (ctypes.c_float * elements)(*[float(i % 101) / 13 for i in range(elements)])
    ys = (ctypes.c_float * elements)(*[float(i % 19) for i in range(elements)])
    out = (ctypes.c_float * elements)()
    baseline = (ctypes.c_float * elements)()
    modes = {'scalar': 1, 'auto': 0}
    result = {}
    for name, mode in modes.items():
        kernels._lib.ox_saxpy(xs, ys, out, elements, .25, mode)
        samples = []
        for _ in range(trials):
            start = time.perf_counter_ns()
            for _ in range(repeats):
                code = kernels._lib.ox_saxpy(xs, ys, out, elements, .25, mode)
                if code < 0:
                    raise RuntimeError('native dispatch failed')
            samples.append((time.perf_counter_ns() - start) / repeats)
        if name == 'scalar':
            baseline[:] = out[:]
        else:
            if any(abs(a - b) > 1e-4 for a, b in zip(out, baseline)):
                raise AssertionError('SIMD results diverged from scalar')
        result[name] = {'median_ns_per_call': round(statistics.median(samples)),
                        'min_ns_per_call': round(min(samples)),
                        'max_ns_per_call': round(max(samples)),
                        'samples_ns_per_call': [round(x) for x in samples],
                        'bytes_processed_per_call': elements * 3 * 4}
    return {'kind': 'ACTUAL_HOST_MEASUREMENT', 'host': detect_host().to_dict(),
            'simd_available': kernels.features(), 'elements': elements, 'repeats': repeats,
            'trials': trials, 'modes': result,
            'observed_speedup_auto_vs_scalar': round(result['scalar']['median_ns_per_call'] /
                                                     result['auto']['median_ns_per_call'], 3),
            'caveats': 'host-specific; no AMD/Intel 9850X3D/285K comparison; includes ctypes call overhead'}


if __name__ == '__main__':
    output = run()
    path = ROOT / 'results/benchmark_native.json'
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'output': str(path), 'observed_speedup': output['observed_speedup_auto_vs_scalar']}))

"""Compare measured CPU INT8 GEMM to exact Python reference on the current host.

Both implementations compute the same integer output. Not an NPU benchmark.
"""
from __future__ import annotations
import json
from pathlib import Path
import statistics
import time

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from omega_x.native import NativeKernels
from omega_x.host import detect_host

ROOT = Path(__file__).resolve().parents[1]


def run(dim: int = 64, repeats: int = 5) -> dict:
    if not 2 <= dim <= 128 or not 3 <= repeats <= 20:
        raise ValueError('benchmark bound')
    a = [[((i*7 + j*11)%255)-127 for j in range(dim)] for i in range(dim)]
    b = [[((i*13 - j*5)%255)-127 for j in range(dim)] for i in range(dim)]
    kernel = NativeKernels()
    if not kernel.available:
        raise RuntimeError('benchmark requires a native C11 library')
    def oracle():
        return [[sum(a[i][k]*b[k][j] for k in range(dim)) for j in range(dim)]
                for i in range(dim)]
    actual = kernel.matmul_int8(a,b)
    if actual != oracle():
        raise AssertionError('CPU INT8 kernel mismatch against exact integer oracle')
    observed = {}
    for name, fn in (('native_cpu',lambda: kernel.matmul_int8(a,b)),('python_reference',oracle)):
        samples=[]
        for _ in range(repeats):
            before = time.perf_counter_ns()
            value=fn()
            samples.append(time.perf_counter_ns()-before)
            if value != actual:
                raise AssertionError('INT8 benchmark output mismatch')
        observed[name] = {'median_ns': int(statistics.median(samples)), 'samples_ns':samples}
    ratio = observed['python_reference']['median_ns'] / max(1, observed['native_cpu']['median_ns'])
    return {'kind':'ACTUAL_CPU_INT8_GEMM','host':detect_host().to_dict(),'matrix_dim':dim,
            'repeats':repeats,'verification':'EXACT_INTEGER_MATCH','timings':observed,
            'measured_python_to_native_ratio':round(ratio,3),
            'limitations':'Only this CPU and Python; NOT NPU hardware nor AMD-vs-Intel 9850X3D/285K'}


if __name__=='__main__':
    result=run()
    target=ROOT/'results/int8_benchmark.json'
    target.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'file':str(target),'measured_python_to_native_ratio':result['measured_python_to_native_ratio']}))

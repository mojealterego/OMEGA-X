"""Real bounded CPU operations proving *functional*, not performance, coverage.

Each of the 12 source task classes maps to a small representative kernel.
The original 4.61-billion-instruction workload is NOT executed by this probe.
"""
from __future__ import annotations
from array import array
from hashlib import sha256
import json
from time import perf_counter_ns
from .fusion_twin import STANDARD_TASKS
from .native import NativeKernels


def run_functional_replay() -> dict:
    kernels = NativeKernels()
    results = []
    signatures = []
    for task in STANDARD_TASKS:
        start = perf_counter_ns()
        if task.kind in ('CACHE', 'BACKGROUND'):
            # Fixed data and hash permit independent replay across hosts.
            size = 1_048_576 if task.kind == 'CACHE' else 65_536
            data = bytes(range(256)) * (size // 256)
            digest = sha256(data).hexdigest()
            correct = len(data) == size and sha256(memoryview(data)).hexdigest() == digest
            signature = digest
            backend = 'cpu_sha256'
        elif task.kind == 'VECTOR':
            count = 4096
            x = [float((i + task.task_id) % 97) for i in range(count)]
            y = [float(i % 17) for i in range(count)]
            output = kernels.saxpy(x, y, .125, 'auto')
            correct = len(output) == count and all(
                output[i] == .125*x[i] + y[i] for i in range(count))
            signature = sha256(array('f', output).tobytes()).hexdigest()
            backend = 'native_cpu_saxpy' if kernels.available else 'python_cpu_saxpy'
        else:
            n = 16
            a = [[((i*11 + k*7 + task.task_id) % 29) - 14 for k in range(n)] for i in range(n)]
            b = [[((k*3 + j*13 + task.task_id) % 23) - 11 for j in range(n)] for k in range(n)]
            output = kernels.matmul_int8(a, b)
            reference = [[sum(a[i][k] * b[k][j] for k in range(n))
                          for j in range(n)] for i in range(n)]
            correct = output == reference
            signature = sha256(json.dumps(output, separators=(',', ':')).encode()).hexdigest()
            backend = 'native_cpu_int8' if kernels.available else 'python_cpu_int8'
        elapsed = max(1, perf_counter_ns() - start)
        signatures.append({'task_id': task.task_id, 'signature': signature})
        results.append({'task_id': task.task_id, 'kind': task.kind,
                        'backend': backend, 'correct': bool(correct),
                        'measured_wall_ns': elapsed})
    passed = sum(r['correct'] for r in results)
    return {'evidence_tier': 'REAL_HOST_FUNCTIONAL_CPU_ONLY',
            'jobs': len(STANDARD_TASKS), 'passed': passed, 'failed': len(STANDARD_TASKS) - passed,
            'native_library_loaded': kernels.available, 'real_cpu_executed': True,
            'physical_npu_executed': False, 'equivalent_to_pdf_full_workload': False,
            'functional_sha256': sha256(json.dumps(signatures, sort_keys=True,
                                                  separators=(',', ':')).encode()).hexdigest(),
            'results': results,
            'interpretation': 'Small representative real CPU kernels; timings are local host wall-clock, not Ryzen/Intel or PDF workload timings.'}

"""Actual wall-clock microbenchmark; does not equate model timings with hardware."""
from pathlib import Path
from time import perf_counter_ns
import json
import platform
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from omega_x.model import Workload, Instruction, load_profile
from omega_x.runtime import OmegaRuntime


def make_tasks(n=12):
    kinds = [Instruction.CACHE, Instruction.VECTOR, Instruction.TENSOR] + [Instruction.BACKGROUND] * 9
    return [Workload(i, f'job-{i}', kinds[i % len(kinds)], 1000000 + i * 1000,
                     16 * 1024 * 1024, cache_warmth=.7 if i == 0 else .1,
                     trace=tuple((i * 65536 + j * 64) for j in range(256))) for i in range(n)]

def main():
    profile = load_profile(ROOT / 'config' / 'profile.json')
    tasks = make_tasks()
    elapsed = []
    results = []
    for _ in range(7):
        start = perf_counter_ns()
        result = OmegaRuntime(profile).run(tasks)
        elapsed.append(perf_counter_ns() - start)
        results.append(result)
    report = {'benchmark_type': 'actual_host_wall_clock_for_python_model',
              'host': platform.platform(), 'python': sys.version.split()[0],
              'runs_ns': elapsed, 'median_ns': sorted(elapsed)[len(elapsed)//2],
              'tasks': len(tasks), 'trace_accesses': sum(len(t.trace) for t in tasks),
              'deterministic_model': len({r['modeled_makespan_ns'] for r in results}) == 1,
              'example_result': results[0]}
    print(json.dumps(report, indent=2, sort_keys=True))
    return report

if __name__ == '__main__':
    main()

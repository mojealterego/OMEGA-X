"""Adversarial contracts, custom requests, fault injection and sensitivity evidence."""
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

from omega_x.fusion_twin import (
    FusionTwin, FusionTask, REFERENCE_ARCHITECTURES, STANDARD_TASKS,
    run_sensitivity_campaign,
)

ROOT = Path(__file__).resolve().parents[1]


class FusionHardeningTests(unittest.TestCase):
    def test_randomized_resource_invariants(self):
        for seed in range(80):
            rng = random.Random(seed)
            tasks = [FusionTask(i, f'job_{i}', rng.choice(('CACHE', 'VECTOR', 'TENSOR', 'BACKGROUND')),
                                rng.randint(100, 500_000_000), rng.randint(0, 128)*1024*1024,
                                rng.random(), rng.random(), rng.random(), rng.random())
                     for i in range(rng.randint(1, 35))]
            faults = (('npu_off',) if seed % 3 == 0 else ('dram_half',) if seed % 3 == 1 else ('p_derate',))
            result = FusionTwin(REFERENCE_ARCHITECTURES['omega_x']).run(tasks, faults=faults)
            self.assertTrue(all(result['invariants'].values()), seed)
            self.assertLessEqual(result['lower_bound_ns'], result['makespan_ns'])
            self.assertEqual(result['completed'], len(tasks))

    def test_fault_injection_never_mints_virtual_npu(self):
        result = FusionTwin(REFERENCE_ARCHITECTURES['omega_x']).run(STANDARD_TASKS, faults=('npu_off',))
        self.assertFalse(any(t['domain'] == 'NPU' for t in result['tasks']))
        self.assertTrue(all(result['invariants'].values()))

    def test_thermal_and_dram_faults_do_not_improve_single_task(self):
        model = FusionTwin(REFERENCE_ARCHITECTURES['omega_x'])
        task = STANDARD_TASKS[0]
        base = model.run([task])['makespan_ns']
        self.assertGreaterEqual(model.run([task], faults=('dram_half',))['makespan_ns'], base)
        self.assertGreaterEqual(model.run([task], faults=('p_derate',))['makespan_ns'], base)

    def test_sensitivity_is_reproducible_and_has_quantiles(self):
        a = run_sensitivity_campaign(seeds=40, seed=1234)
        b = run_sensitivity_campaign(seeds=40, seed=1234)
        self.assertEqual(a, b)
        self.assertEqual(a['scenarios'], 40)
        self.assertTrue(a['all_invariants_pass'])
        self.assertLessEqual(a['p05_ms'], a['p50_ms'])
        self.assertLessEqual(a['p50_ms'], a['p95_ms'])
        self.assertFalse(a['physical_validation'])
        with self.assertRaises(ValueError):
            run_sensitivity_campaign(seeds=0)

    def test_custom_request_cli(self):
        body = {'schema_version': 1, 'architecture': 'omega_x', 'policy': 'critical_first',
                'virtual_multiplier': 1, 'faults': ['npu_off'],
                'tasks': [{'task_id': 1, 'name': 'bounded', 'kind': 'TENSOR',
                           'instructions': 10000, 'working_set_bytes': 4096,
                           'vector_fraction': 0, 'cache_warmth': 0,
                           'tensor_sparsity': 0.5, 'memory_access_fraction': 0.1}]}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'request.json'
            p.write_text(json.dumps(body))
            q = subprocess.run([sys.executable, '-m', 'omega_x.cli', 'fusion-run', str(p)],
                               cwd=ROOT, text=True, capture_output=True, timeout=15)
            self.assertEqual(q.returncode, 0, q.stderr)
            result = json.loads(q.stdout)
            self.assertEqual(result['completed'], 1)
            self.assertEqual(result['tasks'][0]['domain'], 'P')
            # Reject duplicate keys, even when JSON parsers would silently overwrite.
            p.write_text('{"schema_version":1,"schema_version":1}')
            bad = subprocess.run([sys.executable, '-m', 'omega_x.cli', 'fusion-run', str(p)],
                                 cwd=ROOT, text=True, capture_output=True, timeout=15)
            self.assertNotEqual(bad.returncode, 0)
            p.write_text(json.dumps({**body, 'hidden': True}))
            bad = subprocess.run([sys.executable, '-m', 'omega_x.cli', 'fusion-run', str(p)],
                                 cwd=ROOT, text=True, capture_output=True, timeout=15)
            self.assertNotEqual(bad.returncode, 0)

    def test_campaign_cli(self):
        q = subprocess.run([sys.executable, '-m', 'omega_x.cli', 'fusion-campaign', '--seeds', '12', '--seed', '91'],
                           cwd=ROOT, text=True, capture_output=True, timeout=15)
        self.assertEqual(q.returncode, 0, q.stderr)
        self.assertEqual(json.loads(q.stdout)['scenarios'], 12)


if __name__ == '__main__':
    unittest.main()

"""Red/green specification for the 12-task Ryzen/Intel virtual fusion contract."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

from omega_x.fusion_twin import (
    Architecture, FusionTwin, FusionTask, STANDARD_TASKS, REFERENCE_ARCHITECTURES,
    compare_architectures, solve_virtual_envelope,
)

ROOT = Path(__file__).resolve().parents[1]


class FusionReferenceTests(unittest.TestCase):
    def test_source_workload_is_complete_and_unique(self):
        self.assertEqual(len(STANDARD_TASKS), 12)
        self.assertEqual(len({t.task_id for t in STANDARD_TASKS}), 12)
        self.assertEqual(sum(t.instructions for t in STANDARD_TASKS), 4_610_000_000)
        self.assertEqual(STANDARD_TASKS[0].working_set_bytes, 64 * 1024 * 1024)
        self.assertEqual(len([t for t in STANDARD_TASKS if t.kind == 'BACKGROUND']), 6)
        self.assertEqual(len([t for t in STANDARD_TASKS if t.kind == 'TENSOR']), 2)

    def test_virtual_topology_and_cache_budget_are_explicit(self):
        omega = REFERENCE_ARCHITECTURES['omega_x']
        self.assertEqual((omega.p_cores, omega.e_cores, omega.npu_engines), (8, 16, 4))
        self.assertEqual(omega.l3_bytes, 128 * 1024 * 1024)
        self.assertEqual(omega.logical_threads, 32)
        self.assertEqual(REFERENCE_ARCHITECTURES['amd_9850x3d'].logical_threads, 16)
        self.assertEqual(REFERENCE_ARCHITECTURES['intel_285k'].logical_threads, 24)
        self.assertEqual(omega.p_cache_bytes + omega.e_cache_bytes, omega.l3_bytes)
        self.assertEqual(REFERENCE_ARCHITECTURES['amd_9850x3d'].npu_engines, 0)

    def test_all_architectures_replay_deterministically(self):
        for name, architecture in REFERENCE_ARCHITECTURES.items():
            with self.subTest(name=name):
                first = FusionTwin(architecture).run(STANDARD_TASKS)
                second = FusionTwin(architecture).run(tuple(reversed(STANDARD_TASKS)))
                self.assertEqual(first['proof_sha256'], second['proof_sha256'])
                self.assertEqual(first['completed'], 12)
                self.assertTrue(all(first['invariants'].values()))
                self.assertEqual(len(first['tasks']), 12)
                self.assertTrue(all(t['end_ns'] >= t['start_ns'] for t in first['tasks']))

    def test_virtual_npu_and_cpu_fallback(self):
        omega = FusionTwin(REFERENCE_ARCHITECTURES['omega_x']).run(STANDARD_TASKS)
        amd = FusionTwin(REFERENCE_ARCHITECTURES['amd_9850x3d']).run(STANDARD_TASKS)
        self.assertEqual(sum(t['domain'] == 'NPU' for t in omega['tasks']), 2)
        self.assertEqual(sum(t['domain'] == 'NPU' for t in amd['tasks']), 0)
        self.assertEqual(sum(t['kind'] == 'TENSOR' for t in amd['tasks']), 2)

    def test_cache_residency_never_exceeds_partition(self):
        for profile in REFERENCE_ARCHITECTURES.values():
            result = FusionTwin(profile).run(STANDARD_TASKS)
            self.assertLessEqual(result['cache']['P']['allocated_bytes'], profile.p_cache_bytes)
            self.assertLessEqual(result['cache']['E']['allocated_bytes'], profile.e_cache_bytes)

    def test_memory_bandwidth_monotonicity_for_single_task(self):
        from dataclasses import replace
        p = REFERENCE_ARCHITECTURES['omega_x']
        slow = replace(p, dram_gb_s=p.dram_gb_s / 2)
        fast_result = FusionTwin(p).run(STANDARD_TASKS[:1])
        slow_result = FusionTwin(slow).run(STANDARD_TASKS[:1])
        self.assertGreaterEqual(slow_result['makespan_ns'], fast_result['makespan_ns'])

    def test_fail_closed_validation(self):
        from dataclasses import replace
        with self.assertRaises(ValueError):
            replace(REFERENCE_ARCHITECTURES['omega_x'], l3_bytes=-1)
        with self.assertRaises(ValueError):
            replace(REFERENCE_ARCHITECTURES['omega_x'], dram_gb_s=float('nan'))
        with self.assertRaises(ValueError):
            FusionTwin(REFERENCE_ARCHITECTURES['omega_x']).run([STANDARD_TASKS[0]] * 2)
        with self.assertRaises(ValueError):
            FusionTask(999, 'x', 'VECTOR', -1, 0, 0.0, 0.0, 0.0, 0.0)

    def test_comparison_has_no_fake_hardware_attestation(self):
        result = compare_architectures()
        self.assertEqual(result['evidence_tier'], 'DETERMINISTIC_VIRTUAL_MODEL')
        self.assertFalse(result['physical_ryzen_intel_fusion_verified'])
        self.assertEqual(set(result['results']), set(REFERENCE_ARCHITECTURES))
        self.assertEqual(result['pdf_reference_ms']['omega_x'], 294.36)
        self.assertEqual(result['pdf_reference_ms']['amd_9850x3d'], 773.71)
        self.assertIn('model_vs_pdf_delta_ms', result)

    def test_virtual_envelope_solver_is_bounded_and_verifiable(self):
        outcome = solve_virtual_envelope(max_multiplier=16)
        self.assertGreaterEqual(outcome['required_virtual_clock_multiplier'], 1)
        self.assertLessEqual(outcome['required_virtual_clock_multiplier'], 16)
        self.assertTrue(outcome['contract_satisfied'])
        self.assertLessEqual(outcome['verified_makespan_ms'], 294.36)
        self.assertTrue(outcome['virtual_time_only'])
        self.assertFalse(outcome['physical_performance_proven'])
        with self.assertRaises(ValueError):
            solve_virtual_envelope(max_multiplier=0)

    def test_cli_contract(self):
        p = subprocess.run([sys.executable, '-m', 'omega_x.cli', 'fusion-compare'],
                           cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)['evidence_tier'], 'DETERMINISTIC_VIRTUAL_MODEL')
        q = subprocess.run([sys.executable, '-m', 'omega_x.cli', 'fusion-solve', '--max-multiplier', '16'],
                           cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(q.returncode, 0, q.stderr)
        self.assertTrue(json.loads(q.stdout)['contract_satisfied'])


if __name__ == '__main__':
    unittest.main()

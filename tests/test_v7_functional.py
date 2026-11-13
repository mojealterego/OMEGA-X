"""Bounded real CPU validation for the four virtual workload classes."""
import json
import subprocess
import sys
from pathlib import Path
import unittest
from omega_x.fusion_functional import run_functional_replay

ROOT = Path(__file__).resolve().parents[1]

class FunctionalReplayTests(unittest.TestCase):
    def test_12_workload_classes_have_real_cpu_reference_checks(self):
        a = run_functional_replay()
        b = run_functional_replay()
        self.assertEqual(a['jobs'], 12)
        self.assertEqual(a['passed'], 12)
        self.assertEqual(a['failed'], 0)
        self.assertEqual(a['functional_sha256'], b['functional_sha256'])
        self.assertTrue(all(x['correct'] and x['measured_wall_ns'] > 0 for x in a['results']))
        self.assertTrue(a['real_cpu_executed'])
        self.assertFalse(a['physical_npu_executed'])
        self.assertFalse(a['equivalent_to_pdf_full_workload'])

    def test_cli_functional_replay(self):
        p = subprocess.run([sys.executable, '-m', 'omega_x.cli', 'fusion-functional'],
                           cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)['passed'], 12)

if __name__ == '__main__':
    unittest.main()

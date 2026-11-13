"""Reference PDF-derived twelve-task simulation, without fabricated speedup claims."""
from pathlib import Path
import json
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestStandardSuite(unittest.TestCase):
    def test_all_twelve_tasks_and_cache_invariants(self):
        p = subprocess.run([sys.executable, '-m', 'omega_x.cli', 'run', 'examples/standard_12_tasks.json'],
                           cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(p.returncode, 0, p.stderr)
        result = json.loads(p.stdout)
        self.assertEqual(result['tasks'], 12)
        self.assertTrue(all(result['invariants'].values()))
        self.assertEqual(len({p['task_id'] for p in result['placements']}), 12)
        self.assertEqual(result['interpretation'], 'DETERMINISTIC_SIMULATION_ONLY')

if __name__ == '__main__':
    unittest.main()

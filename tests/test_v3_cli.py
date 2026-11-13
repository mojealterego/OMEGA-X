"""Subprocess acceptance for newly exposed physical execution interfaces."""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, '-m', 'omega_x.cli', *args], cwd=ROOT,
                          text=True, capture_output=True, timeout=30)


class TestV3Cli(unittest.TestCase):
    def test_host_topology_returns_actual_cpu_list(self):
        out = cli('host-topology')
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)
        self.assertGreater(len(data['cpus']), 0)
        self.assertIn('hybrid_verified', data)

    def test_actual_int8_gemm_by_cli(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'matrix.json'
            path.write_text(json.dumps({'left': [[2,-3]], 'right': [[4],[-2]]}))
            out = cli('matmul-int8', str(path))
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(json.loads(out.stdout)['matrix'], [[14]])
            self.assertEqual(json.loads(out.stdout)['compute_device'], 'CPU')

    def test_physical_plan_from_existing_v1_workload(self):
        out = cli('physical-plan', 'examples/request.json')
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)
        self.assertTrue(data['plan'])
        self.assertEqual(data['mode'],'real_cpu_affinity_proposal')

    def test_bounded_real_batch_via_cli(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'req.json'
            path.write_text(json.dumps({'requests':[{'kind':'sha256','size':1024},
                                                        {'kind':'memory','size':4096}]}))
            out = cli('execute-batch',str(path),'--workers','2')
            self.assertEqual(out.returncode,0,out.stderr)
            actual = json.loads(out.stdout)
            self.assertEqual([r['status'] for r in actual],['ok','ok'])
            self.assertTrue(all(r['measured'] for r in actual))

    def test_unsafe_action_or_batch_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'req.json'
            path.write_text(json.dumps({'requests':[{'kind':'shell','size':10}]}))
            result = cli('execute-batch',str(path))
            self.assertNotEqual(result.returncode,0)
            self.assertNotIn('Traceback',result.stderr)

if __name__=='__main__':
    unittest.main()

"""Real end-to-end subprocess contract checks for the version 2 CLI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from omega_x.bridge_v2 import sign_request
from omega_x.model import Workload, Instruction

ROOT = Path(__file__).resolve().parents[1]


def invoke(*args, env=None):
    return subprocess.run([sys.executable, '-m', 'omega_x.cli', *args],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)


class TestCLI(unittest.TestCase):
    def test_host_and_replicate_subprocess(self):
        host = invoke('host')
        self.assertEqual(host.returncode, 0, host.stderr)
        self.assertGreater(len(json.loads(host.stdout)['allowed_cpus']), 0)
        sim = invoke('replicate', '--seed', '7', '--rounds', '100', '--nodes', '3')
        self.assertEqual(sim.returncode, 0, sim.stderr)
        self.assertTrue(all(json.loads(sim.stdout)['invariants'].values()))

    def test_actual_cpu_subprocess(self):
        proc = invoke('execute', '--kind', 'sha256', '--size', '4096')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['status'], 'ok')

    def test_authenticated_bridge_replay_rejected(self):
        env = dict(os.environ, OMEGA_X_HMAC_KEY_HEX=(b'Z' * 32).hex(), OMEGA_X_TEST_MODE='1')
        req = ROOT / 'results/tmp/signed_e2e.json'
        req.parent.mkdir(parents=True, exist_ok=True)
        req.write_bytes(sign_request([Workload(1, 'one', Instruction.SCALAR, 10, 64)],
                                     'cli-e2e', 'tenant1', b'Z' * 32, 100, 10000, nonce='c' * 32))
        for path in ('results/bridge_evidence.sqlite3', 'results/bridge_replay.sqlite3'):
            for suffix in ('', '-wal', '-shm'):
                (ROOT / (path + suffix)).unlink(missing_ok=True)
        first = invoke('run-signed', str(req), '--now-ns', '101', env=env)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout)['tenant'], 'tenant1')
        again = invoke('run-signed', str(req), '--now-ns', '101', env=env)
        self.assertNotEqual(again.returncode, 0)
        self.assertIn('replay', again.stderr.lower())

if __name__ == '__main__':
    unittest.main()

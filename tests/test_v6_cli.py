"""End-to-end CLI contracts for new offline diagnostics and evidence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def cli(*args, env=None):
    return subprocess.run([sys.executable, '-m', 'omega_x.cli', *args],
                          cwd=ROOT, capture_output=True, text=True, timeout=30, env=env)


class V6CLITests(unittest.TestCase):
    def test_state_explorer_cli(self):
        result = cli('coherence-explore', '--depth', '3', '--nodes', '2')
        self.assertEqual(result.returncode, 0, result.stderr)
        body = json.loads(result.stdout)
        self.assertTrue(body['all_invariants_pass'])
        self.assertEqual(body['depth'], 3)

    def test_policy_explorer_cli(self):
        result = cli('policy-evaluate', '--seed', '3', '--scenarios', '4', '--jobs', '16')
        self.assertEqual(result.returncode, 0, result.stderr)
        body = json.loads(result.stdout)
        self.assertEqual(len(body['cases']), 4)
        self.assertTrue(body['guardrails_passed'])
        self.assertFalse(body['auto_deployment'])

    def test_proof_stream_cli(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            event = p/'event.json'
            event.write_text('{"kind":"TEST","payload":{"n":4}}')
            os.chmod(td, 0o700)
            env = dict(os.environ, OMEGA_X_PROOF_KEY_HEX='42'*32)
            create = cli('proof-append', str(p/'events.jsonl'), str(event), env=env)
            self.assertEqual(create.returncode, 0, create.stderr)
            entry = json.loads(create.stdout)
            self.assertEqual(entry['sequence'], 1)
            verify = cli('proof-verify', str(p/'events.jsonl'), '--head', entry['head'], env=env)
            self.assertEqual(verify.returncode, 0, verify.stderr)
            self.assertEqual(json.loads(verify.stdout)['count'], 1)
            env['OMEGA_X_PROOF_KEY_HEX'] = '43'*32
            bad = cli('proof-verify', str(p/'events.jsonl'), env=env)
            self.assertEqual(bad.returncode, 2)

    def test_proof_no_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ)
            env.pop('OMEGA_X_PROOF_KEY_HEX', None)
            result = cli('proof-verify', str(Path(td)/'events.jsonl'), env=env)
            self.assertEqual(result.returncode, 2)

if __name__ == '__main__':
    unittest.main()

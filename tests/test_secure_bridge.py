"""Contract and security tests for the offline Digital-Life bridge v2."""
from pathlib import Path
import json
import unittest
from omega_x.bridge_v2 import sign_request, verify_request, ReplayStore, AuthenticationError
from omega_x.model import Workload, Instruction

ROOT = Path(__file__).resolve().parents[1]
KEY = b'K' * 32
TASKS = [Workload(12, 'test', Instruction.SCALAR, 100, 1024)]


class TestSignedBridge(unittest.TestCase):
    def test_roundtrip_and_integrity(self):
        blob = sign_request(TASKS, 'req-1', 'tenant-A', KEY, issued_ns=1000, ttl_ns=1000000, nonce='a' * 32)
        tenant, req, tasks, nonce = verify_request(blob, KEY, now_ns=1001)
        self.assertEqual((tenant, req, nonce), ('tenant-A', 'req-1', 'a' * 32))
        self.assertEqual(tasks, TASKS)

    def test_tampered_signature_wrong_tenant_and_expiration_rejected(self):
        blob = sign_request(TASKS, 'req-1', 'tenant-A', KEY, issued_ns=1000, ttl_ns=1000, nonce='b' * 32)
        data = json.loads(blob)
        data['tenant'] = 'tenant-B'
        with self.assertRaises(AuthenticationError):
            verify_request(json.dumps(data).encode(), KEY, now_ns=1001)
        with self.assertRaises(AuthenticationError):
            verify_request(blob, b'Q' * 32, now_ns=1001)
        with self.assertRaises(AuthenticationError):
            verify_request(blob, KEY, now_ns=2001)

    def test_replay_store_rejects_nonce_reuse_across_processes(self):
        db = ROOT / 'results/tmp/replay_test.sqlite3'
        for suffix in ('', '-wal', '-shm'):
            (ROOT / ('results/tmp/replay_test.sqlite3' + suffix)).unlink(missing_ok=True)
        with ReplayStore(db) as store:
            self.assertTrue(store.claim('tenant-A', 'a' * 32, expires_ns=10000, now_ns=1000))
            self.assertFalse(store.claim('tenant-A', 'a' * 32, expires_ns=10000, now_ns=1000))
            self.assertTrue(store.claim('tenant-B', 'a' * 32, expires_ns=10000, now_ns=1000))
            self.assertTrue(store.claim('tenant-A', 'a' * 32, expires_ns=20000, now_ns=10001))

    def test_weak_key_invalid_tenant_and_invalid_nonce_rejected(self):
        for key, tenant, nonce in ((b'bad', 'ok', 'a' * 32), (KEY, '../bad', 'a' * 32), (KEY, 'ok', 'x')):
            with self.assertRaises(ValueError):
                sign_request(TASKS, 'r', tenant, key, issued_ns=0, ttl_ns=1000, nonce=nonce)

if __name__ == '__main__':
    unittest.main()

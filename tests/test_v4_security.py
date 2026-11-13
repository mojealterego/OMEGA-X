"""Concurrency, persistence, and secret-handling regression tests."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sqlite3
from contextlib import closing
import stat
import tempfile
import unittest

from omega_x.job_store import JobStore
from omega_x.service import create_keys, load_keys


class SecurityTests(unittest.TestCase):
    def test_database_created_owner_only(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'private'/'jobs.sqlite3'
            store=JobStore(path)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode),0o700)
            self.assertTrue(store.integrity())

    def test_concurrent_same_idempotency_key_yields_one_job(self):
        with tempfile.TemporaryDirectory() as root:
            store=JobStore(Path(root)/'jobs.db')
            request={'kind':'sha256','size':1000,'cpu':None,'timeout_s':2.0,'priority':'normal'}
            with ThreadPoolExecutor(max_workers=12) as pool:
                results=list(pool.map(lambda _:store.submit('alpha','same',request),range(24)))
            self.assertEqual(len({x['job_id'] for x in results}),1)
            self.assertEqual(store.metrics('alpha')['total'],1)

    def test_crash_recovery_exhausted_attempts_is_terminal(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'jobs.db'
            store=JobStore(path)
            req={'kind':'sha256','size':1,'cpu':None,'timeout_s':1.0,'priority':'normal'}
            job=store.submit('alpha','one',req,now_ns=1000)
            for i in range(3):
                claimed=store.claim_next(1000+i)
                self.assertIsNotNone(claimed)
                self.assertEqual(store.recover(1000+i),1)
            self.assertEqual(store.get('alpha',job['job_id'])['status'],'FAILED')
            self.assertIsNone(store.claim_next(9999))

    def test_secret_file_rejects_duplicate_tenant_and_key(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'keys.json'
            with self.assertRaises(ValueError):
                create_keys(path,['alpha','alpha'])
            path.write_text('{"tenants":{"alpha":"'+'ab'*32+'","beta":"'+'ab'*32+'"}}')
            path.chmod(0o600)
            with self.assertRaises(ValueError):
                load_keys(path)


if __name__ == '__main__':
    unittest.main()

class FailClosedStartupTests(unittest.TestCase):
    def test_compromised_audit_blocks_service_start(self):
        from omega_x.service import LocalControlPlane
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'jobs.db'
            store=JobStore(path)
            req={'kind':'sha256','size':1,'cpu':None,'timeout_s':1.0,'priority':'normal'}
            store.submit('alpha','one',req)
            with closing(sqlite3.connect(path)) as db:
                db.execute("UPDATE journal SET event='BAD' WHERE seq=1")
                db.commit()
            plane=LocalControlPlane(path, {'alpha': bytes.fromhex('aa'*32)},workers=1)
            try:
                with self.assertRaises(RuntimeError):
                    plane.start()
            finally:
                plane.stop()

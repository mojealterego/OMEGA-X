"""Tamper-evident state transition journal, with independent mutation checks."""
from pathlib import Path
import sqlite3
from contextlib import closing
import tempfile
import unittest

from omega_x.job_store import JobStore


class AuditTests(unittest.TestCase):
    def test_journal_covers_all_transitions_and_detects_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'jobs.db'
            store=JobStore(path)
            req={'kind':'sha256','size':2,'cpu':None,'timeout_s':1.0,'priority':'normal'}
            job=store.submit('alpha','x',req,now_ns=1000)
            store.claim_next(1001)
            store.fail(job['job_id'],'WORKER_ERROR',1002)
            retry=store.get('alpha',job['job_id'])['not_before_ns']
            store.claim_next(retry)
            store.complete(job['job_id'],{'status':'ok'},retry+1)
            self.assertTrue(store.integrity())
            with closing(sqlite3.connect(path)) as db:
                events=[row[0] for row in db.execute('SELECT event FROM journal ORDER BY seq')]
            self.assertEqual(events,['SUBMITTED','CLAIMED','RETRY','CLAIMED','SUCCEEDED'])
            with closing(sqlite3.connect(path)) as db:
                db.execute("UPDATE journal SET event='COMPROMISED' WHERE seq=3")
                db.commit()
            self.assertFalse(store.integrity())

    def test_journal_detects_truncated_history(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'jobs.db'
            store=JobStore(path)
            req={'kind':'sha256','size':2,'cpu':None,'timeout_s':1.0,'priority':'normal'}
            store.submit('alpha','x',req)
            store.submit('alpha','y',req)
            self.assertTrue(store.integrity())
            with closing(sqlite3.connect(path)) as db:
                db.execute('DELETE FROM journal WHERE seq=1')
                db.commit()
            self.assertFalse(store.integrity())


if __name__=='__main__':
    unittest.main()

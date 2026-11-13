"""Contract-first tests for the durable multi-tenant job engine."""
import tempfile
from pathlib import Path
import unittest

from omega_x.job_store import JobStore, Conflict, CapacityExceeded


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.tmp.name) / 'jobs.sqlite3', max_pending=4, max_per_tenant=2)
        self.clock = 1_800_000_000_000_000_000

    def tearDown(self):
        self.tmp.cleanup()

    def submit(self, tenant='alpha', key='key1', kind='sha256', size=1000, priority='normal'):
        return self.store.submit(tenant, key, {'kind': kind, 'size': size, 'cpu': None,
                                                'timeout_s': 2.0, 'priority': priority}, now_ns=self.clock)

    def test_idempotent_submission_and_conflicting_payload(self):
        a = self.submit()
        b = self.submit()
        self.assertEqual(a['job_id'], b['job_id'])
        self.assertEqual(a['status'], 'QUEUED')
        with self.assertRaises(Conflict):
            self.submit(size=1001)
        self.assertEqual(self.store.metrics('alpha')['total'], 1)

    def test_tenant_scoped_access_and_bounded_capacity(self):
        job = self.submit()
        self.assertIsNone(self.store.get('beta', job['job_id']))
        self.submit(key='key2')
        with self.assertRaises(CapacityExceeded):
            self.submit(key='key3')
        self.submit(tenant='beta', key='key1')
        self.submit(tenant='beta', key='key2')
        with self.assertRaises(CapacityExceeded):
            self.submit(tenant='gamma', key='key1')

    def test_round_robin_fairness_across_tenants(self):
        self.submit(tenant='alpha', key='a1')
        self.submit(tenant='alpha', key='a2')
        self.submit(tenant='beta', key='b1')
        self.submit(tenant='beta', key='b2')
        names = [self.store.claim_next(self.clock)['tenant'] for _ in range(4)]
        self.assertEqual(names, ['alpha', 'beta', 'alpha', 'beta'])

    def test_atomic_completion_and_terminal_state(self):
        job = self.submit()
        claimed = self.store.claim_next(self.clock)
        self.assertEqual(claimed['attempts'], 1)
        self.assertTrue(self.store.complete(job['job_id'], {'status': 'ok', 'digest': '123'}, self.clock+1))
        self.assertFalse(self.store.complete(job['job_id'], {'status': 'ok'}, self.clock+2))
        self.assertEqual(self.store.get('alpha', job['job_id'])['result']['digest'], '123')
        self.assertEqual(self.store.metrics('alpha')['SUCCEEDED'], 1)

    def test_failure_backoff_is_deterministic_and_terminal(self):
        job = self.submit()
        self.store.claim_next(self.clock)
        self.store.fail(job['job_id'], 'WORKER_ERROR', self.clock)
        record = self.store.get('alpha', job['job_id'])
        self.assertEqual(record['status'], 'QUEUED')
        self.assertGreater(record['not_before_ns'], self.clock)
        self.assertIsNone(self.store.claim_next(self.clock))
        self.assertIsNotNone(self.store.claim_next(record['not_before_ns']))
        self.store.fail(job['job_id'], 'WORKER_ERROR', record['not_before_ns'])
        second = self.store.get('alpha', job['job_id'])
        self.assertGreater(second['not_before_ns'] - record['not_before_ns'], 0)
        self.store.claim_next(second['not_before_ns'])
        self.store.fail(job['job_id'], 'WORKER_ERROR', second['not_before_ns'])
        self.assertEqual(self.store.get('alpha', job['job_id'])['status'], 'FAILED')

    def test_recovery_after_crash_and_cancellation(self):
        job = self.submit()
        self.store.claim_next(self.clock)
        self.assertEqual(self.store.recover(self.clock+1), 1)
        self.assertEqual(self.store.get('alpha', job['job_id'])['status'], 'QUEUED')
        self.assertEqual(self.store.recover(self.clock+2), 0)
        self.assertTrue(self.store.cancel('alpha', job['job_id'], self.clock+3))
        self.assertFalse(self.store.cancel('alpha', job['job_id'], self.clock+4))
        self.assertIsNone(self.store.claim_next(self.clock+5))

    def test_rejects_invalid_inputs_and_sql_metacharacters(self):
        for tenant in ('', '../x', 'alpha;DROP TABLE jobs', 'ä', 'a'*65):
            with self.subTest(tenant=tenant), self.assertRaises(ValueError):
                self.submit(tenant=tenant)
        for key in ('', 'x'*129, 'x\nabc'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.submit(key=key)
        with self.assertRaises(ValueError):
            self.submit(priority='root')


if __name__ == '__main__':
    unittest.main()

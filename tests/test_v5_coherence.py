"""Safety-first mathematical invariants for an unavailable CXL-like coherence island."""
import unittest
from omega_x.coherence_twin import CoherenceTwin, CoherenceUnavailable, StaleLease, run_coherence_campaign


class CoherenceContract(unittest.TestCase):
    def setUp(self):
        self.fabric = CoherenceTwin(nodes=3, directory_capacity=16)

    def test_exclusive_write_invalidates_all_sharers(self):
        a = self.fabric.acquire_shared(0, 12)
        b = self.fabric.acquire_shared(1, 12)
        self.assertEqual(self.fabric.read(a), self.fabric.read(b))
        lease = self.fabric.acquire_exclusive(2, 12)
        version = self.fabric.write(lease, 981)
        self.assertGreater(version, 0)
        with self.assertRaises(StaleLease):
            self.fabric.read(a)
        self.assertEqual(self.fabric.read(self.fabric.acquire_shared(0, 12)), 981)
        self.assertTrue(all(self.fabric.invariants().values()))

    def test_separated_sharer_blocks_write_fail_closed(self):
        self.fabric.acquire_shared(0, 1)
        self.fabric.acquire_shared(1, 1)
        self.fabric.partition(((0, 2), (1,)))
        with self.assertRaises(CoherenceUnavailable):
            self.fabric.acquire_exclusive(0, 1)
        self.assertTrue(all(self.fabric.invariants().values()))

    def test_reconnect_and_fencing(self):
        lease = self.fabric.acquire_exclusive(0, 1)
        self.fabric.write(lease, 101)
        self.fabric.restart()
        with self.assertRaises(StaleLease):
            self.fabric.read(lease)
        self.assertEqual(self.fabric.read(self.fabric.acquire_shared(2, 1)), 101)
        self.assertTrue(all(self.fabric.invariants().values()))

    def test_partition_remains_safe_when_owner_unreachable(self):
        lease = self.fabric.acquire_exclusive(0, 5)
        self.fabric.write(lease, 77)
        self.fabric.partition(((0,), (1, 2)))
        with self.assertRaises(CoherenceUnavailable):
            self.fabric.acquire_shared(1, 5)
        self.fabric.heal()
        self.assertEqual(self.fabric.read(self.fabric.acquire_shared(1, 5)), 77)

    def test_two_exclusive_holders_never_coexist(self):
        first = self.fabric.acquire_exclusive(0, 0)
        second = self.fabric.acquire_exclusive(1, 0)
        with self.assertRaises(StaleLease):
            self.fabric.write(first, 1)
        self.fabric.write(second, 2)
        self.assertTrue(all(self.fabric.invariants().values()))

    def test_directory_bounded_with_safe_eviction(self):
        co = CoherenceTwin(nodes=3, directory_capacity=4)
        for n in range(200):
            lease = co.acquire_exclusive(n % 3, n)
            co.write(lease, n)
            self.assertLessEqual(co.directory_size, 4)
            self.assertTrue(all(co.invariants().values()))
        self.assertEqual(co.read(co.acquire_shared(2, 0)), 0)
        self.assertEqual(co.read(co.acquire_shared(2, 199)), 199)

    def test_directory_eviction_requires_remote_invalidation_ack(self):
        co = CoherenceTwin(nodes=3, directory_capacity=1)
        lease = co.acquire_exclusive(0, 1)
        co.write(lease, 42)
        co.partition(((0,), (1, 2)))
        with self.assertRaises(CoherenceUnavailable):
            co.acquire_shared(1, 2)
        self.assertEqual(co.directory_size, 1)
        self.assertTrue(all(co.invariants().values()))
        co.heal()
        self.assertEqual(co.read(co.acquire_shared(1, 1)), 42)

    def test_invalid_domain_address_and_payloads(self):
        for action in (lambda: self.fabric.acquire_shared(-1, 0),
                       lambda: self.fabric.acquire_shared(3, 0),
                       lambda: self.fabric.acquire_shared(1, -1),
                       lambda: self.fabric.partition(((0, 1), (1, 2))),
                       lambda: CoherenceTwin(nodes=1)):
            with self.assertRaises(ValueError):
                action()
        lease = self.fabric.acquire_exclusive(0, 1)
        with self.assertRaises(ValueError):
            self.fabric.write(lease, True)

    def test_coherence_fault_campaign_deterministic(self):
        first = run_coherence_campaign(seeds=40, rounds=120, base_seed=1805)
        self.assertEqual(first, run_coherence_campaign(seeds=40, rounds=120, base_seed=1805))
        self.assertEqual(first['events'], 4800)
        self.assertTrue(first['all_invariants_pass'])
        self.assertGreater(first['fail_closed_rejections'], 0)
        self.assertEqual(len(first['campaign_sha256']), 64)

    def test_partition_audit_and_replay(self):
        self.fabric.acquire_shared(0, 1)
        self.fabric.acquire_shared(1, 1)
        self.fabric.acquire_exclusive(2, 1)
        state = self.fabric.report()
        self.assertEqual(state, self.fabric.report())
        self.assertEqual(len(state['proof_sha256']), 64)
        self.assertGreater(state['snoop_messages'], 0)
        self.assertTrue(all(state['invariants'].values()))


if __name__ == '__main__':
    unittest.main()

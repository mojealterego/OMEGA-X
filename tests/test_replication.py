"""Deterministic external-cluster simulation with quorum and safety invariants."""
import unittest
from omega_x.replication import QuorumTwin, run_campaign


class TestQuorumTwin(unittest.TestCase):
    def test_partition_prevents_minorities_from_committing(self):
        twin = QuorumTwin(3, seed=7)
        self.assertTrue(twin.append('first'))
        twin.partition(((0,), (1, 2)))
        self.assertTrue(twin.append('second'))
        self.assertEqual(twin.leader, 1)
        self.assertEqual(twin.committed, ['first', 'second'])
        self.assertTrue(twin.invariants()['prefix_safety'])

    def test_crash_failover_and_rejoin_replays_committed_log(self):
        twin = QuorumTwin(3, seed=1)
        self.assertTrue(twin.append('a'))
        twin.crash(0)
        self.assertTrue(twin.append('b'))
        twin.recover(0)
        twin.heal()
        self.assertTrue(twin.append('c'))
        self.assertEqual(twin.nodes[0].log, ['a', 'b', 'c'])
        self.assertTrue(all(twin.invariants().values()))

    def test_no_majority_rejects_write(self):
        twin = QuorumTwin(3, seed=9)
        twin.crash(1)
        twin.crash(2)
        self.assertFalse(twin.append('rejected'))
        self.assertEqual(twin.committed, [])

    def test_campaign_is_reproducible_and_conserves_events(self):
        a = run_campaign(20261111, 300, nodes=5)
        b = run_campaign(20261111, 300, nodes=5)
        self.assertEqual(a, b)
        self.assertEqual(a['rounds'], sum(a['event_counts'].values()))
        self.assertTrue(all(a['invariants'].values()))
        self.assertEqual(len(a['sha256']), 64)

    def test_multiseed_failover_campaign(self):
        for seed in range(30):
            result = run_campaign(seed, 250, nodes=3)
            self.assertTrue(all(result['invariants'].values()), f'seed {seed}')

if __name__ == '__main__':
    unittest.main()

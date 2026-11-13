"""Bounded deterministic Markov and stride prefetch behavior."""
import unittest
from omega_x.prefetch import MarkovPrefetcher
from omega_x.model import Domain, load_profile, Workload, Instruction
from omega_x.runtime import OmegaRuntime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestPrefetch(unittest.TestCase):
    def test_stride_predictions_are_bounded_and_monotonic(self):
        p = MarkovPrefetcher(depth=4, max_transitions=64)
        for line in (10, 11, 12, 13, 14):
            p.observe(1, line)
        self.assertEqual(p.predict(1, 14), (15, 16, 17, 18))
        self.assertEqual(p.predict(1, (1 << 64) - 1), ())

    def test_markov_successor_after_repeated_pattern(self):
        p = MarkovPrefetcher(depth=2, max_transitions=64)
        for line in (10, 20, 10, 20, 10, 20):
            p.observe(2, line)
        self.assertEqual(p.predict(2, 10)[0], 20)

    def test_bounded_memory_and_no_cross_task_history(self):
        p = MarkovPrefetcher(depth=8, max_transitions=16)
        for line in range(100):
            p.observe(1, line)
        self.assertLessEqual(p.transition_count, 16)
        self.assertEqual(p.predict(999, 10), ())

    def test_runtime_reports_modeled_prefetches_and_cache_invariant(self):
        profile = load_profile(ROOT / 'config/profile.json')
        trace = tuple(i * 64 for i in range(100))
        task = Workload(4, 'trace', Instruction.CACHE, 1000, 1024 * 1024, trace=trace)
        result = OmegaRuntime(profile).run([task])
        self.assertGreater(result['modeled_prefetches'], 0)
        self.assertTrue(result['invariants']['cache_partition'])

if __name__ == '__main__':
    unittest.main()

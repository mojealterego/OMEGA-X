"""RED-first tests: decision policies, proof-carrying evolution, state exploration."""
import copy
import json
import unittest
from omega_x.engineering_twin import DigitalTwin, Profile, TwinTask, Fault
from omega_x.policy_evolution import evaluate_policies, PolicyEvaluationError
from omega_x.state_explorer import explore_coherence


def jobs():
    return [TwinTask(i, 'alpha' if i % 2 else 'beta', 'VECTOR', 100, 0, 0, 100_000)
            for i in range(8)]


class TestPolicyEvolution(unittest.TestCase):
    def setUp(self):
        self.profile = Profile(p_lanes=1, e_lanes=4, npu_lanes=0, p_ops_per_us=100,
                               e_ops_per_us=60, power_budget_watts=100)

    def test_dynamic_policy_reduces_model_makespan(self):
        baseline = DigitalTwin(self.profile, 10).run(jobs())
        evolved = DigitalTwin(self.profile, 10).run(jobs(), policy='earliest_finish')
        self.assertLess(evolved['makespan_ns'], baseline['makespan_ns'])
        self.assertTrue(all(evolved['invariants'].values()))
        self.assertEqual(evolved['jobs'], baseline['jobs'])

    def test_dynamic_policy_is_deterministic(self):
        a = DigitalTwin(self.profile, 10).run(jobs(), policy='earliest_finish')
        b = DigitalTwin(self.profile, 10).run(list(reversed(jobs())), policy='earliest_finish')
        self.assertEqual(a['proof_sha256'], b['proof_sha256'])

    def test_unknown_policy_rejected(self):
        with self.assertRaises(ValueError):
            DigitalTwin(self.profile, 1).run(jobs(), policy='unsafe')

    def test_evolution_preserves_safety_gate(self):
        result = evaluate_policies(self.profile, [jobs(), jobs()],
                                   [[Fault('p_down', 0, 1000)], []], [7, 8])
        self.assertIn(result['selected'], ('compat', 'earliest_finish'))
        self.assertTrue(result['guardrails_passed'])
        self.assertEqual(result['evidence_tier'], 'SIMULATED_TESTED')
        self.assertEqual(len(result['cases']), 2)
        self.assertEqual(result['proof_sha256'], evaluate_policies(self.profile, [jobs(), jobs()],
                                   [[Fault('p_down', 0, 1000)], []], [7, 8])['proof_sha256'])

    def test_evolution_rejects_invalid_cases(self):
        with self.assertRaises((ValueError, PolicyEvaluationError)):
            evaluate_policies(self.profile, [jobs()], [[]], [7, 8])

    def test_shadow_guard_rejects_regression(self):
        import random
        rng = random.Random(47)
        case = [TwinTask(i, 'a', 'VECTOR' if rng.randrange(2) else 'BACKGROUND',
                         rng.randrange(50, 10000), rng.randrange(0, 300),
                         rng.randrange(0, 300), rng.randrange(200000, 500000))
                for i in range(10)]
        profile = Profile(p_lanes=1, e_lanes=1, npu_lanes=0, p_ops_per_us=200,
                          e_ops_per_us=40, power_budget_watts=40)
        proof = evaluate_policies(profile, [case], [[]], [47])
        self.assertFalse(proof['candidate_guardrails_passed'])
        self.assertTrue(proof['guardrails_passed'])
        self.assertEqual(proof['selected'], 'compat')
        self.assertEqual(proof['selected_aggregate_makespan_ns'], proof['baseline_aggregate_makespan_ns'])

    def test_bounded_full_depth_three_node_exploration(self):
        result = explore_coherence(nodes=3, depth=4, capacity=2)
        self.assertTrue(result['search_exhausted'])
        self.assertGreater(result['states'], 1000)
        self.assertGreater(result['rejected_stale_leases'], 100)

    def test_explorer_repeatability(self):
        a = explore_coherence(nodes=2, depth=3, capacity=2)
        b = explore_coherence(nodes=2, depth=3, capacity=2)
        self.assertEqual(a, b)
        self.assertTrue(a['all_invariants_pass'])
        self.assertGreater(a['transitions'], 20)
        self.assertGreater(a['rejected_stale_leases'], 0)

    def test_explorer_parameter_limits(self):
        for invalid in (-1, 0, 8, True):
            with self.assertRaises(ValueError):
                explore_coherence(depth=invalid)


if __name__ == '__main__':
    unittest.main()

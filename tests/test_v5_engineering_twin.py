"""Test-first contractual tests for deterministic external architecture admission."""
import json
import random
import subprocess
import tempfile
import sys
import unittest
from pathlib import Path

from omega_x.engineering_twin import (
    DigitalTwin, Fault, Profile, TwinTask, run_multiseed_campaign
)


class ExternalArchitectureContract(unittest.TestCase):
    def setUp(self):
        self.profile = Profile(p_lanes=2, e_lanes=2, npu_lanes=1,
                               p_ops_per_us=1000, e_ops_per_us=500,
                               npu_ops_per_us=2000, fabric_bytes_per_ns=64,
                               link_latency_ns=800, p_lane_watts=30,
                               e_lane_watts=10, npu_lane_watts=15,
                               power_budget_watts=45)
        self.jobs = [
            TwinTask(task_id=i, tenant='alpha' if i % 2 else 'beta',
                     kind=('TENSOR' if i % 5 == 0 else 'BACKGROUND' if i % 3 == 0 else 'VECTOR'),
                     ops=10000 + 1000*i, transfer_bytes=4096,
                     arrival_ns=0, deadline_ns=1_000_000)
            for i in range(20)
        ]

    def test_repeatability_and_record_hash(self):
        a = DigitalTwin(self.profile, seed=1122).run(self.jobs)
        b = DigitalTwin(self.profile, seed=1122).run(self.jobs)
        self.assertEqual(a, b)
        self.assertEqual(a['jobs'], len(self.jobs))
        self.assertEqual(a['completed'] + a['deadline_misses'] + a['unavailable'], a['jobs'])
        self.assertTrue(all(a['invariants'].values()))
        self.assertEqual(len(a['proof_sha256']), 64)
        self.assertLessEqual(a['peak_power_watts'], self.profile.power_budget_watts)

    def test_fabric_outage_queues_until_heal_without_fabric_magic(self):
        jobs = [TwinTask(1, 'tenantA', 'VECTOR', 2000, 2048, 0, 100000),
                TwinTask(2, 'tenantB', 'VECTOR', 2000, 2048, 1, 3000)]
        result = DigitalTwin(self.profile, 12).run(jobs, [Fault('fabric_down', 0, 5000)])
        self.assertEqual(result['completed'], 1)
        self.assertEqual(result['deadline_misses'], 1)
        self.assertGreaterEqual(result['outcomes'][0]['fabric_started_ns'], 5000)

    def test_npu_failure_routes_to_realistic_cpu_sim_domain(self):
        jobs = [TwinTask(7, 'alpha', 'TENSOR', 20000, 256, 0, 500000)]
        res = DigitalTwin(self.profile, 1).run(jobs, [Fault('npu_down', 0, 100000)])
        self.assertEqual(res['outcomes'][0]['domain'], 'P')
        self.assertEqual(res['completed'], 1)
        self.assertTrue(all(res['invariants'].values()))

    def test_no_execution_if_every_domain_is_unavailable(self):
        faults = [Fault('p_down', 0, 200000), Fault('e_down', 0, 200000),
                  Fault('npu_down', 0, 200000)]
        res = DigitalTwin(self.profile, 42).run([TwinTask(1, 'alpha', 'TENSOR', 1000, 0, 0, 10000)], faults)
        self.assertEqual(res['unavailable'], 1)
        self.assertEqual(res['outcomes'][0]['status'], 'unavailable')

    def test_power_budget_constrains_parallelism(self):
        jobs = [TwinTask(i, 'a', 'VECTOR', 60000, 0, 0, 1000000) for i in range(10)]
        res = DigitalTwin(self.profile, 0).run(jobs)
        self.assertLessEqual(res['peak_power_watts'], 45)
        self.assertTrue(res['invariants']['power_budget'])
        self.assertTrue(all(v['finish_ns'] >= v['compute_started_ns'] for v in res['outcomes']))

    def test_tenant_fair_arrival_order_and_no_duplicate_dispatch(self):
        jobs = [TwinTask(i, 'z', 'BACKGROUND', 1000, 0, 0, 100000) for i in range(6)] + [
            TwinTask(i, 'a', 'BACKGROUND', 1000, 0, 0, 100000) for i in range(6, 9)]
        res = DigitalTwin(self.profile, 0).run(jobs)
        order = [row['tenant'] for row in res['outcomes']]
        self.assertEqual(order[:6], ['a', 'z', 'a', 'z', 'a', 'z'])
        self.assertEqual(len({o['task_id'] for o in res['outcomes']}), 9)

    def test_finite_bounds_inputs_fail_closed(self):
        with self.assertRaises(ValueError):
            TwinTask(1, 'a', 'VECTOR', 1, 1, 0, -1)
        with self.assertRaises(ValueError):
            TwinTask(1, 'a', 'VECTOR', 1, -1, 0, 1)
        with self.assertRaises(ValueError):
            Fault('fabric_down', 100, 100)
        with self.assertRaises(ValueError):
            Profile(p_lanes=0)
        with self.assertRaises(ValueError):
            DigitalTwin(self.profile, -1)
        with self.assertRaises(ValueError):
            DigitalTwin(self.profile, 0).run(self.jobs + [self.jobs[0]])
        with self.assertRaises(ValueError):
            DigitalTwin(self.profile, 0).run(self.jobs, [Fault('invalid', 0, 1)])

    def test_campaign_50_seeds_matrix_and_replay(self):
        campaign = run_multiseed_campaign(seeds=50, jobs_per_seed=48, base_seed=20261112)
        self.assertEqual(campaign['seeds'], 50)
        self.assertEqual(campaign['jobs'], 2400)
        self.assertTrue(campaign['all_invariants_pass'])
        self.assertEqual(len(campaign['campaign_sha256']), 64)
        self.assertGreater(campaign['injected_faults'], 0)
        self.assertEqual(campaign, run_multiseed_campaign(seeds=50, jobs_per_seed=48, base_seed=20261112))

    def test_cli_entrypoint_outputs_machine_readable_proof(self):
        root = Path(__file__).resolve().parents[1]
        run = subprocess.run([sys.executable, '-m', 'omega_x.cli', 'engineering-twin', '--seed', '10',
                              '--jobs', '30'], cwd=root, text=True, capture_output=True, timeout=12)
        self.assertEqual(run.returncode, 0, run.stderr)
        payload = json.loads(run.stdout)
        self.assertEqual(payload['jobs'], 30)
        self.assertTrue(all(payload['invariants'].values()))
        self.assertEqual(payload['evidence_tier'], 'SIMULATED_TESTED')

    def test_custom_request_json_runs_faults_with_strict_schema(self):
        root = Path(__file__).resolve().parents[1]
        envelope = {'schema_version': 1, 'seed': 99,
                    'profile': {'p_lanes': 2, 'e_lanes': 2, 'npu_lanes': 1,
                                'power_budget_watts': 60},
                    'tasks': [{'task_id': 1, 'tenant': 'x', 'kind': 'TENSOR',
                               'ops': 3000, 'transfer_bytes': 256,
                               'arrival_ns': 0, 'deadline_ns': 100000}],
                    'faults': [{'kind':'npu_down', 'start_ns': 0, 'end_ns': 1000}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.json'
            path.write_text(json.dumps(envelope), encoding='utf-8')
            run = subprocess.run([sys.executable, '-m', 'omega_x.cli', 'engineering-twin',
                                  '--request', str(path)], cwd=root, text=True,
                                 capture_output=True, timeout=12)
            self.assertEqual(run.returncode, 0, run.stderr)
            payload = json.loads(run.stdout)
            self.assertEqual(payload['outcomes'][0]['domain'], 'P')
            self.assertEqual(payload['evidence_tier'], 'SIMULATED_TESTED')
            path.write_text('{"seed":1,"seed":2}', encoding='utf-8')
            bad = subprocess.run([sys.executable, '-m', 'omega_x.cli', 'engineering-twin',
                                  '--request', str(path)], cwd=root, text=True,
                                 capture_output=True, timeout=12)
            self.assertNotEqual(bad.returncode, 0)

    def test_coherence_campaign_cli(self):
        root = Path(__file__).resolve().parents[1]
        run = subprocess.run([sys.executable, '-m', 'omega_x.cli', 'coherence-campaign',
                              '--seed', '198', '--seeds', '3', '--rounds', '50'], cwd=root,
                             text=True, capture_output=True, timeout=12)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(json.loads(run.stdout)['all_invariants_pass'])

    def test_randomized_invariants(self):
        for seed in range(15):
            rng = random.Random(seed)
            jobs = [TwinTask(i, f't{rng.randrange(4)}', rng.choice(('VECTOR','BACKGROUND','TENSOR')),
                             rng.randrange(1, 100000), rng.randrange(0, 30000),
                             rng.randrange(0, 50000), 5_000_000)
                    for i in range(60)]
            result = DigitalTwin(self.profile, seed).run(jobs)
            self.assertTrue(all(result['invariants'].values()), seed)


if __name__ == '__main__':
    unittest.main()

"""Offline deterministic campaign and shadow-policy correctness evidence for v6."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import random
import secrets
import sys
import tempfile
from time import perf_counter_ns

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from omega_x.engineering_twin import DigitalTwin, Fault, Profile, TwinTask
from omega_x.policy_evolution import evaluate_policies
from omega_x.proof_stream import IntegrityViolation, ProofStream
from omega_x.state_explorer import explore_coherence

ROOT = Path(__file__).resolve().parents[1]


def canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def run() -> dict:
    t0 = perf_counter_ns()
    profile = Profile(p_lanes=2, e_lanes=4, npu_lanes=1, power_budget_watts=96)
    cases: list[list[TwinTask]] = []
    windows: list[list[Fault]] = []
    seeds: list[int] = []
    for idx in range(24):
        seed = 902_000 + idx
        rng = random.Random(seed)
        cases.append([TwinTask(i, 'tenant_' + str(i % 4),
                               ('VECTOR','BACKGROUND','TENSOR')[i % 3],
                               rng.randrange(400, 30_000), rng.randrange(0, 6000),
                               rng.randrange(0, 5000), 250_000)
                      for i in range(24)])
        windows.append([Fault('fabric_down', 2000, 4000),
                        Fault(('npu_down','p_down','thermal_derate')[idx % 3], 5000, 11000)])
        seeds.append(seed)
    policy = evaluate_policies(profile, cases, windows, seeds)
    if policy != evaluate_policies(profile, cases, windows, seeds):
        raise AssertionError('policy proof is nondeterministic')
    if not policy['guardrails_passed'] or not policy['proof_sha256']:
        raise AssertionError('shadow non-regression gate failed')

    exploration = [explore_coherence(nodes=2, depth=4, capacity=2),
                   explore_coherence(nodes=3, depth=4, capacity=2)]
    if not all(x['all_invariants_pass'] and x['search_exhausted'] for x in exploration):
        raise AssertionError('exhaustive modeled coherence state exploration failed')

    fuzz_proofs: list[str] = []
    for seed in range(128):
        rng = random.Random(seed + 70_000)
        count = rng.randrange(1, 28)
        p_lanes = rng.randrange(1, 5)
        e_lanes = rng.randrange(1, 7)
        npu_lanes = rng.randrange(0, 3)
        sim_profile = Profile(p_lanes=p_lanes, e_lanes=e_lanes, npu_lanes=npu_lanes,
                              power_budget_watts=64, p_lane_watts=14, e_lane_watts=6,
                              npu_lane_watts=9)
        tasks = [TwinTask(i, 't'+str(i%3),
                          ('VECTOR','BACKGROUND','TENSOR')[rng.randrange(3)],
                          rng.randrange(1, 50_000), rng.randrange(0, 4000),
                          rng.randrange(0, 30000), 350_000) for i in range(count)]
        faults = ([Fault('npu_down', 0, 10_000)] if seed%4 == 0 else
                  [Fault('fabric_down', 1000, 5000)] if seed%4 == 1 else
                  [Fault('thermal_derate', 10_000, 30_000)] if seed%4 == 2 else [])
        output = DigitalTwin(sim_profile, seed).run(tasks, faults, policy='earliest_finish')
        if not all(output['invariants'].values()):
            raise AssertionError('model invariant violated in fuzz campaign')
        if output['proof_sha256'] != DigitalTwin(sim_profile, seed).run(tasks, faults, policy='earliest_finish')['proof_sha256']:
            raise AssertionError('deterministic fuzz replay mismatch')
        fuzz_proofs.append(output['proof_sha256'])

    with tempfile.TemporaryDirectory(prefix='omega_v6_evidence_') as temp:
        stream = ProofStream(Path(temp)/'authenticated.jsonl', secrets.token_bytes(32), max_records=32)
        head = None
        for seq in range(16):
            head = stream.append('SCENARIO', {'seed': seq, 'status': 'SIMULATED_TESTED'})['head']
        if stream.verify(expected_head=head, expected_count=16)['count'] != 16:
            raise AssertionError('anchor verification failed')
        proof_key = stream._key
        if len(proof_key) != 32:
            raise AssertionError('evidence MAC length error')
        path = Path(temp)/'authenticated.jsonl'
        data = path.read_bytes()
        path.write_bytes(data.replace(b'SIMULATED_TESTED', b'CORRUPTED_TESTED', 1))
        try:
            stream.verify()
        except IntegrityViolation:
            tamper_rejected = True
        else:
            raise AssertionError('evidence tampering escaped authentication')

    proof = {
        'version': '6.0.0',
        'mode': 'OFFLINE_MODEL_AND_LOCAL_SECURITY_VALIDATION',
        'policy_evaluation': policy,
        'model_checker': exploration,
        'fuzz_seed_count': 128,
        'fuzz_digest_sha256': hashlib.sha256(''.join(fuzz_proofs).encode()).hexdigest(),
        'authenticated_log_records_verified': 16,
        'authenticated_log_tampering_denied': tamper_rejected,
        'proof_ledger_anchor_verified': True,
        'simulated_cases': sum(len(case) for case in cases) + sum(x['transitions'] for x in exploration) + 128,
        'physical_npu_verified': False,
        'physical_cxl_verified': False,
        'kernel_sched_ext_attached': False,
        'all_invariants_pass': True,
    }
    proof['proof_sha256'] = hashlib.sha256(canonical(proof)).hexdigest()
    artifact = ROOT/'results'/'evolution_campaign_v6.json'
    artifact.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    benchmark = {'v6_campaign_wall_ms': round((perf_counter_ns() - t0)/1e6, 3),
                 'context': 'measured Python campaign wall time on local test host, not processor-model speedup',
                 'state_machine_transitions': sum(x['transitions'] for x in exploration),
                 'policy_cases': len(cases),
                 'fuzz_seeds': 128}
    (ROOT/'results'/'v6_benchmark.json').write_text(json.dumps(benchmark, indent=2)+'\n',encoding='utf-8')
    return {'proof_sha256': proof['proof_sha256'], 'simulated_cases': proof['simulated_cases'],
            'policy_selected': policy['selected'], 'checker_states': sum(x['states'] for x in exploration),
            'fuzz_seeds': 128, 'tamper_rejected': tamper_rejected,
            'elapsed_ms': benchmark['v6_campaign_wall_ms']}


if __name__ == '__main__':
    print(json.dumps(run(), indent=2, ensure_ascii=False))

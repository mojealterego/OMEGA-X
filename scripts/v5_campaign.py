"""Offline reproducible admission of isolated hardware-inspired simulation profiles.

Does not control real sched_ext, NPU, CXL, DRAM or host scheduling.
"""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from omega_x.coherence_twin import run_coherence_campaign
from omega_x.engineering_twin import run_multiseed_campaign
from omega_x.replication import run_campaign
from kernel_ebpf.preflight import inspect_host


def execute() -> dict:
    engineering = run_multiseed_campaign(seeds=100, jobs_per_seed=96, base_seed=20261112)
    coherence = run_coherence_campaign(seeds=100, rounds=200, base_seed=10261112)
    quorum = [run_campaign(42000 + seed, 1000, (3, 5, 7)[seed % 3]) for seed in range(50)]
    if not (engineering['all_invariants_pass'] and coherence['all_invariants_pass'] and
            all(all(report['invariants'].values()) for report in quorum)):
        raise AssertionError('admission invariant failed')
    # Check the pure-C reference compilation, separate from the kernel BPF ABI.
    out = ROOT / 'kernel_ebpf' / 'libomega_policy_reference.so'
    build = subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            '-fPIC', '-shared', '-o', str(out),
                            str(ROOT / 'kernel_ebpf/policy_reference.c')],
                           cwd=ROOT, capture_output=True, text=True, timeout=30)
    if build.returncode:
        raise RuntimeError('C11 contract compile failed: ' + build.stderr)
    (ROOT / 'results/scx_policy_build.log').write_text('C11_CONTRACT_BUILD_PASS\n' + build.stderr, encoding='utf-8')
    preflight = inspect_host()
    (ROOT / 'results/scx_preflight_v5.json').write_text(json.dumps(preflight, indent=2), encoding='utf-8')
    out_data = {
        'mode': 'SIMULATED_TESTED',
        'physical_npu_verified': False, 'physical_cxl_verified': False,
        'kernel_sched_ext_attached': False,
        'bpf_abi_compilation_verified': False,
        'engineering': engineering,
        'coherence': coherence,
        'quorum': {
            'seeds': len(quorum),
            'events': sum(r['rounds'] for r in quorum),
            'commits': sum(r['commits'] for r in quorum),
            'rejected_writes': sum(r['rejected_writes'] for r in quorum),
            'all_invariants_pass': True,
            'seed_proofs': [r['sha256'] for r in quorum],
        },
        'c11_scheduler_policy_reference_compiled': True,
        'scx_sdk_and_kernel_status': preflight['status'],
    }
    out_data['all_invariants_pass'] = bool(engineering['all_invariants_pass'] and
                                           coherence['all_invariants_pass'] and
                                           out_data['quorum']['all_invariants_pass'])
    out_data['scenario_events'] = engineering['jobs'] + coherence['events'] + out_data['quorum']['events']
    digest = sha256(json.dumps(out_data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    out_data['proof_sha256'] = digest
    (ROOT / 'results/architecture_campaign_v5.json').write_text(
        json.dumps(out_data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {
        'simulation_status': out_data['mode'], 'all_invariants_pass': out_data['all_invariants_pass'],
        'scenario_events': out_data['scenario_events'],
        'engineering_jobs': engineering['jobs'], 'coherence_events': coherence['events'],
        'quorum_events': out_data['quorum']['events'], 'rejections_coherence': coherence['fail_closed_rejections'],
        'proof_sha256': digest, 'kernel_attached': False,
    }


if __name__ == '__main__':
    print(json.dumps(execute(), sort_keys=True, ensure_ascii=False))

"""Reproducible virtual fusion acceptance campaign and independent real-CPU probes."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from omega_x.fusion_twin import compare_architectures, solve_virtual_envelope, run_sensitivity_campaign
from omega_x.fusion_functional import run_functional_replay


def save(name: str, obj: dict) -> None:
    (ROOT / 'results' / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False,
                                                     sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')


def main() -> dict:
    compare = compare_architectures()
    contract = solve_virtual_envelope(max_multiplier=16)
    sensitivity = run_sensitivity_campaign(seeds=128)
    functional = run_functional_replay()
    if (not contract['contract_satisfied'] or not sensitivity['all_invariants_pass'] or
        functional['passed'] != 12 or functional['failed'] or
        not all(all(r['invariants'].values()) for r in compare['results'].values())):
        raise RuntimeError('fusion v7 acceptance criteria failed')
    save('fusion_v7_compare.json', compare)
    save('fusion_v7_contract.json', contract)
    save('fusion_v7_sensitivity.json', sensitivity)
    save('fusion_v7_functional.json', functional)
    result = {'version': '7.0.0', 'evidence_tier': 'DETERMINISTIC_VIRTUAL_MODEL_AND_REAL_CPU_FUNCTIONAL',
              'model_baseline_ms': compare['model_makespan_ms'],
              'pdf_reference_ms': compare['pdf_reference_ms'],
              'virtual_contract_satisfied': contract['contract_satisfied'],
              'required_logical_time_multiplier': contract['required_virtual_clock_multiplier'],
              'virtual_contract_makespan_ms': contract['verified_makespan_ms'],
              'model_sensitivity_scenarios': sensitivity['scenarios'],
              'model_sensitivity_all_invariants_pass': sensitivity['all_invariants_pass'],
              'real_cpu_functional_passed': functional['passed'],
              'real_cpu_functional_digest': functional['functional_sha256'],
              'physical_ryzen_intel_fusion_verified': False,
              'physical_npu_verified': False,
              'kernel_sched_ext_attached': False,
              'host_measured_pdf_benchmark': False,
              'inputs': {'compare_proof': compare['proof_sha256'],
                         'contract_proof': contract['proof_sha256'],
                         'sensitivity_proof': sensitivity['proof_sha256']}}
    result['proof_sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True,
                                  separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    save('fusion_v7_acceptance.json', result)
    return result

if __name__ == '__main__':
    print(json.dumps(main(), indent=2, ensure_ascii=False, sort_keys=True))

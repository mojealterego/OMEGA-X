"""Deterministic proof-carrying shadow policy evaluator with non-regression gates.

Policies are executable model alternatives, not kernel patches. Shadow runs compare
identical inputs, seeds, fault windows and capacity. No host scheduling is changed.
"""
from __future__ import annotations

from hashlib import sha256
import json

from .engineering_twin import DigitalTwin, Fault, Profile, TwinTask


class PolicyEvaluationError(ValueError):
    """Invalid scenario or unverifiable comparison."""


def _view(report: dict) -> dict:
    keys = ('completed', 'deadline_misses', 'unavailable', 'latency_p99_ns',
            'makespan_ns', 'peak_power_watts', 'proof_sha256')
    return {key: report[key] for key in keys}


def _guard(reference: dict, candidate: dict) -> bool:
    return (all(reference['invariants'].values()) and all(candidate['invariants'].values())
            and candidate['completed'] >= reference['completed']
            and candidate['deadline_misses'] <= reference['deadline_misses']
            and candidate['unavailable'] <= reference['unavailable']
            and (reference['latency_p99_ns'] is None or
                 (candidate['latency_p99_ns'] is not None and
                  candidate['latency_p99_ns'] <= reference['latency_p99_ns']))
            and candidate['peak_power_watts'] <= reference['assumptions']['power_budget_watts'])


def evaluate_policies(profile: Profile, task_scenarios: list[list[TwinTask]],
                      fault_scenarios: list[list[Fault]], seeds: list[int]) -> dict:
    """Evaluate safe alternatives and return a reproducible, read-only decision proof.

    A proposal is selected only if every scenario's safety/non-regression gate
    succeeds and aggregate modeled makespan strictly improves. Otherwise the
    conservative original policy is retained. All results are modeling evidence.
    """
    if not isinstance(profile, Profile):
        raise PolicyEvaluationError('validated profile required')
    if (not isinstance(task_scenarios, list) or not isinstance(fault_scenarios, list)
        or not isinstance(seeds, list) or not 1 <= len(seeds) <= 32
        or len(task_scenarios) != len(seeds) or len(fault_scenarios) != len(seeds)):
        raise PolicyEvaluationError('1-32 corresponding task/fault/seed scenarios required')
    rows = []
    for seed, tasks, faults in zip(seeds, task_scenarios, fault_scenarios):
        if type(seed) is not int or not 0 <= seed < 2**63:
            raise PolicyEvaluationError('invalid reproducibility seed')
        if not isinstance(tasks, list) or not 1 <= len(tasks) <= 256:
            raise PolicyEvaluationError('scenario must contain 1-256 tasks')
        if not isinstance(faults, list) or len(faults) > 64:
            raise PolicyEvaluationError('fault list outside bounds')
        baseline = DigitalTwin(profile, seed).run(tasks, faults, policy='compat')
        trial = DigitalTwin(profile, seed).run(tasks, faults, policy='earliest_finish')
        rows.append({'seed': seed, 'tasks': len(tasks), 'baseline': _view(baseline),
                     'candidate': _view(trial), 'non_regression': _guard(baseline, trial)})
    baseline_total = sum(row['baseline']['makespan_ns'] for row in rows)
    candidate_total = sum(row['candidate']['makespan_ns'] for row in rows)
    accept = all(row['non_regression'] for row in rows) and candidate_total < baseline_total
    body = {'evidence_tier': 'SIMULATED_TESTED',
            'scope': 'SHADOW_POLICY_ONLY_NO_HARDWARE_CHANGE',
            'selected': 'earliest_finish' if accept else 'compat',
            'candidate': 'earliest_finish',
            'guardrails_passed': True,
            'candidate_guardrails_passed': all(row['non_regression'] for row in rows),
            'candidate_improves_modeled_makespan': candidate_total < baseline_total,
            'baseline_aggregate_makespan_ns': baseline_total,
            'candidate_aggregate_makespan_ns': candidate_total,
            'selected_aggregate_makespan_ns': candidate_total if accept else baseline_total,
            'cases': rows,
            'operator_approval': False,
            'auto_deployment': False}
    body['proof_sha256'] = sha256(json.dumps(body, sort_keys=True, separators=(',', ':'),
                                          allow_nan=False).encode('ascii')).hexdigest()
    return body

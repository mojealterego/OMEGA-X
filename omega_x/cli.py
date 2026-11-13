"""Offline CLI for deterministic model, real CPU execution, cluster twin and signed bridge."""
from __future__ import annotations
from pathlib import Path
import argparse
import json
import os
import random
import re
import sqlite3
import signal
import threading
import sys
import time
from .model import load_profile
from .runtime import OmegaRuntime
from .adapter import decode
from .simulation import DeterministicTwin
from .host import detect_host
from .executor import ExecutionRequest, LocalExecutor
from .replication import run_campaign
from .engineering_twin import DigitalTwin, Profile as EngineeringProfile, TwinTask, Fault, run_multiseed_campaign
from .coherence_twin import run_coherence_campaign
from .state_explorer import explore_coherence
from .policy_evolution import evaluate_policies
from .proof_stream import ProofStream, IntegrityViolation
from .bridge_v2 import verify_request, ReplayStore, AuthenticationError
from .ledger import EvidenceLedger
from .topology import detect_topology
from .real_policy import PhysicalPlanner, PhysicalExecutor
from .native import NativeKernels
from .adapter import _reject_duplicates
from .service import LocalControlPlane, create_keys, load_keys
from dataclasses import asdict

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / 'config' / 'profile.json'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='omega-x')
    parser.add_argument('--profile', default=str(PROFILE))
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run', help='deterministic CPU/cache model from JSON v1')
    run.add_argument('request')
    twin = sub.add_parser('simulate', help='fault-injection simulation')
    twin.add_argument('--seed', type=int, default=20261111)
    twin.add_argument('--rounds', type=int, default=200)
    eng = sub.add_parser('engineering-twin', help='deterministic external architecture digital twin; no host hardware implied')
    eng.add_argument('--seed', type=int, default=20261112)
    eng.add_argument('--request', type=str, help='strict v1 architecture JSON envelope')
    eng.add_argument('--jobs', type=int, default=48)
    eng.add_argument('--faults', action='store_true', help='inject modeled fabric, thermal and NPU outages')
    campaign = sub.add_parser('engineering-campaign', help='bounded deterministic multiseed fault campaign')
    campaign.add_argument('--seed', type=int, default=20261112)
    campaign.add_argument('--seeds', type=int, default=50)
    campaign.add_argument('--jobs', type=int, default=48)
    coherence_campaign = sub.add_parser('coherence-campaign', help='bounded CXL-like SWMR/partition fault campaign')
    coherence_campaign.add_argument('--seed', type=int, default=20261112)
    coherence_campaign.add_argument('--seeds', type=int, default=50)
    coherence_campaign.add_argument('--rounds', type=int, default=120)
    evolve = sub.add_parser('policy-evaluate', help='read-only proof-carrying shadow policy campaign')
    evolve.add_argument('--seed', type=int, default=20261112)
    evolve.add_argument('--scenarios', type=int, default=16)
    evolve.add_argument('--jobs', type=int, default=24)
    explorer = sub.add_parser('coherence-explore', help='bounded exhaustive coherence state exploration')
    explorer.add_argument('--nodes', type=int, choices=(2, 3), default=2)
    explorer.add_argument('--depth', type=int, default=4)
    explorer.add_argument('--capacity', type=int, default=2)
    append_event = sub.add_parser('proof-append', help='record a signed local JSON evidence event')
    append_event.add_argument('path')
    append_event.add_argument('event_json')
    verify_events = sub.add_parser('proof-verify', help='check signed evidence and external anchor')
    verify_events.add_argument('path')
    verify_events.add_argument('--head')
    verify_events.add_argument('--count', type=int)
    sub.add_parser('host', help='read-only real host capabilities')
    sub.add_parser('host-topology', help='read-only verified P/E topology from sysfs')
    plan = sub.add_parser('physical-plan', help='map modeled v1 workloads to allowed physical CPU IDs without execution')
    plan.add_argument('request')
    batch = sub.add_parser('execute-batch', help='run a bounded JSON batch of approved Linux CPU operations')
    batch.add_argument('request')
    batch.add_argument('--workers', type=int, default=2)
    batch.add_argument('--timeout', type=float, default=10)
    gemm = sub.add_parser('matmul-int8', help='execute exact bounded INT8 matrix multiplication on CPU')
    gemm.add_argument('request')
    execute = sub.add_parser('execute', help='real sandboxed Linux CPU workload')
    execute.add_argument('--kind', choices=('sha256', 'saxpy', 'memory'), required=True)
    execute.add_argument('--size', type=int, required=True)
    execute.add_argument('--cpu', type=int)
    execute.add_argument('--timeout', type=float, default=10)
    cluster = sub.add_parser('replicate', help='deterministic quorum twin')
    cluster.add_argument('--seed', type=int, default=20261111)
    cluster.add_argument('--rounds', type=int, default=1000)
    cluster.add_argument('--nodes', type=int, choices=(3, 5, 7), default=3)
    keys = sub.add_parser('init-keys', help='create an owner-only tenant key file; never overwrites')
    keys.add_argument('path')
    keys.add_argument('--tenants', nargs='+', required=True)
    serve = sub.add_parser('serve', help='start authenticated loopback-only real CPU job service')
    serve.add_argument('--keys-file', required=True)
    serve.add_argument('--state-dir', required=True)
    serve.add_argument('--port', type=int, default=8765)
    serve.add_argument('--workers', type=int, default=2)
    serve.add_argument('--max-pending', type=int, default=256)
    sub.add_parser('fusion-functional', help='execute bounded real CPU kernels for 12 virtual task classes')
    sub.add_parser('fusion-compare', help='v7 virtual Ryzen/Intel 12-task benchmark (modeled, not measured)')
    solve = sub.add_parser('fusion-solve', help='v7 bounded logical-time contract feasibility solver')
    solve.add_argument('--max-multiplier', type=int, default=16)
    custom = sub.add_parser('fusion-run', help='strict custom v7 virtual performance envelope')
    custom.add_argument('request')
    sweep = sub.add_parser('fusion-campaign', help='v7 bounded deterministic sensitivity campaign')
    sweep.add_argument('--seeds', type=int, default=128)
    sweep.add_argument('--seed', type=int, default=20261112)
    signed = sub.add_parser('run-signed', help='authenticated v2 Digital-Life-compatible offline request')
    signed.add_argument('request')
    signed.add_argument('--now-ns', type=int, help='test clock, requires OMEGA_X_TEST_MODE=1')
    args = parser.parse_args(argv)
    try:
        if args.command == 'fusion-functional':
            from .fusion_functional import run_functional_replay
            result = run_functional_replay()
        elif args.command == 'fusion-run':
            from .fusion_twin import FusionTask, FusionTwin, REFERENCE_ARCHITECTURES
            from dataclasses import replace
            raw = Path(args.request).read_bytes()
            if len(raw) > 262144:
                raise ValueError('fusion envelope exceeds 256 KiB')
            body = json.loads(raw, object_pairs_hook=_reject_duplicates,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
            if not isinstance(body, dict) or set(body) != {'schema_version', 'architecture', 'policy', 'virtual_multiplier', 'faults', 'tasks'} or type(body['schema_version']) is not int or body['schema_version'] != 1:
                raise ValueError('invalid fusion v7 envelope')
            if body['architecture'] not in REFERENCE_ARCHITECTURES or not isinstance(body['tasks'], list) or not isinstance(body['faults'], list):
                raise ValueError('invalid architecture, tasks or faults')
            required = {'task_id','name','kind','instructions','working_set_bytes','vector_fraction','cache_warmth','tensor_sparsity','memory_access_fraction'}
            if any(not isinstance(t, dict) or set(t) != required for t in body['tasks']):
                raise ValueError('invalid fusion task schema')
            profile = replace(REFERENCE_ARCHITECTURES[body['architecture']], virtual_multiplier=body['virtual_multiplier'])
            result = FusionTwin(profile).run([FusionTask(**t) for t in body['tasks']],
                                             policy=body['policy'], faults=tuple(body['faults']))
        elif args.command == 'fusion-campaign':
            from .fusion_twin import run_sensitivity_campaign
            result = run_sensitivity_campaign(seeds=args.seeds, seed=args.seed)
        elif args.command == 'fusion-compare':
            from .fusion_twin import compare_architectures
            result = compare_architectures()
        elif args.command == 'fusion-solve':
            from .fusion_twin import solve_virtual_envelope
            result = solve_virtual_envelope(max_multiplier=args.max_multiplier)
        elif args.command == 'init-keys':
            create_keys(args.path, args.tenants)
            result = {'status': 'created', 'tenants': len(args.tenants), 'mode': 'owner_only_0600'}
        elif args.command == 'serve':
            service = LocalControlPlane(Path(args.state_dir) / 'jobs.sqlite3', load_keys(args.keys_file),
                                        port=args.port, workers=args.workers, max_pending=args.max_pending)
            stop = threading.Event()
            def on_signal(_number, _frame):
                stop.set()
            signal.signal(signal.SIGTERM, on_signal)
            signal.signal(signal.SIGINT, on_signal)
            try:
                service.start()
                print(json.dumps({'status':'listening','host':'127.0.0.1','port':service.port,
                                  'mode':'owner_operated_local_cpu'}),flush=True)
                stop.wait()
            finally:
                service.stop()
            return 0
        elif args.command == 'run':
            _, tasks = decode(Path(args.request).read_bytes())
            result = OmegaRuntime(load_profile(args.profile)).run(tasks)
        elif args.command == 'simulate':
            result = DeterministicTwin(args.seed).run(args.rounds)
        elif args.command == 'engineering-twin':
            if args.request is not None:
                raw = Path(args.request).read_bytes()
                if len(raw) > 262144:
                    raise ValueError('architecture envelope exceeds limit')
                body = json.loads(raw, object_pairs_hook=_reject_duplicates)
                if not isinstance(body, dict) or set(body) != {'schema_version','seed','profile','tasks','faults'} or body['schema_version'] != 1:
                    raise ValueError('invalid schema v1 architecture envelope')
                if not isinstance(body['profile'], dict) or not isinstance(body['tasks'], list) or not isinstance(body['faults'], list):
                    raise ValueError('invalid architecture structures')
                custom = EngineeringProfile(**body['profile'])
                jobs = [TwinTask(**row) for row in body['tasks']]
                faults = [Fault(**row) for row in body['faults']]
                result = DigitalTwin(custom, body['seed']).run(jobs, faults)
            else:
                if not 1 <= args.jobs <= 4096:
                    raise ValueError('engineering-twin bounded jobs [1,4096]')
                generated = [TwinTask(i, 'alpha' if i % 2 else 'beta',
                                      ('TENSOR' if i % 5 == 0 else 'BACKGROUND' if i % 3 == 0 else 'VECTOR'),
                                      3000+i*200, 2048+(i % 11)*64, (i//6)*1000, 1_000_000)
                             for i in range(args.jobs)]
                faults = [Fault('fabric_down', 0, 2500), Fault('npu_down', 6000, 12000),
                          Fault('thermal_derate', 15000, 25000)] if args.faults else []
                result = DigitalTwin(EngineeringProfile(), args.seed).run(generated, faults)
        elif args.command == 'coherence-campaign':
            result = run_coherence_campaign(args.seeds, args.rounds, args.seed)
        elif args.command == 'engineering-campaign':
            result = run_multiseed_campaign(args.seeds, args.jobs, args.seed)
        elif args.command == 'coherence-explore':
            result = explore_coherence(nodes=args.nodes, depth=args.depth, capacity=args.capacity)
        elif args.command == 'policy-evaluate':
            if not 1 <= args.scenarios <= 32 or not 1 <= args.jobs <= 256 or not 0 <= args.seed < 2**63 - args.scenarios:
                raise ValueError('policy campaign bounds violated')
            profile = EngineeringProfile(p_lanes=2, e_lanes=4, npu_lanes=1,
                                         power_budget_watts=96)
            scenarios = []
            faults = []
            seeds = []
            for n in range(args.scenarios):
                seed = args.seed + n
                rng = random.Random(seed)
                scenarios.append([TwinTask(i, 'tenant_' + str(i % 3),
                                           ('VECTOR' if i % 2 else 'BACKGROUND') if i % 7
                                           else 'TENSOR', rng.randrange(200, 30_000),
                                           rng.randrange(0, 16_000), rng.randrange(0, 3000),
                                           500_000) for i in range(args.jobs)])
                faults.append(([Fault('npu_down', 0, 8000), Fault('thermal_derate', 3000, 9000)]
                               if n % 3 == 0 else [Fault('p_down', 0, 2000)] if n % 3 == 1
                               else [Fault('fabric_down', 0, 1000)]))
                seeds.append(seed)
            result = evaluate_policies(profile, scenarios, faults, seeds)
        elif args.command in ('proof-append', 'proof-verify'):
            raw_key = os.environ.get('OMEGA_X_PROOF_KEY_HEX', '')
            if not re.fullmatch('[0-9a-f]{64}', raw_key):
                raise ValueError('OMEGA_X_PROOF_KEY_HEX must contain 64 lowercase hex characters')
            stream = ProofStream(args.path, bytes.fromhex(raw_key))
            if args.command == 'proof-verify':
                result = stream.verify(expected_head=args.head, expected_count=args.count)
            else:
                path = Path(args.event_json)
                if path.stat().st_size > 8192:
                    raise ValueError('input event too large')
                body = json.loads(path.read_bytes(), object_pairs_hook=_reject_duplicates)
                if not isinstance(body, dict) or set(body) != {'kind', 'payload'}:
                    raise ValueError('invalid evidence event schema')
                result = stream.append(body['kind'], body['payload'])
        elif args.command == 'host':
            result = detect_host().to_dict()
        elif args.command == 'host-topology':
            result = detect_topology().to_dict()
        elif args.command == 'physical-plan':
            _, tasks = decode(Path(args.request).read_bytes())
            result = {'mode': 'real_cpu_affinity_proposal',
                      'plan': [asdict(p) for p in PhysicalPlanner(detect_topology()).plan(tasks)],
                      'simulated_npu_engines': 'not physical devices'}
        elif args.command == 'execute-batch':
            raw = Path(args.request).read_bytes()
            if len(raw) > 65536:
                raise ValueError('batch envelope too large')
            body = json.loads(raw, object_pairs_hook=_reject_duplicates)
            if not isinstance(body, dict) or set(body) != {'requests'} or not isinstance(body['requests'], list):
                raise ValueError('invalid batch envelope')
            reqs = []
            for req in body['requests']:
                if not isinstance(req, dict) or set(req) - {'kind','size','cpu'}:
                    raise ValueError('invalid batch request')
                reqs.append(ExecutionRequest(**req))
            result = PhysicalExecutor().run(reqs, timeout_s=args.timeout, workers=args.workers)
        elif args.command == 'matmul-int8':
            raw = Path(args.request).read_bytes()
            if len(raw) > 512 * 1024:
                raise ValueError('matrix envelope too large')
            body = json.loads(raw, object_pairs_hook=_reject_duplicates)
            if not isinstance(body, dict) or set(body) != {'left','right'}:
                raise ValueError('invalid INT8 matrix envelope')
            start_ns = time.perf_counter_ns()
            product = NativeKernels().matmul_int8(body['left'], body['right'])
            result = {'matrix': product, 'compute_device': 'CPU',
                      'measured_wall_ns': time.perf_counter_ns() - start_ns}
        elif args.command == 'execute':
            result = LocalExecutor().run_one(ExecutionRequest(args.kind, args.size, args.cpu), args.timeout)
        elif args.command == 'replicate':
            result = run_campaign(args.seed, args.rounds, args.nodes)
        else:
            if args.now_ns is not None and os.environ.get('OMEGA_X_TEST_MODE') != '1':
                raise ValueError('clock override only available in explicit test mode')
            now_ns = args.now_ns if args.now_ns is not None else time.time_ns()
            key_hex = os.environ.get('OMEGA_X_HMAC_KEY_HEX', '')
            if len(key_hex) < 64:
                raise AuthenticationError('missing or insufficient authentication key')
            try:
                key = bytes.fromhex(key_hex)
            except ValueError as exc:
                raise AuthenticationError('malformed authentication key') from exc
            raw = Path(args.request).read_bytes()
            tenant, request_id, tasks, nonce = verify_request(raw, key, now_ns)
            with ReplayStore(ROOT / 'results' / 'bridge_replay.sqlite3') as replay:
                if not replay.claim(tenant, nonce, now_ns + 86_400_000_000_000, now_ns):
                    raise AuthenticationError('replay detected: nonce already consumed')
            simulated = OmegaRuntime(load_profile(args.profile)).run(tasks)
            with EvidenceLedger(ROOT / 'results' / 'bridge_evidence.sqlite3') as ledger:
                seq = ledger.append(f'{tenant}:{request_id}', raw, simulated)
                integrity = ledger.verify()
            result = {'tenant': tenant, 'request_id': request_id, 'evidence_sequence': seq,
                      'ledger_head_sha256': integrity['head_sha256'], 'result': simulated}
        print(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, TimeoutError,
            json.JSONDecodeError, sqlite3.DatabaseError, IntegrityViolation) as exc:
        print(json.dumps({'error': type(exc).__name__, 'detail': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

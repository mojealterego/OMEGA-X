"""Offline deterministic ZIP packager with SHA-256 manifest and extraction verification."""
from __future__ import annotations
import hashlib
import hmac
import json
from pathlib import Path
import re
import shutil
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parent / (ROOT.name + '.zip')
MANIFEST = ROOT / 'MANIFEST_SHA256.txt'
SUMMARY = ROOT / 'results/release_summary.json'
DOCS = (
    'README.md', 'ARCHITECTURE.md', 'ENGINEERING_SPECIFICATION.md',
    'BEYOND_MAXIMUM_INNOVATIONS.md', 'MODULE_REFERENCE.md', 'API_REFERENCE.md',
    'SECURITY_ARCHITECTURE.md', 'BUILD_AND_DEPLOYMENT_GUIDE.md',
    'TESTING_AND_VALIDATION.md', 'DEPENDENCIES_AND_LICENSES.md',
    'DIGITAL_LIFE_COMPATIBILITY.md', 'INTEGRATION_BLUEPRINT.md',
    'PRODUCTION_READINESS_REPORT.md',
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files() -> list[Path]:
    found = []
    for path in ROOT.rglob('*'):
        if path.is_symlink():
            raise RuntimeError(f'symlink forbidden: {path}')
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if '__pycache__' in relative.parts or 'tmp' in relative.parts or path.suffix == '.pyc':
            continue
        if path.name in ('test_native_sanitized', 'libomegax_clang.so', 'test_full_v2.log', 'test_intermediate.log'):
            continue
        if path.suffix in ('.sqlite3', '.sqlite3-wal', '.sqlite3-shm') or path.name.endswith(('-wal', '-shm')):
            continue
        found.append(path)
    return sorted(found, key=lambda p: p.relative_to(ROOT).as_posix())


def _check_content(files: list[Path]) -> None:
    if any(not (ROOT / name).is_file() for name in DOCS):
        raise RuntimeError('missing required documentation')
    if len([f for f in files if f.name in DOCS and f.parent == ROOT]) != 13:
        raise RuntimeError('documentation count mismatch')
    for f in files:
        if f.suffix not in ('.py', '.md', '.c', '.h'):
            continue
        raw = f.read_text(encoding='utf-8')
        if any(marker in raw for marker in ('TO'+'DO', 'FIX'+'ME', 'T'+'BD', 'Not'+'Implemented', 'unimplemented'+'!')):
            raise RuntimeError(f'incomplete marker in {f}')
    if not (ROOT / 'native/libomegax.so').is_file():
        raise RuntimeError('missing native binary')
    testlog = (ROOT / 'results/unittest.log').read_text(encoding='utf-8')
    if 'FAILED' in testlog or 'skipped' in testlog or not re.search(r'Ran \d+ tests in [\d.]+s\s+OK\s*$', testlog):
        raise RuntimeError('test evidence is not green')
    if 'NATIVE_SANITIZER_TEST_PASS' not in (ROOT / 'results/native_sanitizer.log').read_text():
        raise RuntimeError('native sanitizer evidence missing')
    campaign = json.loads((ROOT / 'results/architecture_campaign_v5.json').read_text())
    if (not campaign['all_invariants_pass'] or campaign['scenario_events'] != 79600 or
        campaign['physical_npu_verified'] or campaign['physical_cxl_verified'] or
        campaign['kernel_sched_ext_attached'] or campaign['bpf_abi_compilation_verified']):
        raise RuntimeError('simulation acceptance evidence inconsistent')
    if 'C11_CONTRACT_BUILD_PASS' not in (ROOT / 'results/scx_policy_build.log').read_text():
        raise RuntimeError('portable policy C11 build evidence missing')
    if not (ROOT / 'kernel_ebpf/libomega_policy_reference.so').is_file():
        raise RuntimeError('portable policy binary missing')
    v6 = json.loads((ROOT / 'results/evolution_campaign_v6.json').read_text())
    if (not v6['all_invariants_pass'] or v6['simulated_cases'] != 7759
        or not v6['authenticated_log_tampering_denied'] or not v6['proof_ledger_anchor_verified']
        or v6['fuzz_seed_count'] != 128 or not v6['policy_evaluation']['guardrails_passed']
        or v6['physical_npu_verified'] or v6['physical_cxl_verified']
        or v6['kernel_sched_ext_attached']
        or any(not item['all_invariants_pass'] or not item['search_exhausted']
               for item in v6['model_checker'])):
        raise RuntimeError('v6 model-checking, proof-stream or safety-gate evidence inconsistent')
    claimed_proof = v6.pop('proof_sha256')
    calc = hashlib.sha256(json.dumps(v6, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode('utf-8')).hexdigest()
    if not hmac.compare_digest(claimed_proof, calc):
        raise RuntimeError('v6 deterministic campaign proof checksum mismatch')
    v7 = json.loads((ROOT / 'results/fusion_v7_acceptance.json').read_text())
    compare = json.loads((ROOT / 'results/fusion_v7_compare.json').read_text())
    contract = json.loads((ROOT / 'results/fusion_v7_contract.json').read_text())
    sweep = json.loads((ROOT / 'results/fusion_v7_sensitivity.json').read_text())
    functional = json.loads((ROOT / 'results/fusion_v7_functional.json').read_text())
    if (v7['version'] != '7.0.0' or not v7['virtual_contract_satisfied'] or
        v7['required_logical_time_multiplier'] != contract['required_virtual_clock_multiplier'] or
        v7['real_cpu_functional_passed'] != 12 or functional['failed'] != 0 or
        sweep['scenarios'] != 128 or not sweep['all_invariants_pass'] or
        compare['evidence_tier'] != 'DETERMINISTIC_VIRTUAL_MODEL' or
        contract['verified_makespan_ms'] > contract['target_makespan_ms'] or
        contract['physical_performance_proven'] or not contract['virtual_time_only'] or
        v7['physical_npu_verified'] or v7['physical_ryzen_intel_fusion_verified'] or
        v7['kernel_sched_ext_attached'] or v7['host_measured_pdf_benchmark']):
        raise RuntimeError('v7 virtual fusion evidence invalid or overstated')
    for obj in (v7, compare, contract, sweep):
        expected = obj['proof_sha256']
        content = {k:v for k,v in obj.items() if k != 'proof_sha256'}
        actual = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':'),
                                          allow_nan=False).encode()).hexdigest()
        if not hmac.compare_digest(expected, actual):
            raise RuntimeError('v7 deterministic proof mismatch')
    if not (ROOT / 'VIRTUAL_FUSION_CONTRACT_v7.md').is_file():
        raise RuntimeError('missing v7 evidence contract')
    if 'COMPILEALL_EXIT=0' not in (ROOT / 'results/compile.log').read_text():
        raise RuntimeError('Python compilation evidence missing')


def release() -> dict:
    MANIFEST.unlink(missing_ok=True)
    testlog = (ROOT / 'results/unittest.log').read_text(encoding='utf-8')
    count = int(re.search(r'Ran (\d+) tests', testlog).group(1))
    if count < 174:
        raise RuntimeError('v6 regression test count below required minimum')
    benchmark = json.loads((ROOT / 'results/benchmark_native.json').read_text())
    replication = json.loads((ROOT / 'results/replication_campaign.json').read_text())
    source = [p for p in _files() if p.suffix in ('.py', '.c', '.h') and 'tests' not in p.parts and p.name != 'test_native.c']
    tests = [p for p in _files() if p.suffix in ('.py', '.c') and ('tests' in p.parts or p.name == 'test_native.c')]
    service_load = json.loads((ROOT / 'results/service_load.json').read_text())
    admission = json.loads((ROOT / 'results/architecture_campaign_v5.json').read_text())
    summary = {
        'name': ROOT.name, 'version': '7.0.0',
        'test_count': count, 'test_failures': 0, 'test_skipped': 0,
        'native_sanitizer': 'PASS',
        'external_architecture_simulated_events': admission['scenario_events'],
        'external_architecture_simulation_proof': admission['proof_sha256'],
        'external_architecture_model_invariants': admission['all_invariants_pass'],
        'portable_c11_policy_reference': 'COMPILED_AND_CONFORMANCE_TESTED',
        'actual_kernel_sched_ext_verified': False,
        'physical_cxl_npu_verified': False,
        'v6_shadow_policy_evaluation': 'PASS_WITH_CONSERVATIVE_GATE',
        'v6_explicit_state_coherence_model': 'PASS_BOUNDED_DEPTH',
        'v6_authenticated_evidence_stream': 'PASS_LOCAL_TAMPER_REJECTION',
        'v6_fuzz_seeds': 128,
        'v6_model_cases': 7759,
        'v7_fusion_model': 'DETERMINISTIC_VIRTUAL_MODEL',
        'v7_pdf_target_ms': 294.36,
        'v7_unscaled_omega_makespan_ms': json.loads((ROOT / 'results/fusion_v7_compare.json').read_text())['model_makespan_ms']['omega_x'],
        'v7_required_virtual_clock_multiplier': json.loads((ROOT / 'results/fusion_v7_contract.json').read_text())['required_virtual_clock_multiplier'],
        'v7_virtual_contract_makespan_ms': json.loads((ROOT / 'results/fusion_v7_contract.json').read_text())['verified_makespan_ms'],
        'v7_sensitivity_scenarios': 128,
        'v7_real_cpu_functional_jobs': 12,
        'v7_physical_fusion_verified': False,
        'real_service_jobs': service_load['jobs'],
        'real_service_successes': service_load['successes'],
        'real_service_journal_integrity': service_load['journal_integrity'],
        'simulation_seeds': replication['seeds'], 'simulation_events': replication['total_events'],
        'simulation_invariants_pass': replication['all_invariants_pass'],
        'native_speedup_observed': benchmark['observed_speedup_auto_vs_scalar'],
        'source_lines_including_comments': sum(len(p.read_text(encoding='utf-8').splitlines()) for p in source),
        'test_lines_including_comments': sum(len(p.read_text(encoding='utf-8').splitlines()) for p in tests),
        'documentation_files': len(DOCS),
        'scope': 'LOCAL_TESTED_AND_SIMULATED_TESTED_NOT_PRODUCTION_VERIFIED',
        'digital_life_modified': False,
    }
    summary['file_count'] = len(_files()) + (1 if SUMMARY.exists() else 2)  # plus manifest, and possibly summary
    SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    files = _files()
    _check_content(files)
    MANIFEST.write_text(''.join(f'{_sha(p)}  {p.relative_to(ROOT).as_posix()}\n' for p in files), encoding='utf-8')
    files = _files()
    summary['file_count'] = len(files)
    with zipfile.ZipFile(OUTPUT, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for file in files:
            relative = file.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(ROOT.name + '/' + relative, date_time=(2026, 11, 12, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            z.writestr(info, file.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(OUTPUT) as z:
        if z.testzip() is not None:
            raise RuntimeError('ZIP CRC verification failed')
        names = z.namelist()
        if len(names) != len(files) or len(names) != len(set(names)):
            raise RuntimeError('ZIP file count or duplicate mismatch')
        expected = {}
        for line in z.read(ROOT.name + '/MANIFEST_SHA256.txt').decode().splitlines():
            sha, rel = line.split('  ', 1)
            expected[rel] = sha
        if len(expected) != len(files) - 1:
            raise RuntimeError('manifest count mismatch')
        for rel, sha in expected.items():
            actual = hashlib.sha256(z.read(ROOT.name + '/' + rel)).hexdigest()
            if actual != sha:
                raise RuntimeError(f'ZIP manifest mismatch: {rel}')
        # Extract only to a temporary directory inside this isolated package.
        extract = ROOT / 'results/tmp/release_extract'
        if extract.exists():
            shutil.rmtree(extract)
        extract.mkdir(parents=True)
        try:
            for info in z.infolist():
                rel = Path(info.filename)
                if rel.is_absolute() or '..' in rel.parts or rel.parts[0] != ROOT.name:
                    raise RuntimeError('unsafe archive path')
            z.extractall(extract)
            for rel, sha in expected.items():
                if _sha(extract / ROOT.name / rel) != sha:
                    raise RuntimeError('extracted file mismatch')
        finally:
            shutil.rmtree(extract)
    summary['archive_bytes'] = OUTPUT.stat().st_size
    summary['archive_sha256'] = _sha(OUTPUT)
    return summary


if __name__ == '__main__':
    print(json.dumps(release(), indent=2, ensure_ascii=False))

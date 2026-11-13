# Moduły i odpowiedzialności

| Moduł | Publiczny kontrakt | Funkcja |
|---|---|---|
| `omega_x.job_store` | `JobStore`, `validate_request`, `validate_tenant` | WAL, idempotencja, quota, claim, retry, recover, journal, integrity |
| `omega_x.service` | `LocalControlPlane`, `create_keys`, `load_keys` | Loopback API, autoryzacja tenantów, worker pool, graceful shutdown |
| `omega_x.client` | `OmegaClient`, `RemoteError` | Bezpieczny lokalny klient, submit/get/wait/cancel/metrics |
| `omega_x.executor` | `ExecutionRequest`, `LocalExecutor` | Proces potomny, hard timeout, affinity, SHA256/SAXPY/memory |
| `omega_x.real_policy` | `PhysicalPlanner`, `PhysicalExecutor` | Przydział do dozwolonego cpuset, brak domniemanego NPU |
| `omega_x.topology` | `detect_topology`, `classify_cpu` | Odczyt P/E z sysfs bez zgadywania |
| `omega_x.native` | `NativeKernels`, `NativeQueue` | CPU SAXPY, GEMM INT8, SPSC |
| `omega_x.bridge_v2` | `sign_request`, `verify_request`, `ReplayStore` | Podpisane koperty, TTL, anty-replay |
| `omega_x.ledger` | `EvidenceLedger` | Idempotentny ledger z łańcuchem SHA-256 |
| `omega_x.adapter` | `encode`, `decode` | Kontrakt JSON v1 dla modelu |
| `omega_x.runtime` | `OmegaRuntime` | Orkiestracja modelu i telemetrii |
| `omega_x.scheduler` | scheduler modelowy | Wirtualny harmonogram P/E/NPU |
| `omega_x.cache` | model cache | Partycjonowanie, hit/miss i izolacja |
| `omega_x.prefetch` | predykcja adresów | Markov i stride |
| `omega_x.fabric` | model komunikacji | Wirtualna magistrala i opóźnienia |
| `omega_x.simulation` | `DeterministicTwin` | Wstrzykiwanie awarii i inwarianty |
| `omega_x.replication` | `run_campaign` | Quorum i partycje 3/5/7 węzłów |
| `omega_x.cli` | `main` | CLI bez operacji repozytoryjnych |

`native/omega_native.c` jest jedynym źródłem natywnego rozszerzenia CPU. `kernel_ebpf/scx_omega_x.*` jest opcjonalnym profilem źródłowym bez automatycznego ładowania. `scripts/build_native.py`, `scripts/v4_campaign.py`, `scripts/release.py` dostarczają powtarzalne komendy. `benchmarks/service_load.py` wykonuje rzeczywiste lokalne żądania, a pozostałe benchmarki mierzą lokalne jądra.

## Nowe moduły v5

| Moduł | Publiczne punkty wejścia | Kontrakt |
|---|---|---|
| `omega_x.engineering_twin` | `Profile`, `TwinTask`, `Fault`, `DigitalTwin.run`, `run_multiseed_campaign` | Sprawdzone geometrycznie jednostki P/E/NPU, zasoby, terminy, awarie i hash wyniku |
| `omega_x.coherence_twin` | `Lease`, `CoherenceTwin.acquire_shared/acquire_exclusive/read/write/partition/heal/restart/report`, `run_coherence_campaign` | Odmowa niepotwierdzonej inwalidacji, SWMR, wersje, fencing, katalog ograniczony pamięciowo |
| `omega_x.scx_contract` | `policy_choice` | Stabilna abstrakcja opt-in wyboru kolejki P/E i kradzieży pracy |
| `kernel_ebpf/policy_reference.c/.h` | `omega_scx_choice` | C11 odpowiednik logiki fallback; **nie** kernel sched_ext |
| `scripts/v5_campaign.py` | `execute` | Weryfikacja trzech modeli 79 600 zdarzeń i budowa referencji C11 |

Schemat nowego wejścia: `schemas/engineering_twin.schema.json`.
Przykładowa koperta: `examples/engineering_twin_request.json`.

## Nowe kontrakty v6

| Ścieżka | Publiczne API | Gwarancja i zakres |
|---|---|---|
| `omega_x.policy_evolution` | `evaluate_policies(profile, task_scenarios, fault_scenarios, seeds)`, `PolicyEvaluationError` | Read-only porównanie dwóch polityk, limit 32 przypadków po 256 zadań, nieprzekraczanie bramek i fallback na kompatybilną |
| `omega_x.state_explorer` | `explore_coherence(nodes=2, depth=4, capacity=2)` | BFS małego modelu, zawsze weryfikuje SWMR i wersje; sprawdza także poprawność odmów |
| `omega_x.proof_stream` | `ProofStream(path, key, max_records=4096)`, `append`, `verify`, `IntegrityViolation` | Rekordy JSONL SHA-256 + HMAC, 32-bajtowy klucz, fsync i flock, opcjonalny niezależny anchor |
| `omega_x.engineering_twin` | `DigitalTwin.run(tasks, faults, policy='compat')` | Opcjonalna polityka `earliest_finish`; stary kontrakt i semantyka domyślna zachowane |
| `omega_x.cli` | `policy-evaluate`, `coherence-explore`, `proof-append`, `proof-verify` | Offline, brak ingerencji w istniejący runtime lub GitHub |
| `scripts/v6_campaign.py` | `run()` | Walidacja multi-seed, eksplorator, fuzz i negatywna próba naruszenia MAC |

## Moduły v7

`fusion_twin.py`: typowane profile i zadania, konserwacja budżetów cache/DRAM/mocy, odtwarzalne wyniki, analiza wrażliwości i solver czasu logicznego. `fusion_functional.py`: weryfikacja rzeczywistych CPU SHA-256, SIMD SAXPY, INT8 GEMM. `scripts/v7_campaign.py`: dowody akceptacji, deterministyczne fingerprinty i raporty JSON. Pełna specyfikacja: `VIRTUAL_FUSION_CONTRACT_v7.md`.

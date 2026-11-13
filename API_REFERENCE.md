# API OMEGA-X v6.0.0

## Adres i uwierzytelnianie

Tylko `http://127.0.0.1:<port>`; wszystkie ścieżki poza `/v1/health` wymagają `Authorization: Bearer <64 lowercase hex>` odpowiadającego kluczowi tenanta. Nagłówek `Host` musi dokładnie odpowiadać `127.0.0.1:<port>`. Brak CORS. Sekrety nie są częścią ZIP.

## Endpointy

| Metoda | Ścieżka | Odpowiedź |
|---|---|---|
| GET | `/v1/health` | 200 `{status:"ok"}` lub 503 `{status:"fault"}` |
| GET | `/v1/capabilities` | 200: rzeczywiste CPU, katalog operacji |
| GET | `/v1/metrics` | 200: statystyki wyłącznie własnego tenanta |
| POST | `/v1/jobs` | 202: nowe zadanie; 200: identyczny klucz idempotencji |
| GET | `/v1/jobs/{32-hex-id}` | 200: status i wynik własnego zadania |
| DELETE | `/v1/jobs/{32-hex-id}` | 200: anulowano QUEUED; 409: wykonanie już rozpoczęte |

`POST /v1/jobs` akceptuje JSON: `{"idempotency_key":"abc-001","kind":"sha256","size":4096,"timeout_s":5.0,"priority":"normal"}`. Opcjonalne `cpu` może wskazać tylko dozwolony identyfikator procesora. Operacje: `sha256`, `saxpy`, `memory`; żadnych komend użytkownika. Priorytety: `latency`, `normal`, `background`. Odpowiedź zawiera `job_id` i `status`.

Kody błędów: 400 `INVALID_REQUEST`, 401 `UNAUTHORIZED`, 404 `NOT_FOUND`, 409 `IDEMPOTENCY_CONFLICT` lub `JOB_NOT_CANCELLABLE`, 429 `CAPACITY_EXCEEDED`, 503 `SERVICE_UNAVAILABLE`. Treść błędu nie zawiera sekretów.

## Python API

`OmegaClient(key: bytes, port: int)` oferuje `submit(kind,size,...)`, `get(job_id)`, `wait(job_id,timeout_s)`, `cancel(job_id)`, `metrics()`, `capabilities()`, `health()`. Błędy HTTP są mapowane na `RemoteError(status,code)`. `LocalControlPlane(path, keys, workers, port)` ma `start()` i `stop()`.

## Kontrakt Digital-Life offline

Niezmieniony adapter v1 `encode/decode` i podpisany v2 `sign_request/verify_request` z HMAC-SHA256, TTL i nonce. Brak automatycznego wywołania Digital-Life; jest to wyłącznie przyszły punkt integracyjny.

## API offline — model zewnętrznej architektury v5

Uruchomienie `python3 -m omega_x.cli engineering-twin --request <path>` przyjmuje
pliki JSON do **262144 bajtów**. `schema_version=1`, wymagane pola `seed`,
`profile`, `tasks`, `faults`; nieznane i zdublowane pola są odrzucane. Struktura
pojedynczego zadania: `task_id`, `tenant`, `kind` (`VECTOR|BACKGROUND|TENSOR`),
`ops`, `transfer_bytes`, `arrival_ns`, `deadline_ns`. Awaria ma `kind`
(`p_down|e_down|npu_down|fabric_down|thermal_derate`), `start_ns`, `end_ns`.
Kontrakt jest dokumentowany także w `schemas/engineering_twin.schema.json`.

Przykład:

```bash
python3 -m omega_x.cli engineering-twin --request examples/engineering_twin_request.json
python3 -m omega_x.cli engineering-campaign --seed 20261112 --seeds 50 --jobs 48
python3 -m omega_x.cli coherence-campaign --seed 20261112 --seeds 50 --rounds 120
```

Odpowiedź zawiera `evidence_tier=SIMULATED_TESTED`, rozkład statusów
`completed/deadline_miss/unavailable`, zdarzenia per zadanie, `peak_power_watts`,
`latency_p99_ns`, pięć niezmienników oraz `proof_sha256`. Ten hash jest integralnością
powtórzenia modelu, nie podpisem zewnętrznego urządzenia. Dotychczasowe API
`/v1/jobs` pozostaje kompatybilne i nie zleca zadań cyfrowemu bliźniakowi.

## CLI v6 — wersjonowany kontrakt offline

- `python3 -m omega_x.cli policy-evaluate --seed 3 --scenarios 4 --jobs 16`: JSON zawiera `selected`, `candidate_guardrails_passed`, oddzielne `cases`, sumy makespan, `proof_sha256`, `evidence_tier=SIMULATED_TESTED`, `operator_approval=false`, `auto_deployment=false`.
- `python3 -m omega_x.cli coherence-explore --nodes 3 --depth 4 --capacity 2`: JSON z `states`, `transitions`, `rejected_stale_leases`, `all_invariants_pass`, `proof_sha256`. Zbiór wejściowy jest ograniczonym modelem koherencji, nie interfejsem PCIe/CXL.
- `python3 -m omega_x.cli proof-append PATH EVENT_JSON`: przyjmuje maksymalnie 8192 bajtów i dokładnie pola `{ "kind": "POLICY_REVIEW", "payload": { "result": "approved_for_review" } }`; zwraca `sequence`, `head`, `bytes_written`. Wymaga `OMEGA_X_PROOF_KEY_HEX` z 64 małych znaków hex; plik i katalog prywatne.
- `python3 -m omega_x.cli proof-verify PATH --head 64_HEX --count 1`: weryfikuje każdy rekord HMAC, indeks, poprzednią głowę, kanonizację i opcjonalny zewnętrzny checkpoint. Exit 2 przy odrzuceniu, 0 po sukcesie.

**Zgodność:** `/v1/jobs`, `bridge_v2` i oryginalny `engineering-twin` pozostają bez zmian protokołu. Nowa polityka jest opt-in; nie zmienia działania domyślnego planisty ani serwera.

## API CLI v7.0.0 — virtual fusion

- `fusion-compare`: 12 zadań źródłowych, trzy profile, makespan, przyspieszenia i różnice względem PDF.
- `fusion-solve --max-multiplier N`: minimalny jawny mnożnik czasu wirtualnego z zakresu `[1,N]`, maksymalnie 256. Wartość nie jest fizycznym taktowaniem.
- `fusion-run REQUEST`: JSON według `schemas/fusion_v7.schema.json`, bez zduplikowanych kluczy, do 256 KiB i 256 zadań. Akceptuje trzy nazwy architektur, dwa algorytmy kolejkowania i trzy rodzaje awarii.
- `fusion-campaign --seeds N --seed S`: odtwarzalna analiza wrażliwości, 1–512 scenariuszy.
- `fusion-functional`: prawdziwe, małe jądra CPU i kontrola poprawności; nie jest benchmarkiem pełnego źródłowego obciążenia.

Pełny kontrakt, jednostki i ograniczenia: `VIRTUAL_FUSION_CONTRACT_v7.md`.

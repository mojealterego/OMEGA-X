# OMEGA-X v7.0.0 — runtime CPU i wirtualna fuzja Ryzen/Intel

**Profil wydania:** lokalne oprogramowanie Linux x86-64; Python 3.11+, C11, bez zależności Python wymagających pobrania z sieci. Produkt obejmuje działające API, kolejkę, realne wykonanie CPU, natywne jądra i deterministyczne modele. Nie jest fizyczną fuzją procesorów AMD Ryzen 7 9850X3D oraz Intel Core Ultra 9 285K.

## Komponenty

- `omega_x/model.py`, `scheduler.py`, `runtime.py`, `cache.py`, `prefetch.py`, `fabric.py`, `simulation.py`: deterministyczny model domen P/E/NPU, pamięci, magistrali i awarii.
- `omega_x/executor.py`, `real_policy.py`, `topology.py`, `host.py`: rzeczywiste zadania CPU Linux z ograniczonym katalogiem operacji, affinity i deadline.
- `native/omega_native.c`, `omega_x/native.py`: C11 SIMD SAXPY, INT8 GEMM, SPSC. Kod CPU działa na sprzęcie z instrukcjami faktycznie dostępnymi na hoście.
- `omega_x/job_store.py`, `service.py`, `client.py`: izolowana lokalna usługa wielotenantowa z autoryzacją, kolejką WAL, retry, recovery, audytem i klientem.
- `omega_x/bridge_v2.py`, `ledger.py`, `adapter.py`: podpisany kontrakt offline do ewentualnego przyszłego podłączenia Digital-Life.
- `omega_x/replication.py`: symulator quorum i awarii 3/5/7 węzłów.
- `kernel_ebpf/`: źródło opcjonalnego sched_ext, niewgrywane do jądra, nieweryfikowane na bieżącym hoście.

## Uruchomienie offline

```bash
python3 scripts/build_native.py
python3 -m unittest discover -s tests -v
python3 -m omega_x.cli host
python3 -m omega_x.cli execute --kind sha256 --size 1048576
python3 -m omega_x.cli simulate --seed 20261112 --rounds 2000
python3 scripts/v4_campaign.py
```

## Usługa wielotenantowa na loopback

Najpierw wygeneruj sekrety (tworzy plik 0600, nie nadpisuje istniejącego):

```bash
python3 -m omega_x.cli init-keys ./keys.json --tenants alpha beta
mkdir -m 700 -p ./state
python3 -m omega_x.cli serve --keys-file ./keys.json --state-dir ./state --port 8765 --workers 2
```

W drugim terminalu (ta sama maszyna):

```bash
python3 -m examples.submit_job --keys-file ./keys.json --tenant alpha --port 8765 --kind sha256 --size 1024
```

`examples/submit_job.py` można również uruchomić z katalogu głównego przez `python3 examples/submit_job.py` po ustawieniu `PYTHONPATH=.`. Tokeny nie są publikowane ani dołączone do ZIP. Serwer odmawia nasłuchu poza `127.0.0.1` i nigdy nie wykonuje dowolnych komend.

## Dowody i granice

Lokalna regresja: 104 testy PASS, 0 pominięć; C11 ASan/UBSan PASS; 50 000 zdarzeń deterministycznych w 50 nasionach; 18 rzeczywistych zadań CPU przez API zakończonych sukcesem. Dowody są w `results/`. Benchmarki mierzą host uruchomieniowy, nie Ryzen/Intel z PDF. `sched_ext` i NPU pozostają odrębnymi, niepotwierdzonymi profilami sprzętowymi. Repozytorium Digital-Life nie zostało zmienione.

## Dokumentacja

13 głównych dokumentów: `ARCHITECTURE.md`, `ENGINEERING_SPECIFICATION.md`, `BEYOND_MAXIMUM_INNOVATIONS.md`, `MODULE_REFERENCE.md`, `API_REFERENCE.md`, `SECURITY_ARCHITECTURE.md`, `BUILD_AND_DEPLOYMENT_GUIDE.md`, `TESTING_AND_VALIDATION.md`, `DEPENDENCIES_AND_LICENSES.md`, `DIGITAL_LIFE_COMPATIBILITY.md`, `INTEGRATION_BLUEPRINT.md`, `PRODUCTION_READINESS_REPORT.md` oraz ten plik. Licencja MIT dla własnego kodu Python/C11, GPL-2.0 dla oddzielnych źródeł sched_ext.

## Rozszerzenie v5.0.0 — zewnętrzna architektura bez fizycznych urządzeń

`omega_x.engineering_twin` jest skończonym modelem zdarzeń i zasobów z domenami P/E/NPU,
jedną magistralą serializującą transfery, limitami mocy, deadline, ograniczoną sprawiedliwością
tenantów, deterministycznym jitterem i awariami. Wykonuje **realne obliczenia modelu**,
nie instrukcje sprzętowego NPU. `omega_x.coherence_twin` symuluje katalog pamięci typu
CXL, SWMR, snoop, fencing, restart, podział sieci i blokady przy braku potwierdzenia
unieważnienia. `kernel_ebpf/policy_reference.c` jest skompilowaną i przetestowaną
implementacją referencyjną C11 do porównania decyzji kolejek z Python, nie binarium BPF.

```bash
python3 -m omega_x.cli engineering-twin --request examples/engineering_twin_request.json
python3 -m omega_x.cli engineering-twin --seed 17 --jobs 60 --faults
python3 -m omega_x.cli engineering-campaign --seeds 50 --jobs 48
python3 -m omega_x.cli coherence-campaign --seeds 40 --rounds 120
python3 scripts/v5_campaign.py
```

Dowody `results/architecture_campaign_v5.json` dotyczą **79 600 zdarzeń/przypadków modelowych**
(9600 przydziałów, 20000 operacji koherencji i 50000 zdarzeń quorum) i nie
stanowią benchmarków rzeczywistego Ryzen/Intel, CXL ani NPU. Regresja 132 testów
łączy nowy zakres ze wszystkimi dotychczasowymi testami v4. `scripts/release.py`
sprawdza kompletność wyników przed pakowaniem.

Wymóg sprzętu zewnętrznego **zastąpiono zdefiniowaną kwalifikacją symulacyjną**;
nie nadano fikcyjnego `PRODUCTION_VERIFIED`, `CXL_VERIFIED` ani `KERNEL_ATTACHED`.
Przeprowadzenie ewentualnego podłączenia Digital-Life nie jest częścią tej paczki.

## Wydanie v6.0.0 — kontrolowana ewolucja i dowody integralności

Nowe funkcje są działającymi komponentami lokalnego oprogramowania, nie deklaracją dodatkowych tranzystorów ani rzeczywistego przyspieszenia sprzętu. Wersja zachowuje API HTTP v1 i kontrakt HMAC v2 bez migracji stanu.

- `omega_x.policy_evolution`: porównanie polityki kompatybilnej i polityki najwcześniejszego przewidywanego zakończenia na **identycznych** profilach zasobów, obciążeniach, awariach i ziarnach losowania. Kandydat może zostać wybrany wyłącznie wtedy, gdy nie pogarsza p99, liczby niedotrzymanych terminów i dostępności w żadnym scenariuszu oraz obniża łączny modelowany makespan. W przeciwnym razie wybierana jest polityka bazowa.
- `omega_x.state_explorer`: skończona eksploracja stanów katalogu koherencji z wyłącznymi zapisami, stale leases, restartem, podziałami sieci i weryfikacją monotoniczności wersji. Zakres dowodu jest **ograniczony głębokością modelu**.
- `omega_x.proof_stream`: append-only JSONL z HMAC-SHA256, SHA-256, monotonicznym `seq`, `flock`, fsync, kontrolą 0600/0700 i opcjonalnym zewnętrznym zakotwiczeniem (head + liczba rekordów). Dziennik nie jest sam w sobie niezależnym WORM.

```bash
python3 -m omega_x.cli policy-evaluate --seed 20261112 --scenarios 16 --jobs 24
python3 -m omega_x.cli coherence-explore --nodes 3 --depth 4
python3 scripts/v6_campaign.py
python3 -m unittest discover -s tests -v
```

Do użycia strumienia dowodów operator sam wytwarza i przechowuje sekret 256-bitowy, który **nie** jest dołączony do paczki:

```bash
mkdir -m 700 -p "$HOME/omega-x-evidence"
export OMEGA_X_PROOF_KEY_HEX="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
printf '{"kind":"POLICY_REVIEW","payload":{"decision":"reviewed"}}\n' > "$HOME/omega-x-evidence/event.json"
python3 -m omega_x.cli proof-append "$HOME/omega-x-evidence/events.jsonl" "$HOME/omega-x-evidence/event.json"
python3 -m omega_x.cli proof-verify "$HOME/omega-x-evidence/events.jsonl"
```

Dla weryfikacji po odtworzeniu archiwum należy zachować sekret oraz **niezależnie** zapamiętać zwrócony `head` i `sequence`; parametr `--head` wykrywa podmianę głowy dziennika. Przykład nie wysyła klucza ani wyników poza host. Przy zmianie sekretu istniejący dziennik nie zostanie zweryfikowany.

**Dowody v6:** `results/evolution_campaign_v6.json`, `results/v6_benchmark.json`, `results/unittest.log`. Dodatkowy model nie uzyskuje dostępu do urządzeń NPU/CXL ani do jądrowego `sched_ext`; pozostaje read-only shadow evaluation. Bramka wyboru nie wykonuje zmian produkcyjnych, a wynik ``selected=compat`` w kampanii mieszanej jest poprawnym wynikiem odmowy nieudokumentowanej optymalizacji.

## v7.0.0 — Wirtualny odpowiednik parametrów fuzji Ryzen/Intel

**Kontrakt, zakres i uczciwa interpretacja wyników:** `VIRTUAL_FUSION_CONTRACT_v7.md`.
Nowy model nie odtwarza wartości z PDF przez wpisanie ich jako wyników: porównuje trzy jawne profile i symuluje 12 zadań z zasobami P/E/NPU, pamięcią i limitem mocy. Solver osiąga progi PDF wyłącznie po zadeklarowanym skalowaniu czasu logicznego; nie jest to sprzętowa przewaga 3×. `fusion-functional` uruchamia prawdziwe, małe jądra CPU dla 12 klas zadań i sprawdza poprawność wyników.

```bash
python3 -m omega_x.cli fusion-compare
python3 -m omega_x.cli fusion-solve --max-multiplier 16
python3 -m omega_x.cli fusion-campaign --seeds 128
python3 -m omega_x.cli fusion-functional
python3 -m omega_x.cli fusion-run examples/fusion_v7_custom_request.json
```

Dowody: `results/fusion_v7_*.json`. Nie twierdzimy, że fizycznie uzyskano 72,9 TOPS, 128 MiB SRAM L3 lub pomiary porównawcze Ryzen/Intel.

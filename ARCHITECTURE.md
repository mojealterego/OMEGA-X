# Architektura OMEGA-X v6.0.0

## Dwie jawnie rozdzielone domeny

1. **Model matematyczno-symulacyjny:** profile P/E/NPU, 4-tier cache, partycjonowanie dróg, Markov/stride, DSQ i model opóźnień. Wynik jest funkcją wejścia, konfiguracji i seeda; nie jest pomiarem krzemu.
2. **Fizyczny runtime CPU:** odczyt topologii `/sys/devices/system/cpu`, cpuset procesu, operacje SHA-256/SAXPY/pamięć w potomnych procesach Linux, natywne C11 i rzeczywisty zegar monotoniczny.

## Lokalny control plane

```text
Owner CLI / OmegaClient
       | loopback HTTP + per-tenant bearer key
       v
HTTP validation + tenant authorization + idempotency
       | bounded request and queue
       v
SQLite WAL [jobs, tenant_turns, journal, counters]
       | transactional claim / fair tenant turns
       v
Worker pool (1..16) -> LocalExecutor -> child process with CPU affinity
       | result or retry/backoff -> SQLite WAL
       v
Tenant-scoped status / metrics / cancellation
```

Przyjmowane są wyłącznie trzy operacje obliczeniowe; nie istnieje interfejs do shell, plików dowolnych, zewnętrznego HTTP, pobierania zależności ani automatycznego deploy. Baza danych i katalog stanu są prywatne (0600/0700). Tokeny 256-bitowe przechowywane poza archiwum.

## Stany i odzyskiwanie

`QUEUED -> RUNNING -> SUCCEEDED` lub `RUNNING -> QUEUED` po błędzie i backoff, maksymalnie 3 próby; następnie `FAILED`. `QUEUED -> CANCELLED` jest dozwolone tylko przed wykonaniem. Restart wykrywa `RUNNING` i bezpiecznie przenosi do `QUEUED` albo `FAILED`, zachowując historię. Semantyka wykonania: **at least once**; wynik operacji CPU jest deterministyczny dla argumentów, więc ponowienie jest bezpieczne. Nie deklarujemy exactly-once dla zewnętrznych skutków ubocznych.

## Audyt i spójność

Wszystkie przejścia zapisywane są atomowo z SHA-256 łańcuchem zdarzeń; startup sprawdza `PRAGMA quick_check` i spójność łańcucha. Jest to detekcja przypadkowej/nieuprawnionej modyfikacji, nie sprzętowy WORM ani odporność na przeciwnika mającego pełny zapis do pliku i możliwość przeliczenia łańcucha.

## Granice systemu

`kernel_ebpf` jest opcjonalnym kodem źródłowym wymagającym zgodnego sched_ext/libbpf/BTF. Domyślny runtime wykorzystuje Linux affinity bez ładowania eBPF. Brak możliwości stworzenia dodatkowych fizycznych rdzeni, SRAM, magistrali CXL czy NPU przez samo oprogramowanie.

## Rozszerzona architektura deterministycznych bliźniaków v5

```text
Wersjonowany JSON v1 --> ścisła walidacja (duplikaty pól = reject)
     |                                   |
     v                                   v
DigitalTwin [virtual P/E/NPU]     CoherenceTwin [SWMR directory]
  |  - per-lane availability        |  - version / token / epoch
  |  - fair per-arrival tenants     |  - snoop + revoke with ACK
  |  - shared fabric queue          |  - fail-closed partitions
  |  - power admission              |  - bounded directory / restart
  v                                 v
Deterministic reports SHA-256 --> v5 multi-seed campaign
     |
     +-- quorum twin 3/5/7 nodes (independent safety model)
     +-- C11 policy reference (compared with Python)
     +-- READ-ONLY sched_ext capability preflight
```

Czas w modelu to całkowite nanosekundy; nie pochodzi z realnego zegara systemowego.
Kolejność przy tej samej dacie dostarczenia jest round-robin po nazwie tenanta,
a potem stabilna po `task_id`. W obrębie domeny wygrywa najwcześniej dostępna
wirtualna jednostka. Domena tensorowa korzysta z NPU jedynie, gdy taki **wirtualny**
zasób jest dostępny; awaria przekierowuje do CPU. Zasilanie jest ograniczane
przez rezerwacje zajętości w przedziałach [start,end), nie przez umowne mnożniki
przyspieszenia. Interfejs źródeł eBPF nadal jest izolowany i domyślnie nieaktywny.

## Warstwa assurance v6 — bez bocznych ścieżek wykonania

```text
Profile + Tasks + Faults + Seed
              |
              v
       DigitalTwin(compat) --------+ 
              |                    |
              v                    |
       DigitalTwin(earliest_finish)|
              |                    |
              +--> Nonregression Gate --> Decision Proof SHA-256
                                          |
                                          +--> CLI JSON / manual operator review

CoherenceTwin -> bounded explicit-state BFS -> invariant summary + SHA-256
Owner events  -> ProofStream(JSONL, MAC, fsync) -> optional external anchor
```

Zmiana polityki nie zmienia liczby rdzeni, szybkości kanałów, dostępnych akceleratorów ani budżetu energetycznego. `evaluate_policies` nigdy nie wywołuje API fizycznego planisty. `coherence-explore` nigdy nie dołącza BPF, nie używa CXL ani nie zapisuje w repozytoriach. Dowody SHA-256 są odtwarzalne przy tych samych wejściach; autentyczność pliku JSONL jest weryfikowana osobnym kluczem MAC. Brak podstaw do podnoszenia statusu z `SIMULATED_TESTED` na `PRODUCTION_VERIFIED`.

**Granice zaufania:** CLI otrzymuje modelowane dane, dziennik wymaga prywatnego katalogu i sekretu operatora. Istniejący, zamknięty HTTP control plane zachowuje starą semantykę. Brak nowych portów, uprawnień i procesów wdrożeniowych.

## Architektura v7 — wirtualny performance twin

`fusion_twin.py` realizuje osobny, deterministyczny harmonogram dwóch etapów: DRAM (jeden współdzielony zasób) oraz CPU/NPU (oddzielne domeny i rdzenie). Partycje cache są ograniczone budżetem, SMT zwiększa liczbę logicznych wątków bez tworzenia dodatkowej mocy obliczeniowej, a ograniczenie mocy sprawdza nakładające się przedziały. Zasoby są jawnie konfigurowalne; źródłowe cele PDF nie są podawane jako obliczone rezultaty. `fusion_functional.py` weryfikuje małe realne jądra CPU. `VIRTUAL_FUSION_CONTRACT_v7.md` dokumentuje równania, ograniczenia i statusy dowodowe.

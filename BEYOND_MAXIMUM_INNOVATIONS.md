# Zaimplementowane optymalizacje i ich dowody

## 1. Rzeczywiste jądra CPU

C11 `omega_native.c`: detekcja ISA i dispatch scalar/AVX2/AVX-512, natywne SAXPY, dokładne GEMM INT8 z akumulacją INT64 oraz bezblokadowa kolejka SPSC. Implementacje porównywane z niezależnymi wynikami referencyjnymi. `results/benchmark_native.json` i `results/int8_benchmark.json` zawierają pomiary bieżącego hosta.

## 2. Cache i predykcja

Deterministyczny model rezerwacji P/E (12/4), kontrolowane pożyczanie niewykorzystanych dróg, Markov/stride prefetch oraz testy izolacji. Te modele nie modyfikują fizycznej pamięci cache procesora i nie dowodzą realnych 128 MiB L3.

## 3. Odporność wykonawcza

Trwałe przydzielanie zadań, fair turns między tenantami, limitowane kolejki, odtwarzanie po awarii, deterministyczny jitter i kontrolowane zamknięcie. Hash-chain z kontrolą przy starcie. Fail-closed przy awarii bazy. Testy `test_v4_*.py` obejmują rzeczywiste procesy, HTTP, awarie i niepoprawne dane.

## 4. Bezpieczeństwo i koszt

Oddzielne tokeny tenantów, HMAC v2 dla offline Digital-Life, 0600/0700, walidacja Host, limit body, odrzucenie powtarzanych kluczy JSON, brak dowolnych poleceń i zewnętrznej komunikacji. Brak płatnych API, kont chmurowych i zewnętrznych usług w ścieżce wykonania.

## 5. Granica dowodowa

Nie deklarujemy udowodnionej przewagi nad wszystkimi produktami rynkowymi ani parametrów „72,9 TOPS”/„sub-ms tail latency” w realnym systemie. Benchmarki są lokalne i mierzalne, a symulacje mają oddzielny status. `sched_ext` ma źródła, lecz bez potwierdzenia zgodności ABI i uruchomienia w jądrze. Takie rozdzielenie jest wymaganiem rzetelnej inżynierii, nie defektem raportowania.

## Wdrożenia v5: praca z ograniczeniami zamiast fikcyjnej wydajności

1. **Przydział zasobów ze sprawdzaniem mocy** — `engineering_twin.py::_power_safe`
   wykrywa naruszenia budżetu na wszystkich punktach granicznych rezerwacji i
   deterministycznie przesuwa wykonanie do bezpiecznego przedziału.
2. **Odtwarzalne okna awarii** — `Fault` + `_next_safe`: niedostępność NPU,
   P, E, fabric i obniżona sprawność termiczna. Wymuszenie `deadline_miss`
   zamiast fałszywego sukcesu przekraczającego termin.
3. **SWMR z fencingiem** — `coherence_twin.py`: wersje, epoki, atomowe odmowy,
   detekcja przestarzałych lease, partycje i bezpieczne zwalnianie miejsca
   w katalogu. Wykryty testem RED problem unieważniania zdalnej kopii przy
   eviction został usunięty przed wydaniem.
4. **Podwójna implementacja decyzji kolejek** — `policy_reference.c` oraz
   `scx_contract.py`: 20 000 losowych porównań C11/Python przy wymuszeniu
   jawnej zgody na planowanie. Referencja nie jest programem BPF.
5. **Granice liczbowe i JSON** — typy całkowite, odrzucanie bool jako integer,
   ograniczenia pamięci i liczby zdarzeń oraz SHA-256 dowodu powtórzeń.

Wszelkie przewagi odnoszą się do **niezmienników, testowalności i bezpieczeństwa
modelu**. Nie prezentujemy marketingowego „przyspieszenia nad Ryzen/Intel” bez
porównania sprzętowego, którego nie wykonano.

## 7. Proof-carrying safe policy evolution (v6)

**Kod:** `omega_x/engineering_twin.py`, `omega_x/policy_evolution.py`. Jest to rozszerzenie o wybór polityki pod kontrolą niezmienników, a nie dowód wydajności ponad fizyczne granice mikroarchitektury. Dwa modele przydziału wykonują te same zadania, z identycznym ziarnem i ograniczeniami. W kontrolowanym teście przeciążenia 1 rdzenia P + 4 rdzeni E model skrócił makespan z 8000 ns do 3334 ns; **nie jest to zmierzony zysk sprzętowy**. Kampania 24 scenariuszy wymusiła bezpieczny wybór `compat`, gdy kandydat nie zaliczył wymagań regresji. `test_shadow_guard_rejects_regression` wprost potwierdza skuteczność odmowy dla przykładu z gorszym p99.

## 8. Bounded model checking i wykrywanie starych lease

**Kod:** `omega_x/state_explorer.py`. Deterministyczne przejścia węzłów katalogu, trybów S/M, partycji, naprawy i restartu. Weryfikacja SWMR, monotoniczności numerów wersji, limitów pamięci i odmowy odczytu/zapisu nieaktualnym lease. Wynik jest zakończoną eksploracją zdefiniowanego skończonego modelu; nie twierdzi o bezpieczeństwie pełnej fizycznej sieci CXL.

## 9. Uwierzytelnione dowody, kontrola współbieżności i rollback detection

**Kod:** `omega_x/proof_stream.py`, `omega_x/cli.py`. Dyskowy append-only SHA-256/HMAC-SHA256, zewnętrzny anchor, `flock`, `fsync`, `O_NOFOLLOW`, ścisły JSON i limity. Testy wykrywają modyfikację, fałszywy klucz, uszkodzony ogon, symlink, nieprawidłowe dane i wyścigi zapisu. Zaufanie do dowodów zależy od ochrony klucza i niezależnego przechowania punktu zakotwiczenia; nie jest to certyfikacja ani zewnętrzny WORM.

**Wyniki odtwarzalne:** `results/evolution_campaign_v6.json`, `results/unittest.log`, `results/v6_benchmark.json`. Nie twierdzimy, że istnieje absolutna przewaga ponad wszystkie implementacje; porównania odnoszą się wyłącznie do jawnych baseline, modelu i hosta testowego.

## v7 — wirtualny kontrakt i jawne ograniczenia

Przeprowadzono modelowanie 12-zadaniowej fuzji Ryzen/Intel z kontrolą zasobów, testami wrażliwości i solverem czasu logicznego. Przyspieszenie syntetyczne nie jest przyspieszeniem sprzętu; mnożnik 3× stanowi wprost ujawnione założenie. Funkcjonalne jądra CPU sprawdzają poprawność wyników dla klas zadań bez symulowania obecności fizycznego NPU.

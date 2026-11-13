# Weryfikacja OMEGA-X v7.0.0 — zakres dowodowy

## Wykonane testy

- `python -m unittest discover -s tests -v`: **156/156 PASS, 0 skipped, 0 failed**. Log: `results/unittest.log`.
- `python -m compileall -q omega_x tests scripts benchmarks examples kernel_ebpf`: PASS. Log: `results/compile.log`.
- `scripts/build_native.py`: C11 `-Wall -Wextra -Werror` PASS. Log: `results/build_native.log`.
- ASan/UBSan C11 SPSC 200000 elementów, SIMD, INT8, bounds: PASS. Log: `results/native_sanitizer.log`.
- `scripts/v4_campaign.py`: **50 seedów, 50 000 zdarzeń**, wszystkie niezmienniki quorum PASS; profil wyłącznie symulacyjny. `results/replication_campaign.json`.
- `omega_x.cli simulate --rounds 2000`: conservation, bounded retries i checkpoint integrity PASS. `results/simulation.json`.
- `benchmarks/service_load.py`: **18/18 rzeczywistych zadań SHA-256 CPU przez HTTP**, 3 tenantów, 3 workerów, audyt integralny. `results/service_load.json`.
- `benchmarks/native_benchmark.py`, `int8_benchmark.py`: wyniki pomiarów na hoście, poprawność porównana z referencją; brak gwarancji przenoszenia na inne CPU.

## Zakres testów

Testy obejmują: walidację wejścia, autoryzację, izolację tenantów, SQL injection, symlinki i tryby dostępu do sekretów, konflikt idempotencji, współbieżne zapisy, fair scheduling, retry i recovery, ataki na hash-chain, fail-closed, HTTP E2E, SIGTERM, realny proces CPU i sanitizer. Testy eBPF są ograniczone do statycznego preflight — **nie uruchomiono sched_ext w jądrze**. NPU, CXL i rzeczywiste wielohostowe klastry nie były fizycznie dostępne; nie nadano im statusu zweryfikowanego sprzętu.

## Reprodukowalność

Wyniki deterministycznego modelu można odtworzyć z seedami i profilami. Pomiary hosta są zależne od zegara, CPU, OS i obciążenia. `MANIFEST_SHA256.txt` wiąże zawartość archiwum, a CRC ZIP i ponowne rozpakowanie są sprawdzane przed wydaniem. Żaden wynik syntetyczny nie jest oznaczany jako realny pomiar wydajności Ryzen/Intel.

## Kampania v5 — bezpośrednio wykonana w odizolowanym katalogu

- **156/156 PASS**: regresja `python3 -m unittest discover -s tests -v`.
- Kompilacja składni Python: `python3 -m compileall` — PASS.
- **100 seedów × 96 zadań = 9600** zdarzeń przydziału domen i magistrali;
  wszystkie pięć sprawdzanych niezmienników PASS.
- **100 seedów × 200 zdarzeń = 20 000** zdarzeń katalogu koherencji;
  wszystkie sprawdzane niezmienniki PASS; 1637 oczekiwanych odmów
  fail-closed podczas braku potwierdzenia.
- **50 seedów × 1000 = 50 000** zdarzeń symulatora quorum;
  niezmienniki replikacji PASS. Łącznie **79 600** zdarzeń/przypadków.
- **20 000** losowych porównań C11/Python wyboru kolejki planisty.
- Weryfikacja wielokrotnego odtwarzania tego samego seeda: zgodny hash
  raportu i te same liczby decyzji.

Logi: `results/unittest.log`, `results/architecture_campaign_v5.json`,
`results/scx_policy_build.log`, `results/scx_preflight_v5.json`.
Wszystkie ns/watty/p99 z kampanii są **założeniami wirtualnymi**, nie pomiarami
fizycznego hosta. Fizyczne testy CPU i HTTP z v4 pozostają w `results/` jako
dowody wcześniejszego zakresu. Programu eBPF nie załadowano.

## Regresja i kampania v6.0.0

- Zestaw `unittest` po rozszerzeniach: **156/156 PASS**, zero pominięć; `results/unittest.log` zawiera surowe wyniki komend.
- Lokalna kompilacja Python i biblioteki natywnej C11 z `-Werror`: **PASS**. ASan/UBSan C11: **PASS**; brak wykrytych błędów w dostarczonym zakresie.
- Ponownie wykonana kampania v5: **79 600** modelowanych operacji, w tym 9600 przydziałów zasobów, 20 000 przypadków koherencji, 50 000 zdarzeń quorum; wszystkie badane niezmienniki PASS. Wynik w `results/architecture_campaign_v5.json`.
- Kampania v6: **7759** modelowanych przypadków (24 × 24 = 576 zadań cieniowych, 7055 przejść BFS, 128 ziarna fuzz); dwukrotne uruchomienie tych samych scenariuszy potwierdziło deterministyczność. Weryfikacja 16 rekordów HMAC, modyfikacja jednego rekordu poprawnie odrzucona. `results/evolution_campaign_v6.json`.
- Dwukrotne porównanie `policy_evolution` daje ten sam `proof_sha256`. W kontrolowanym kontrprzykładzie `earliest_finish` traci warunek p99 i zostaje odrzucony. Zysk 8000 → 3334 ns to wyłącznie konkretny model 1P/4E, bez potwierdzenia na CPU AMD/Intel.
- Nie przeprowadzono wgrania sched_ext do jądra, sprzętowej fuzji CPU ani uruchomienia na fizycznym NPU/CXL. `LOCAL_TESTED` dotyczy rzeczywistych procesów CPU i biblioteki; `SIMULATED_TESTED` dotyczy modeli wirtualnych.

Pełna kontrola końcowa ZIP obejmuje SHA-256 manifestu, CRC i ponowne wykonanie testów z nowo rozpakowanego archiwum. Liczby testów w nagłówkach wydań historycznych poniżej odnoszą się do ówczesnych wersji, a nie do obecnej końcowej regresji.

## Testy v7.0.0

Wprowadzono 18 nowych testów kontraktów, losowych niezmienników, deterministyczności, awarii NPU/DRAM, walidacji CLI, wrażliwości i rzeczywistych jąder CPU. Kampania `scripts/v7_campaign.py` zapisuje modelowe porównanie, kontrakt logiczny, 128 wariantów założeń i 12 małych rzeczywistych zadań CPU. Raport końcowy: `results/fusion_v7_acceptance.json`. Szczegóły statusów i ograniczeń: `VIRTUAL_FUSION_CONTRACT_v7.md`.

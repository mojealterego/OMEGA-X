# Specyfikacja inżynieryjna v6.0.0

## Kontrakty liczbowe

- `ExecutionRequest.kind` ∈ {`sha256`,`saxpy`,`memory`}; `size` całkowite od 1 do 16 MiB; `cpu` opcjonalny indeks z dozwolonego cpuset.
- `timeout_s` skończone [0.05,30]; maksymalnie 16 workerów i 65 536 zadań oczekujących (konfigurowalne, domyślnie 256).
- Klucz tenanta: 256-bit, unikalny; tenant `[A-Za-z0-9_-]{1,64}`; idempotency key `[A-Za-z0-9_.:-]{1,128}`.
- Body HTTP do 8192 bajtów; odpowiedź klienta do 65536 bajtów; host wyłącznie `127.0.0.1`.
- `priority` ∈ {latency, normal, background}; fairness według ostatniego obsłużonego tenanta, następnie priorytet i FIFO w obrębie tenanta.

## Transakcje

`BEGIN IMMEDIATE` serializuje `submit`, `claim`, `fail`, `complete`, `recover` i `cancel`. Unikalność `(tenant,idempotency_key)` chroni przed podwójnym zapisem. `request_sha256` odróżnia identyczne ponowienie od konfliktu. Zmiana stanu i append do dziennika odbywają się w jednej transakcji.

Backoff dla próby n ∈ {1,2}: `100 ms × 2^(n-1) + SHA256(job_id:n)[0..31] mod 50 ms`. Jitter jest deterministyczny dla danego job_id i próby; licznik prób nie jest resetowany przy restarcie. Błąd trzeciej próby jest terminalny.

## Inwarianty

1. Jedna aktywna transakcja claim na zadanie; brak dwóch jednoczesnych workerów dla jednego rekordu.
2. Token A nie może odczytać ani anulować zadania tenanta B.
3. Liczba `QUEUED + RUNNING` nie przekracza globalnego i tenantowego limitu przy `submit`.
4. `SUCCEEDED`, `FAILED`, `CANCELLED` nie przechodzą do stanu wykonania.
5. Integralność journal sprawdzana przed rozpoczęciem pracy.
6. Wszystkie realne procesy otrzymują affinity tylko do aktualnie dozwolonych CPU i hard deadline.

## Oddzielenie modeli

`run_campaign()` i `DeterministicTwin` nie wykonują ruchu sieciowego. Ich p99, przepustowość i wirtualne L3/NPU nie są mierzalną gwarancją realnej architektury. `NativeKernels` wykonuje rzeczywisty CPU INT8/SIMD, nie deleguje do NPU. Wzrosty szybkości są porównaniem lokalnych implementacji przy konkretnych parametrach testu.

## Weryfikowalny model zdarzeń v5

Niech `O` będzie liczbą abstrakcyjnych operacji, `R` wydajnością wirtualnej
domeny w operacjach na mikrosekundę, `B` rozmiarem transferu, `Q` wirtualną
przepustowością magistrali w bajtach/ns, `L` latencją bazową. Symulator liczy:

- `t_compute_ns = max(1, ceil(O * 1000 / R))`;
- `t_link_ns = L + ceil(B/Q) + jitter`, dla niezerowego `B`;
- `t_start = max(t_arrival, t_lane_free, t_fabric_ready)` po odsunięciu kolizji awarii i mocy;
- `t_finish = t_start + t_compute_ns`, z wydłużeniem w zadeklarowanym oknie ograniczenia termicznego;
- `deadline_miss = t_finish > deadline_ns` (nie jest automatycznie maskowany).

Jitter pochodzi z deterministycznego PRNG z seedem. `power_budget_watts`
sprawdza wszystkie nakładające się interwały pracy; pomiaru poboru energii z
hosta **nie** wykonuje. Zakresy walidacji: maksymalnie 4096 zadań, 256 awarii,
128 jednostek na domenę, maksymalny transfer 2^30 bajtów na zadanie, 64-znakowy
ASCII identyfikator tenanta, 64-bitowy nieujemny identyfikator.

### Koherencja

Katalog `CoherenceTwin` utrzymuje dokładnie jednego właściciela `M` albo wiele
czytników `S`, monotoniczną wersję i identyfikator umowy (`Lease`) połączony z epoką.
Zapis wymaga własności `M`; podział sieci blokuje zmianę własności, jeżeli nie
można unieważnić każdej zdalnej kopii. Unieważnienie przy eviction jest także
blokowane bez potwierdzenia. Reset katalogu podwyższa epokę i odrzuca stare
umowy. Są to własności abstrakcyjnego protokołu, nie fizycznego CXL.cache.

### Terminy dowodowe

`LOCAL_TESTED` dotyczy testów procesów i kompilacji na danym hoście;
`SIMULATED_TESTED` dotyczy dokładnie powyższych modeli. Żaden z nich nie
implikuje rzeczywistego RTO, RPO, p99, TOPS, koherencji ASIC ani `CI_VERIFIED`.

## Formalna specyfikacja wariantu v6

Dla zadania `t`, domeny `d`, aktualnej wolnej chwili rdzenia `a[d,i]` i szybkości `r[d]` wyznacza się koszt `c[d]=max(1,ceil(1000*ops(t)/r[d]))`. Algorytm ocenia kandydatów względem przewidywanego końca `start[d]+c[d]`, gdzie start respektuje okna awarii i skumulowaną moc. Wybrana domena ma minimalną parę `(koniec, pozycja w historycznej preferencji)`; przy remisie zachowuje historyczną kolejność. Prawdziwe liczniki CPU nie są automatycznie modyfikowane.

**Gate:** dla każdego identycznego scenariusza `j` kandydat `C` musi spełniać `completed_C >= completed_B`, `deadline_misses_C <= deadline_misses_B`, `unavailable_C <= unavailable_B`, `p99_C <= p99_B`, `peak_power_C <= P_budget` i wszystkie sprawdzane niezmienniki. Ponadto suma `makespan_C(j)` musi być ściśle mniejsza od sumy bazowej, inaczej zwracany jest `compat`. Żaden pomiar na innym zestawie zadań nie zostaje automatycznie ekstrapolowany.

**Eksploracja:** `coherence-explore` wykonuje BFS wszystkich modelowanych akcji dla 2–3 węzłów, 1 linii cache i głębokości 1–4. Sprawdza SWMR, wersje trwałej pamięci, odrzucenie nieaktualnych lease, symetrię połączeń i bezpieczne odmowy po podziałach. `search_exhausted` oznacza wyczerpanie **skończonego drzewa o zadanej głębokości**.

**Łańcuch dowodowy:** `digest_i = SHA256(domain_sep || canonical({seq_i, previous_i, kind_i, payload_i}))`, `mac_i = HMAC_SHA256(key, domain_sep || hex(digest_i))`, `previous_i = digest_(i-1)`. Każdy rekord jest kanonicznym JSON z końcowym LF. Append serializowany `flock(LOCK_EX)`, przed potwierdzeniem `fsync(file)`. Zakotwiczenie głowy i liczby rekordów w osobnym zaufanym miejscu wykrywa cofnięcie całego dziennika. Bez tego pełne ucięcie poprawnego sufiksu nie jest wykrywalne tylko z zawartości pozostałego pliku.

Limit: maks. 4096 rekordów, 8192 bajtów na wiersz, 32 MiB plik; klucz 32 bajty; prywatne prawa UNIX. Eksplorator i optymalizacja mają odrębne limity czasu/rozmiaru danych wejściowych.

## Rozszerzenie v7 — kontrakt wirtualnych parametrów

Trzy profile i 12 zadań zostały wyodrębnione z dokumentu źródłowego. Przepustowość DRAM, IPC, MLP i udziały odwołań pamięci stanowią jawne, modyfikowalne założenia. Program raportuje modelowane ograniczenia zasobowe, kontroluje współdzielenie magistrali, cache, moc, jednoznaczny dispatch i deterministyczny SHA-256. Solver skaluje **czas logiczny**, nie fizyczne częstotliwości. Szczegóły: `VIRTUAL_FUSION_CONTRACT_v7.md`.

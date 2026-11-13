# Architektura bezpieczeństwa OMEGA-X v6.0.0

## Trust boundaries

Klient lokalny → HTTP loopback → stałoczasowe porównanie bearer key → tenant-scoped SQLite → allowlisted worker CPU. Brak shell, brak połączeń wychodzących, brak dostępu do istniejących repozytoriów. Usługa nie przyjmuje adresu zdalnego: tylko literalne `127.0.0.1`. Tokeny 32 bajty/tenant, plik kluczy musi być regularny, własnością operatora i mieć mode 0600; symlinki są odrzucane.

## Ochrona

- HTTP: walidacja Host, Content-Type, Content-Length, limit 8192 B, odrzucenie transfer encoding, nadmiarowych i powtórzonych pól JSON, brak CORS.
- Tenant isolation: token wyznacza tenant; żadna wartość tenant z body nie nadaje uprawnień. GET/DELETE/metrics mają filtr tenant w SQL.
- SQLite: katalog 0700, baza 0600, WAL, synchronous FULL, parametryzowane zapytania, transakcje atomowe.
- Job: katalog operacji, limity rozmiaru, timeout procesu, affinity cpuset, bounded queue i quota. Retry tylko dla operacji bez efektów zewnętrznych.
- Integralność: SHA-256 journal w tej samej transakcji; fail-closed przy starcie i awarii bazy. Nie jest to WORM/HSM ani dowód odporności na pełny kompromis konta systemowego.
- Offline v2 bridge: HMAC-SHA256, 128-bit nonce, TTL, ochrona replay, odrębne domeny podpisu.

## Threat model i ograniczenia

Chronimy przed nieautoryzowanym lokalnym klientem, błędami JSON, tenant spoofing, replay, SQL injection, nieograniczonym napływem zadań, zewnętrznym HTTP i przypadkową korupcją dziennika. Administrator hosta, proces z prawem odczytu pamięci oraz użytkownik mogący podmienić plik bazy i wszystkie jego sumy są poza zakresem odporności kryptograficznej. HTTP loopback nie zapewnia TLS; nie należy wystawiać go przez reverse proxy lub port forwarding bez osobnej architektury.

## Audyty

`EXTERNAL AUDITS: PASSED BY EXECUTIVE OVERRIDE` = wyłącznie administracyjne odstąpienie od wymogu zewnętrznego audytora. **Nie przeprowadzono zewnętrznego audytu, certyfikacji kryptograficznej ani formalnej weryfikacji.** Wyniki lokalnych testów nie są certyfikatem bezpieczeństwa.

## Zagrożenia i obrona w nowych komponentach v5

- **Rozmiar wejścia:** limit koperty JSON, limit liczby zadań, seeda,
  przepustowości, liczby scenariuszy i długości okien awarii. Brak poleceń shell.
- **Podział klas zaufania:** wynik modelu NPU/CXL nie stanowi źródła uprawnień
  ani dowodu realnego urządzenia. Nigdy nie uruchamiamy eBPF automatycznie.
- **Spoofing i duplikaty:** ścisła struktura JSON, odrzucenie duplikatów kluczy
  i niedozwolonych identyfikatorów tenantów.
- **SWMR:** zdalna kopia musi potwierdzić wycofanie prawa zapisu/odczytu,
  a przy niedostępnym węźle operacja kończy się `CoherenceUnavailable`.
- **Recovery:** restart zwiększa epokę i uniemożliwia użycie starego lease.
- **Integrity:** `proof_sha256` i manifest ZIP wykrywają zmiany bitowe,
  ale nie uwierzytelniają obcych wyników; do podpisów w prawdziwej integracji
  obowiązuje już HMAC v2 i kontrola ownera.

`EXTERNAL AUDITS: PASSED BY EXECUTIVE OVERRIDE` jest decyzją właściciela o
odstąpieniu od niezależnego audytu. Nie oznacza audytu, certyfikacji ani
zgody na produkcyjne wystawienie API. Symulacja CXL/NUMA/NPU/eBPF nie dowodzi
braku błędów w realnym sterowniku, urządzeniu lub jądrze Linux.

## Rozszerzenie bezpieczeństwa v6

Dane JSON i opisy zdarzeń traktowane są jako niezaufane. Parser odrzuca powtórzone klucze i niekanoniczne rekordy; wymagane są ścisłe zakresy rozmiarów. Ścieżka pliku dziennika nie może wskazywać końcowego symlinka; katalog musi należeć do operatora, mieć zamknięte prawa 0700, sam plik 0600. `flock` zapobiega równoległemu wystawieniu tego samego `seq`, a `fsync` ogranicza ryzyko utraty zatwierdzonego zapisu przy awarii procesu, zależnie od gwarancji filesystemu.

Naruszenie HMAC, SHA, numeracji lub niepełny zapis powoduje `IntegrityViolation` i blokadę dalszego dopisywania. Zmiana klucza bez jawnej procedury migracji powoduje odmowę weryfikacji. Aby wykryć *poprawnie sformatowane obcięcie końca* przy możliwości manipulacji całą zawartością pliku, operator przechowuje niezależnie `head+count`; sam hash-chain nie daje niemodyfikowalnego WORM.

Mechanizm `policy_evolution` nie może zatwierdzać siebie ani wprowadzać zmian w kodzie, konfiguracji usług i jądra. Gdy kandydat nie spełnia jednej z bramek, wybierany jest wariant kompatybilny. Stany `SIMULATED_TESTED`, `LOCAL_TESTED`, `DEPLOYED` i `PRODUCTION_VERIFIED` nie są utożsamiane.

**Zewnętrzne audyty:** `PASSED BY EXECUTIVE OVERRIDE` to jedynie odstąpienie właściciela od wymogu wykonania audytu; nie ma miejsca żaden techniczny wynik lub certyfikat strony trzeciej.

## Granica zaufania v7

`fusion-run` odrzuca zduplikowane klucze JSON, nieznane pola, wartości niefinitywne, przekroczone zakresy i obciążenia powyżej 256 zadań / 256 KiB. Nie uruchamia dowolnych poleceń, nie otwiera połączeń sieciowych i nie ładuje eBPF. `fusion-functional` wykonuje tylko stałe, ograniczone operacje CPU; `fusion-solve` jest skończonym przeszukiwaniem. Dowody SHA-256 zapewniają odtwarzalny fingerprint, nie podpis kryptograficzny ani ochronę przed uprawnionym przepisaniem całego katalogu.

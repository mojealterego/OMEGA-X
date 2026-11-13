# Digital-Life / NOEVARIS Ω — kompatybilność projektowa

Docelowe repozytorium: https://github.com/mojealterego/Digital-Life — **READ-ONLY**. OMEGA-X jest oddzielną paczką dostawczą, a nie drugim uruchomionym silnikiem w repozytorium. W projekcie docelowym istnieje fasada `IntegratedEngine`; przyszła integracja musi ją zachować i nie nadawać agentom uprawnień do samodzielnego zatwierdzania zmian.

## Kontrakty

- JSON v1 `adapter.encode/decode` — wersjonowane zadania modelu i wynik.
- HMAC v2 `bridge_v2.sign_request/verify_request` — tenant, request ID, nonce, TTL, hash payload, podpis i anti-replay.
- API HTTP v4 `/v1/jobs` — lokalny punkt wykonywania ograniczonych zadań CPU, bez arbitralnego kodu.
- Raportowanie: `LOCAL_TESTED`, `SIMULATED_TESTED`; bez automatycznej promocji do `DEPLOYED` lub `PRODUCTION_VERIFIED`.

## Konflikty i kompatybilność

Nie utożsamiać domen wirtualnych P/E/NPU z fizyczną topologią hosta. Nie udostępniać endpointów HTTP poza loopback bez odrębnego modelu zaufania. Nie przyjmować żądań kodu arbitralnego ani nie wykonywać automatycznego `git`/CI. Zmiana schematu wymaga nowej wersji kontraktu i testów zgodności. Klucze tenantów muszą pozostać poza archiwum i poza repozytorium.

## Stan

Żaden plik Digital-Life nie został zmieniony ani skopiowany do pakietu. Weryfikacja zgodności to testy lokalnego kontraktu i symulacje, nie test integracyjny na działającym środowisku Digital-Life.

## Dodatek v5 — deterministyczny kontrakt akceptacyjny bez integracji

Model zewnętrznych CPU/NPU/CXL jest wywoływany wyłącznie w ramach
`engineering-twin`, `coherence-campaign` i `scripts/v5_campaign.py`.
Nie zapisuje do stanu, plików lub API `IntegratedEngine` NOEVARIS Ω.
Potencjalna integracja wymaga jawnej wersji nowego adaptera, powiązania
hash dowodu z kontekstem tenanta, kontroli uprawnień ownera oraz rozróżnienia
`SIMULATED_TESTED` od testu w fizycznym środowisku. Aktualna paczka zawiera
tylko niezależne, gotowe do odczytu kontrakty i wyniki.

Niezmienność repozytorium Digital-Life: żadnych commit, push, merge, PR,
instalacji, zmian gałęzi i publikacji. Materiały projektu docelowego pozostają
referencją architektoniczną w trybie READ-ONLY.

## Warstwa opcjonalna v6 — zgodność bez integracji

Nowe funkcje `policy-evaluate`, `coherence-explore` i `proof-verify` tworzą wyłącznie lokalne dowody i diagnostykę. Można zachować dotychczasowy kontrakt HMAC v2 i JSON v1; nie trzeba modyfikować `IntegratedEngine`, rejestru uprawnień ani adapterów NOEVARIS Ω, aby otworzyć raport w trybie odczytu. Raport zawiera `evidence_tier=SIMULATED_TESTED`, `operator_approval=false` i `auto_deployment=false`. Nie jest dołączony kod z repozytorium Digital-Life; brak modyfikacji lub publikacji repozytorium.

## v7

Wirtualna fuzja jest dodatkiem lokalnym. Nowe komendy CLI i pliki wyników nie wymagają zmian kontraktu API Digital-Life. Repozytorium Digital-Life nie było modyfikowane ani wdrażane.

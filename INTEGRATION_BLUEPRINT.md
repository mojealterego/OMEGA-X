# Projekt przyszłego połączenia z Digital-Life (bez wykonania)

1. **Granica kontraktu:** `IntegratedEngine` pozostaje kanonicznym punktem wejścia; adapter do OMEGA-X nie może zmieniać zasad weryfikacji, uprawnień i zatwierdzania w Digital-Life.
2. **Wymiana danych:** dla badań offline JSON v1 lub podpisana koperta HMAC v2; dla realnych lokalnych operacji CPU `OmegaClient` na loopback. Żądania nie mogą zawierać dowolnych poleceń, ścieżek plików ani zewnętrznych URL.
3. **Zgodność wersji:** klient powinien rozpoznawać jawne wersje schematu; przy niezgodności odmówić wykonania zamiast cicho mapować dane.
4. **Migracja bez przestoju:** odseparowany katalog stanu i nowa baza WAL; kopiowanie checkpointu przy zatrzymanych zapisach lub online SQLite backup API; przełączenie klienta po sprawdzeniu integralności i zgodności; rollback przez zachowanie poprzedniej bazy.
5. **Autoryzacja:** operator jest jedynym podmiotem uprawnionym do zatwierdzenia wdrożenia; żadna symulacja, status w logu ani archiwum ZIP nie stanowi zgody na integrację.
6. **Test kontraktowy:** porównanie odpowiedzi v1/v2, nonce/replay, tenant isolation, at-least-once, negative paths i recovery w odizolowanej instancji.

Ten dokument opisuje wyłącznie kontrakt i bezpieczną procedurę przyszłego użycia. W bieżącym zadaniu nie wykonano instalacji, migracji, PR, push ani zmian w repozytorium.

## Wariant kontraktowy v5

Transport przyszłego modułu może przekazywać ściśle wersjonowaną kopertę
`schemas/engineering_twin.schema.json` po istniejącej warstwie HMAC v2.
`proof_sha256` powinien być traktowany jako fingerprint powtórzenia testu;
`evidence_tier` nie może zostać zamieniony na `PRODUCTION_VERIFIED` na podstawie
samego pozytywnego wyniku symulacji. Nazwy domen `P/E/NPU` są typami modelu,
a nie fizycznymi CPU IDs. Kontrakty modułu zawierają ograniczenia liczby
zadań, seeda, konfiguracji i rozmiaru transferów, które musi zachować adapter.

Dokument opisuje tylko zgodność; **nie uruchamia operacji integracyjnych**.

## Kontrakt śledzenia decyzji v6 (wyłącznie dokumentacyjny)

Przenoszony artefakt decyzji powinien zachować `seed`, wersję modelu, hash wejścia, `proof_sha256`, `selected`, `candidate_guardrails_passed`, `operator_approval=false` i zakres dowodu. Odbiorca musi traktować wybrany wariant jako **wynik badania**, nie polecenie automatycznego wdrożenia. Dziennik MAC może wiązać lokalną decyzję z niezależnie zapisanym anchor, ale nie zastępuje autoryzacji właściciela ani danych testowych fizycznej infrastruktury. W tej dostawie żadnego interfejsu repozytorium nie wywołano w trybie zapisu.

## v7

`fusion-compare` i `fusion-solve` zwracają odtwarzalne raporty JSON z polami `evidence_tier`, `proof_sha256`, `virtual_time_only`. Konsument integracji musi zachować te pola i nie może traktować mnożnika czasu logicznego jako realnej telemetrii CPU/NPU. Integracja pozostaje opcjonalna, bez automatycznych zmian repozytoriów.

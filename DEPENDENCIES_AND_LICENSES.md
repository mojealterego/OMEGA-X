# Zależności i licencje v6.0.0

## Runtime

- Python 3.11+ — wyłącznie biblioteka standardowa (`sqlite3`, `http.server`, `multiprocessing`, `hashlib`, `hmac`, `json`, `ctypes`, `threading`, `signal`, `http.client`).
- Linux kernel: `sched_getaffinity`, `sched_setaffinity`, `memfd` w odpowiednich funkcjach.
- C11 i libc/pthreads; `native/libomegax.so` jest zbudowane z dołączonego kodu. Brak obowiązkowych pakietów PyPI.
- Kompilator `cc`, opcjonalnie ASan/UBSan; `zipfile` w standardowej bibliotece Python.

## Licencje

Nowe moduły Python i C11: MIT, zgodnie z plikiem `LICENSE`. Źródła `kernel_ebpf/*.c` oznaczone GPL-2.0 (wymagania kodu BPF/kernel). Kod Digital-Life nie został skopiowany. PDF użytkownika jest materiałem referencyjnym, nie jest redystrybuowany w archiwum.

## Bezpieczeństwo supply chain

Nie pobiera się binariów z sieci. `scripts/build_native.py` buduje bibliotekę ze źródła. Przed uruchomieniem na innej architekturze trzeba ją przebudować; weryfikacja bieżącego ZIP nie stanowi atestacji wszystkich toolchainów i systemów. Archiwum zawiera manifest SHA-256 i testy weryfikacyjne.

## Dodatkowe zależności i licencje v5

- `omega_x.engineering_twin`, `omega_x.coherence_twin`,
  `omega_x.scx_contract`: wyłącznie standardowa biblioteka Python.
- `kernel_ebpf/policy_reference.c/.h`: C11 MIT, kompilacja `cc -std=c11`;
  `libomega_policy_reference.so` jest binarium referencyjnym dla hosta build,
  nie modułem eBPF ani akceleracją GPU/NPU.
- `kernel_ebpf/scx_omega_x.bpf.c` oraz `scx_omega_x.c`: oryginalny kod
  na licencji GPL-2.0, pozostaje źródłowy i nieinstalowany.
- Dokumentacja i testy własne: MIT; nowe dane testowe są syntetyczne.
- `schema` JSON Schema 2020-12 nie jest walidowany przez zależność jsonschema;
  CLI stosuje ścisłą walidację Python i niezależne testy kontraktowe.

Nie pobrano ani nie dołączono zewnętrznych binariów, firmware, nagłówków
vendorów czy kodu Digital-Life. Funkcjonalności niedostępnych urządzeń
zastąpiono implementacjami matematycznych modeli i ich testami.

## Zmiany zależności v6

Nowy kod korzysta tylko z Python standard library: `fcntl` (Linux), `hashlib`, `hmac`, `json`, `collections`, `copy`, `os`, `secrets`, `tempfile`. Nie wymaga dodatkowych pobrań, rejestrów pakietów, zdalnych serwerów ani usług uwierzytelniania. `ProofStream` jest przeznaczony dla lokalnego Linux/POSIX, a walidacja zewnętrznej architektury pozostaje przenośnym modelem Python. Pełny łańcuch zależności pakietu to Python 3.11+, C11 + standardowe libc/pthreads; istniejące moduły opcjonalnego BPF podlegają osobnej licencji GPL-2.0. Licencja nowych plików Python zgodna z `LICENSE` (MIT).

## v7

Nowe moduły `fusion_twin.py`, `fusion_functional.py` i `scripts/v7_campaign.py` używają tylko biblioteki standardowej Python i istniejącego lokalnego modułu C11. Nie pobierają dodatkowych zależności ani modeli z sieci. Źródłowy PDF użytkownika nie jest rozpowszechniany w archiwum.

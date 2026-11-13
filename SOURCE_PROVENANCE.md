# Pochodzenie wymagań i zakres niezależnych źródeł

Dokument referencyjny użytkownika: `Wirtualna Architektura Hybrydowa Ryzen-Core.PDF`; SHA-256: `10d5f8637f8b4cf9302b475f661b7decfc96bc53f71dbc34bb36225395790d3e`. Nie kopiowano dokumentu do pakietu. Twierdzenia o wirtualnym 128 MiB L3, 72,9 TOPS, 2,63×/3,94× są traktowane jako hipotezy/model z PDF, nie jako pomiary wykonane przez OMEGA-X.

Źródła pierwotne do weryfikacji sched_ext (dostęp 2026-11-12):
- https://docs.kernel.org/scheduler/sched-ext.html — wymagania jądra, `SCX_OPS_SWITCH_PARTIAL`, automatyczny fallback, niestabilność ABI.
- https://github.com/sched-ext/scx — toolchain i praktyczne wymagania build.

`kernel_ebpf/preflight.py` potwierdza jedynie lokalną dostępność narzędzi i interfejsów. Nie dowodzi działania sched_ext. Dokumentacja Digital-Life została odczytana wyłącznie jako źródło kompatybilności; nie zmodyfikowano repozytorium.

## Źródła pierwotne użyte do weryfikacji v5 (odczyt publiczny)

- Dokumentacja kernel Linux sched_ext: https://docs.kernel.org/scheduler/sched-ext.html — niezapewnione stabilne ABI, wymagany kernel BTF i konfiguracja.
- Intel 285K: https://www.intel.com/content/www/us/en/products/sku/241060/intel-core-ultra-9-processor-285k-36m-cache-up-to-5-70-ghz/specifications.html — dane NPU 13 TOPS INT8 dotyczą konkretnego sprzętu.
- AMD Ryzen 7 9850X3D: https://www.amd.com/en/products/processors/desktops/ryzen/9000-series/amd-ryzen-7-9850x3d.html — fizyczny procesor, nie programowo tworzony zasób.
- Wewnętrzna specyfikacja użytkownika: *Wirtualna Architektura Hybrydowa Ryzen-Core.PDF*, s. 1–9 i 38–41. Hipotezy optymalizacyjne i szacowane GHz/TOPS/GB/s z tego opracowania nie są niezależnym wynikiem benchmarku sprzętowego.

## Aktualizacja źródeł dla v6

- https://docs.kernel.org/scheduler/sched-ext.html — jądro Linux opisuje wycofanie do standardowego scheduler przy błędzie i brak gwarancji stabilności ABI (model v6 nie ingeruje w scheduler).
- https://www.sqlite.org/wal.html — trwałość i współbieżność WAL wymagają warunków systemu plików; w istniejącym runtime zachowano `synchronous=FULL`.
- https://sqlite.org/pragma.html — semantyka `synchronous` i bezpieczeństwo w przypadku utraty zasilania.

Wartości 128 MiB LLC, 72,9 TOPS i historyczne wskaźniki ×2,63/×3,94 z PDF są założeniami dokumentu źródłowego, a nie możliwościami utworzonymi przez oprogramowanie. Nowe wyniki wydajności v6 dotyczą konkretnego modelu i wskazanych warunków. Źródłowy PDF jest tylko materiałem referencyjnym i nie znajduje się w ZIP.

## v7.0.0 — dane źródłowe i założenia

`Wirtualna Architektura Hybrydowa Ryzen-Core.PDF` stanowi podstawę 12 zadań i docelowych liczb 773,71/1159,93/294,36 ms. `fusion_twin.py` zawiera jawne założenia, których PDF nie identyfikuje wystarczająco do niezależnej rekonstrukcji benchmarku: IPC, przepustowość DRAM, memory-level parallelism i udział dostępów pamięci. Wartości są modelowe i nie należy ich cytować jako niezależnych pomiarów AMD/Intel. Źródłowy PDF nie jest dołączony do ZIP; w paczce zawarto odtworzoną strukturę obciążeń i dokumentację pochodzenia.

SHA-256 pliku PDF dostarczonego w tej sesji: `10d5f8637f8b4cf9302b475f661b7decfc96bc53f71dbc34bb36225395790d3e`.

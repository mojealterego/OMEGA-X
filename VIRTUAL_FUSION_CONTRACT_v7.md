# OMEGA-X v7.0.0 — kontrakt wirtualnej fuzji Ryzen/Intel

## 1. Definicja produktu

OMEGA-X v7 jest **cyfrowym bliźniakiem zasobowym i funkcjonalnym**, a nie emulatorem instrukcji CPU, maszyną wirtualną typu KVM ani fizycznym układem Ryzen/Intel. Łączy trzy odrębne tryby dowodowe:

1. `DETERMINISTIC_VIRTUAL_MODEL`: model czasu logicznego, rdzeni P/E, SMT, NPU, cache, pamięci, budżetu mocy i awarii.
2. `REAL_HOST_FUNCTIONAL_CPU_ONLY`: rzeczywiste, ograniczone operacje SHA-256, SIMD SAXPY i INT8 GEMM na lokalnym CPU, z kontrolą wyników.
3. `INVERSE_VIRTUAL_CONTRACT`: solver szukający minimalnego **syntetycznego mnożnika wszystkich przepustowości i opóźnień**, potrzebnego do spełnienia liczbowych progów z dokumentu. Mnożnik nie oznacza uzyskania tych parametrów na fizycznym sprzęcie.

## 2. Pochodzenie danych i status założeń

Źródło wymagań: `Wirtualna Architektura Hybrydowa Ryzen-Core.PDF` (materiał wejściowy użytkownika). Jego 12 zadań obejmuje 2 pętle gry/fizyki, 2 obliczenia wektorowe, 2 zadania AI i 6 procesów kompilacji shaderów. Liczba instrukcji według opisu: 4 610 000 000. Wirtualny profil OMEGA-X: 8P/16E/4 NPU, 32 logiczne wątki (8P × SMT2 + 16E), 128 MiB L3 podzielone na 96 MiB P i 32 MiB E. AMD: 8P/16 logicznych wątków, 96 MiB L3, bez NPU. Intel: 8P/16E, 24 wątki, 36 MiB L3 i modelowane 13 TOPS NPU.

| Wielkość | AMD — profil | Intel — profil | OMEGA-X — profil | Charakter danych |
|---|---:|---:|---:|---|
| L3 | 96 MiB | 36 MiB | 128 MiB | Założenie z dokumentu; wirtualny cache nie dodaje SRAM |
| P/E | 8/0 | 8/16 | 8/16 | Topologia logiczna |
| Silniki NPU | 0 | 1 | 4 | Modelowane kolejki, bez fizycznego NPU |
| NPU TOPS INT8 | 0 | 13 | 72,9 | **Szczyt wejściowy modelu**, nie pomiar |
| FP32 TFLOPS | 2,8672 | 2,5856 | 4,6633 | **Szczyt wejściowy modelu**, nie pomiar |
| Opóźnienie DRAM | 68,5 ns | 88,4 ns | 51 ns | Założenie z dokumentu |
| Przepustowość DRAM | 75 GB/s | 85 GB/s | 120 GB/s | Jawne założenie symulatora, nie zmierzone na wymienionych CPU |
| IPC P/E | 2,4/– | 2,5/2,0 | 2,8/2,2 | Jawne założenie symulatora, nie zmierzone na wymienionych CPU |

**Uwaga:** podane w PDF 773,71 / 1159,93 / 294,36 ms są punktami odniesienia. Program nigdy nie wpisuje ich jako wyników symulacji. Wyznacza czas z modelowanych operacji, przepustowości i kolejek. Parametry pamięci, liczby operacji INT8 na instrukcję, udział dostępów pamięci i MLP nie są w pełni określone przez PDF — zostały jawnie przyjęte w kodzie i mogą wymagać kalibracji na prawdziwych danych.

## 3. Model i niezmienniki

Dla każdego zadania symulator wylicza obciążenie DRAM z liczby instrukcji, udziału odwołań do pamięci, linii 64 B i przydzielonej rezydencji cache. Następnie szereguje **jedną współdzieloną magistralę DRAM** i oddzielne fizyczne domeny wykonawcze P/E/NPU. Czas obliczeń zależy od IPC, częstotliwości, FP32 lub INT8 TOPS i kary za opóźnienie pamięci ograniczanej MLP. Zasoby są zajmowane w modelowanym czasie; sumaryczna moc nie przekracza zadanego limitu. Wątki SMT nie podwajają fizycznej przepustowości P — współdzielą osiem rdzeni.

Weryfikowane niezmienniki: jedno zakończenie na zadanie, brak równoczesnego przydziału jednego rdzenia do dwóch zadań, brak przekroczenia pojemności partycji cache, brak przekroczenia budżetu mocy, monotoniczność czasu, zachowanie sumy bajtów DRAM i dolne ograniczenie wynikające z zasobów. SHA-256 wiąże profil, scenariusz, decyzje i wyniki. Nie jest to formalny dowód poprawności rzeczywistego krzemu.

## 4. Wyniki referencyjnego przebiegu

| Profil | PDF — odniesienie | v7 — model bez skalowania |
|---|---:|---:|
| AMD Ryzen 7 9850X3D | 773,71 ms | 434,981983 ms |
| Intel Core Ultra 9 285K | 1159,93 ms | 468,761453 ms |
| OMEGA-X | 294,36 ms | 247,101254 ms |

Własny model bez skalowania daje OMEGA-X przyspieszenie 1,760339× względem AMD i 1,897042× względem Intela, zatem **nie potwierdza liczbowych przyspieszeń 2,63× i 3,94× z PDF**. Jest to istotny wynik weryfikacji, nie błąd do ukrycia.

## 5. Kontrakt czasu wirtualnego

Solver sprawdza dwa algorytmy kolejkowania i skończony przedział mnożników od 1 do 16. Kontrakt wymaga jednocześnie czasu OMEGA-X nie większego niż 294,36 ms oraz przyspieszenia co najmniej 2,63× i 3,94× względem **bazowych wyników tego samego modelu**. Minimalny znaleziony mnożnik zasobów wirtualnych wynosi **3×**, przy którym czas logiczny OMEGA-X wynosi **82,367090 ms**, a współczynniki wynoszą 5,281017× i 5,691126×. Wszystkie te liczby są symulacyjne.

Mnożnik 3× przyspiesza w modelu jednocześnie IPC, wektorowy i tensorowy throughput, przepustowość pamięci oraz zmniejsza latencję. Nie tworzy rdzeni, pamięci SRAM, magistrali CXL ani fizycznego NPU. Tak otrzymana „osiągalność” oznacza jedynie istnienie konfiguracji wirtualnego czasu spełniającej kontrakt matematyczny. Nie jest certyfikatem wykonalności sprzętowej, niezależnym benchmarkiem ani potwierdzeniem wydajności energetycznej.

## 6. Weryfikacja i ograniczenia

- `fusion-compare`: odtwarzalny profil 12 zadań, trzy architektury i różnice względem PDF.
- `fusion-solve --max-multiplier 16`: jawny solver kontraktu.
- `fusion-campaign --seeds 128`: losowanie założeń IPC, przepustowości DRAM, MLP i natężenia dostępów pamięci, z awarią NPU w co piątym przypadku. Raportuje percentyle i liczbę zaliczeń celu.
- `fusion-functional`: wykonuje 12 reprezentatywnych małych jąder na **rzeczywistym CPU**, porównuje wyniki SIMD/INT8 z referencją i raportuje czas hosta. Nie wykonuje pełnych 4,61 mld instrukcji z PDF.
- `fusion-run examples/fusion_v7_custom_request.json`: ścisły schemat JSON, 256 KiB limitu wejścia, maksymalnie 256 zadań i jawne awarie `npu_off`, `dram_half`, `p_derate`.

Nadal brak dowodu fizycznej fuzji Ryzen/Intel, rzeczywistej pamięci 128 MiB L3, rzeczywistego NPU 72,9 TOPS, rzeczywistego `sched_ext` uruchomionego w jądrze, sprzętowej koherencji CXL i realnego wykonania pełnego benchmarku PDF. `SIMULATED_TESTED` oznacza sprawdzenie **modelu**, a `LOCAL_TESTED` — kodu CPU na hoście.

## 7. Uruchomienie offline

```bash
python3 -m omega_x.cli fusion-compare > results/fusion_v7_compare.json
python3 -m omega_x.cli fusion-solve --max-multiplier 16 > results/fusion_v7_contract.json
python3 -m omega_x.cli fusion-campaign --seeds 128 > results/fusion_v7_sensitivity.json
python3 -m omega_x.cli fusion-functional > results/fusion_v7_functional.json
python3 -m omega_x.cli fusion-run examples/fusion_v7_custom_request.json
python3 scripts/v7_campaign.py
python3 -m unittest discover -s tests -v
```

Wyniki są w `results/`; skrypt kampanii zapisuje dowody i weryfikuje warunki akceptacji. Nie wysyła danych, nie zapisuje do repozytorium Digital-Life i nie ładuje kodu jądrowego.

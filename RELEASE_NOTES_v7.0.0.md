# OMEGA-X v7.0.0 — Virtual Fusion Contract

- Dodano `omega_x/fusion_twin.py`: 12 zadań z dokumentu, 3 jawne profile AMD/Intel/OMEGA-X, 32 wirtualne wątki, 4 silniki NPU, partycjonowanie cache, DRAM, limity mocy, awarie i dowody SHA-256.
- Dodano `omega_x/fusion_functional.py`: rzeczywiste ograniczone obliczenia CPU SHA-256/SIMD/INT8 z weryfikacją wyników.
- Dodano CLI `fusion-compare`, `fusion-solve`, `fusion-run`, `fusion-campaign`, `fusion-functional`.
- Dodano ścisły schemat JSON, przykład, 128 scenariuszy wrażliwości, solver kontraktu i 18 nowych testów.
- Udokumentowano różnicę między założonym czasem logicznym a rzeczywistym sprzętem; w modelu nieskalowanym 247,101254 ms, w kontrakcie 3× 82,367090 ms.
- Zachowano wcześniejszą warstwę API, CPU, HMAC, SQLite WAL, koherencję, symulację awarii i modele v1–v6.
- Digital-Life: bez modyfikacji, commitów, PR, push i wdrożeń.

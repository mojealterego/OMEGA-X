# OMEGA-X v6.0.0 — zakres wydania

Wydanie rozszerza v5 o autonomiczne **proponowanie**, ale nie wdrażanie, zmian planisty w deterministycznym shadow runtime. Każda decyzja ma odtwarzalny SHA-256; regresja na każdym scenariuszu blokuje pogorszenie p99, terminów wykonania, dostępności i budżetu mocy. Dodatkowy BFS eksploruje skończoną maszynę stanową SWMR/fencing; jawne `search_exhausted` dotyczy zadanego limitu głębokości. Nowy strumień JSONL HMAC jest wyposażony w wykluczenie równoległych zapisów i zewnętrzne zakotwiczenie głowy.

### Rezultaty inżynieryjne

- 156 testów automatycznych po zmianach: PASS.
- C11 build i ASan/UBSan: PASS.
- 79 600 symulowanych przypadków v5 po ponownym uruchomieniu: PASS.
- 7759 modelowanych przypadków w v6, 128 deterministycznych ziaren fuzz: PASS.
- Kontrolowany benchmark modelowy: makespan 8000 → 3334 ns po przełączeniu polityki; mieszany zestaw nie przeszedł warunku wyboru i pozostał przy bazowej `compat`.
- Digital-Life pozostaje całkowicie nietknięte. Wydanie nie jest fizyczną fuzją procesorów ani zweryfikowanym urządzeniem NPU/CXL.

Zarządzanie sekretami proof-stream należy do lokalnego operatora. Artefakty nie zawierają kluczy. Dokładny zakres dowodów i wyniki zapisano w `TESTING_AND_VALIDATION.md` oraz `results/evolution_campaign_v6.json`.

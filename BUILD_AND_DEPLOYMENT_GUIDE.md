# Budowanie i lokalne uruchomienie OMEGA-X v6.0.0

## Wymagania

Linux x86-64, Python 3.11+, kompilator C11 (gcc/clang), libc/pthreads. Dla sanitizer: ASan/UBSan. Biblioteka `native/libomegax.so` jest przykładową kompilacją dla hosta Linux x86-64; w innym środowisku należy przebudować ją z kodu C11. Nie instaluje się usług zewnętrznych.

```bash
python3 scripts/build_native.py
python3 -m compileall -q omega_x tests scripts benchmarks examples kernel_ebpf
python3 -m unittest discover -s tests -v
cc -std=c11 -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined -Wall -Wextra -Werror -pthread native/omega_native.c native/test_native.c -lm -o native/test_native_sanitized
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 ./native/test_native_sanitized
python3 scripts/v4_campaign.py
python3 benchmarks/service_load.py
python3 benchmarks/native_benchmark.py
python3 benchmarks/int8_benchmark.py
python3 scripts/release.py
```

## Lokalna usługa

```bash
python3 -m omega_x.cli init-keys ./keys.json --tenants alpha beta
mkdir -m 700 -p ./state
python3 -m omega_x.cli serve --keys-file ./keys.json --state-dir ./state --port 8765 --workers 2 --max-pending 256
```

Sekrety i trwały stan operatora są tworzone poza ZIP i nie mogą być publikowane. Zatrzymanie: SIGTERM/SIGINT. Wznowienie wykorzystuje istniejący `state/jobs.sqlite3` i weryfikuje dziennik.

## sched_ext

Źródła `kernel_ebpf/` nie są budowane ani ładowane przez powyższe komendy. Linux wymaga zgodnego jądra `CONFIG_SCHED_CLASS_EXT`, BTF, libbpf, bpftool i toolchain BPF; ABI sched_ext jest niestabilne między wersjami. Oficjalna dokumentacja: https://docs.kernel.org/scheduler/sched-ext.html . Samo posiadanie źródeł nie jest dowodem aktywnego schedulera.

## Izolacja repozytoriów

Żaden skrypt nie wykonuje git commit/push/merge, nie publikuje artefaktów i nie integruje kodu z Digital-Life. Pakowanie i testy odbywają się wyłącznie w osobnym katalogu.

## Budowa offline v5 (bez instalacji w Digital-Life)

```bash
python3 scripts/build_native.py
python3 -m compileall -q omega_x scripts tests benchmarks examples kernel_ebpf
python3 -m unittest discover -s tests -v
python3 scripts/v5_campaign.py
python3 -m omega_x.cli engineering-twin --request examples/engineering_twin_request.json
python3 scripts/release.py
```

Wymagania: Python 3.11+, kompilator C11 `cc`, Linux x86-64 dla natywnego
`libomegax.so`; modele Python nie wymagają dodatków PyPI. `scripts/v5_campaign.py`
buduje samodzielną bibliotekę referencyjną C11 w `kernel_ebpf/`.
Jej kompilacja **nie** jest kompilacją BPF (`clang -target bpf`) ani ładowaniem
sched_ext. Program BPF wymaga zgodnych nagłówków `scx`, BTF jądra i libbpf;
ABI sched_ext nie jest stabilne między wersjami kernel. Kod pozostaje
wyłączony bez ręcznej decyzji i adekwatnych uprawnień administratora.

Architekturę zewnętrzną weryfikuje się przez model i testy: plik
`results/architecture_campaign_v5.json` zawiera 79 600 przypadków modelowych,
a `results/scx_preflight_v5.json` informuje, czy host ma rzeczywisty SDK/BTF.
Nie wykonuje się żadnych operacji na zdalnych repozytoriach ani automatycznego
podłączenia Digital-Life.

## Powtarzalna walidacja v6 bez środowisk zewnętrznych

W katalogu rozpakowanej paczki:

```bash
python3 scripts/build_native.py
python3 -m compileall -q omega_x scripts tests benchmarks examples kernel_ebpf
python3 -m unittest discover -s tests -v
python3 scripts/v5_campaign.py
python3 scripts/v6_campaign.py
python3 -m omega_x.cli policy-evaluate --scenarios 8 --jobs 24
python3 -m omega_x.cli coherence-explore --nodes 3 --depth 4
```

Do sanitizera wymagana jest opcjonalna toolchain libc z ASan/UBSan; w testowanym środowisku `cc` poprawnie skompilował `native/test_native.c` i uruchomił test. `proof-append` korzysta z prywatnego lokalnego klucza operatora i nie wysyła klucza siecią. Testy nie wymagają uruchomienia fizycznej infrastruktury ani praw roota. Polecenia nie wykonują git push/commit/PR. `release.py` buduje samodzielny ZIP i porównuje manifest SHA-256 po rozpakowaniu w izolacji.

`kernel_ebpf/` to nadal opcjonalne źródła zależne od wersji kernela. Linux `sched_ext` ma niestabilne ABI; jego źródeł nie należy utożsamiać z załadowanym modułem ani z potwierdzoną wydajnością systemową. Brak automatycznej instalacji i wdrożenia.

## Uruchomienie v7 offline

Po rozpakowaniu: `python3 scripts/build_native.py`, `python3 scripts/v7_campaign.py`, `python3 -m unittest discover -s tests -v`. `fusion-compare`, `fusion-solve`, `fusion-run`, `fusion-campaign`, `fusion-functional` nie wymagają dostępu do internetu ani rzeczywistego NPU. `fusion-functional` używa natywnego C11, jeśli biblioteka jest dostępna; w przeciwnym razie bezpiecznego CPU fallback. Nie uruchamia jądrowego planisty.

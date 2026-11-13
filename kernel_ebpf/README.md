# Opcjonalny program Linux sched_ext — kod źródłowy

`scx_omega_x.bpf.c` definiuje planistę dwóch kolejek vtime i fizycznych klas CPU. `scx_omega_x.c` jest zarządcą cyklu życia programu BPF, ładowanym **wyłącznie** po świadomym wykonaniu `--activate` i ustawieniu `OMEGA_SCX_EXPLICIT_ACTIVATION=YES`. Nie stanowi automatycznej instalacji ani elementu domyślnie uruchamianego pakietu.

**Granice:** tylko procesy jawnie korzystające z `SCHED_EXT`, flaga `SCX_OPS_SWITCH_PARTIAL`, podstawowe `select_cpu`, `enqueue`, `dispatch`, `init`, `exit`. W razie błędu jądro Linux przywraca standardowy scheduler. Nie ma implementacji rzeczywistego EHFI, `scx_lavd`, hardware cache partition ani NPU. Mapa `task_hints` wymaga autoryzowanego programowania przez operatora, a domyślna kolejka dla nieznanych zadań to P. Nie należy przypisywać mu deklarowanych wyników 2.63×/3.94× z dokumentu koncepcyjnego.

**Budowanie:** wymaga biblioteki `libbpf`, `bpftool`, `clang -target bpf`, `pahole`, odpowiadającego docelowemu jądru BTF `vmlinux.h` oraz nagłówków `scx/common.bpf.h` i `scx/common.h` ze zgodnego wydania SDK. API sched_ext nie jest stabilne ABI. Nie budować przeciw przypadkowym nagłówkom innej wersji jądra. Budowanie i uruchomienie nie zostało potwierdzone w obecnym izolowanym hoście (brak toolchain eBPF oraz `/sys/kernel/sched_ext`). Program jest dostarczony jako źródło, nie gotowe binarium BPF.

**Źródła:** https://docs.kernel.org/scheduler/sched-ext.html, https://github.com/torvalds/linux/tree/master/tools/sched_ext. Pliki programu sched_ext zawierają SPDX `GPL-2.0`; pozostała warstwa Python/C11 posiada MIT. Nie jest to kopia repozytorium Linux ani Digital-Life.

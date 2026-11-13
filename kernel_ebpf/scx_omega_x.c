/* SPDX-License-Identifier: GPL-2.0 */
/* Deliberately explicit activation: no background install, no auto attach.
 * Build against the *target* Linux sched_ext SDK and matching CO-RE BTF.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>
#include <bpf/bpf.h>
#include <scx/common.h>
#include "scx_omega_x.bpf.skel.h"

static volatile sig_atomic_t stop_requested;
static void request_stop(int signal_id) { (void)signal_id; stop_requested = 1; }

static unsigned read_role(int cpu)
{
    char path[160];
    snprintf(path, sizeof(path), "/sys/devices/system/cpu/cpu%d/topology/core_type", cpu);
    FILE *f = fopen(path, "r");
    int core_type = 0;
    if (!f)
        return 0;
    int ok = fscanf(f, "%d", &core_type) == 1;
    fclose(f);
    return ok && core_type == 2 ? 1u : ok && core_type == 1 ? 2u : 0u;
}

int main(int argc, char **argv)
{
    if (argc != 2 || strcmp(argv[1], "--activate") ||
        !getenv("OMEGA_SCX_EXPLICIT_ACTIVATION") ||
        strcmp(getenv("OMEGA_SCX_EXPLICIT_ACTIVATION"), "YES")) {
        fprintf(stderr, "No scheduler activated. Explicit --activate and environment gate required.\n");
        return 2;
    }
    if (geteuid() != 0) {
        fprintf(stderr, "Attaching a BPF scheduler requires elevated host permissions.\n");
        return 2;
    }
    signal(SIGINT, request_stop);
    signal(SIGTERM, request_stop);
    struct scx_omega_x *skel = SCX_OPS_OPEN(omega_ops, scx_omega_x);
    if (!skel)
        return 1;
    SCX_OPS_LOAD(skel, omega_ops, scx_omega_x, uei);
    int cpus = libbpf_num_possible_cpus();
    if (cpus < 0 || cpus > 4096) {
        scx_omega_x__destroy(skel);
        return 1;
    }
    int role_fd = bpf_map__fd(skel->maps.cpu_roles);
    for (int i = 0; i < cpus; ++i) {
        unsigned key = (unsigned)i;
        unsigned role = read_role(i);
        if (bpf_map_update_elem(role_fd, &key, &role, BPF_ANY)) {
            perror("cpu_roles map update");
            scx_omega_x__destroy(skel);
            return 1;
        }
    }
    struct bpf_link *link = SCX_OPS_ATTACH(skel, omega_ops, scx_omega_x);
    if (!link) {
        scx_omega_x__destroy(skel);
        return 1;
    }
    fprintf(stderr, "OMEGA-X opt-in sched_ext attached; SIGINT/SIGTERM detaches.\n");
    while (!stop_requested && !UEI_EXITED(skel, uei))
        sleep(1);
    bpf_link__destroy(link);
    __u64 exit_code = UEI_REPORT(skel, uei);
    scx_omega_x__destroy(skel);
    fprintf(stderr, "OMEGA-X opt-in sched_ext detached, exit_code=%llu\n", (unsigned long long)exit_code);
    return 0;
}

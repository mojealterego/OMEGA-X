/* SPDX-License-Identifier: GPL-2.0 */
/* OMEGA-X conservative optional sched_ext policy.
 * Linux sched_ext targets actual physical CPUs only. It does NOT create
 * synthetic 3D V-Cache, E-cores, AVX-512 or NPU resources.
 * Requires a target-matched sched_ext/libbpf SDK; no auto loading.
 */
#include <scx/common.bpf.h>

char _license[] SEC("license") = "GPL";

#define OX_DSQ_P 0x585001ULL
#define OX_DSQ_E 0x585002ULL
#define OX_CPU_UNKNOWN 0u
#define OX_CPU_P 1u
#define OX_CPU_E 2u
#define OX_HINT_NORMAL 0u
#define OX_HINT_BACKGROUND 1u
#define OX_HINT_LATENCY 2u
#define OX_SLICE_NS 500000ULL

UEI_DEFINE(uei);

/* Populated only after verified /sys/.../core_type discovery in userspace. */
struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, 4096);
    __type(key, u32);
    __type(value, u32);
} cpu_roles SEC(".maps");

/* Advisory, not an authorization mechanism; stale task IDs carry no privileges. */
struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 65536);
    __type(key, u32);
    __type(value, u32);
} task_hints SEC(".maps");

s32 BPF_STRUCT_OPS(omega_select_cpu, struct task_struct *p, s32 prev_cpu, u64 wake_flags)
{
    bool idle = false;
    s32 cpu = scx_bpf_select_cpu_dfl(p, prev_cpu, wake_flags, &idle);
    if (idle)
        scx_bpf_dsq_insert(p, SCX_DSQ_LOCAL, OX_SLICE_NS, 0);
    return cpu;
}

void BPF_STRUCT_OPS(omega_enqueue, struct task_struct *p, u64 enq_flags)
{
    u32 tid = BPF_CORE_READ(p, pid);
    u32 *hint = bpf_map_lookup_elem(&task_hints, &tid);
    u64 target = hint && *hint == OX_HINT_BACKGROUND ? OX_DSQ_E : OX_DSQ_P;
    /* Only user DSQs support vtime; global/local queues are FIFO. */
    scx_bpf_dsq_insert_vtime(p, target, OX_SLICE_NS, p->scx.dsq_vtime, enq_flags);
}

void BPF_STRUCT_OPS(omega_dispatch, s32 cpu, struct task_struct *prev)
{
    u32 key = (u32)cpu;
    u32 *role = bpf_map_lookup_elem(&cpu_roles, &key);
    if (role && *role == OX_CPU_E) {
        if (scx_bpf_dsq_move_to_local(OX_DSQ_E, 0))
            return;
        scx_bpf_dsq_move_to_local(OX_DSQ_P, 0);
    } else {
        if (scx_bpf_dsq_move_to_local(OX_DSQ_P, 0))
            return;
        scx_bpf_dsq_move_to_local(OX_DSQ_E, 0);
    }
}

s32 BPF_STRUCT_OPS_SLEEPABLE(omega_init)
{
    s32 err = scx_bpf_create_dsq(OX_DSQ_P, -1);
    if (err)
        return err;
    return scx_bpf_create_dsq(OX_DSQ_E, -1);
}

void BPF_STRUCT_OPS(omega_exit, struct scx_exit_info *ei)
{
    UEI_RECORD(uei, ei);
}

SEC(".struct_ops.link")
struct sched_ext_ops omega_ops = {
    .select_cpu = (void *)omega_select_cpu,
    .enqueue = (void *)omega_enqueue,
    .dispatch = (void *)omega_dispatch,
    .init = (void *)omega_init,
    .exit = (void *)omega_exit,
    .flags = SCX_OPS_SWITCH_PARTIAL,
    .name = "omega_x_optin",
};

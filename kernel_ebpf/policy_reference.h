/* SPDX-License-Identifier: MIT */
#ifndef OMEGA_SCX_POLICY_REFERENCE_H
#define OMEGA_SCX_POLICY_REFERENCE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Standalone executable model of enqueue/dispatch queue decisions.
 * Not the sched_ext kernel ABI, does not load BPF, never attaches to kernel.
 * A return value of 0 means no task selected.
 */
uint32_t omega_scx_choice(uint32_t opted_in, uint32_t cpu_role, uint32_t task_hint,
                          uint32_t p_ready, uint32_t e_ready);
#ifdef __cplusplus
}
#endif
#endif

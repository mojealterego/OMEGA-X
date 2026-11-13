/* SPDX-License-Identifier: MIT */
#include "policy_reference.h"

uint32_t omega_scx_choice(uint32_t opted_in, uint32_t cpu_role,
                          uint32_t task_hint, uint32_t p_ready,
                          uint32_t e_ready)
{
    (void)task_hint; /* The enqueue phase already placed tasks in P/E queues. */
    if (opted_in != 1u)
        return 0u;
    if (cpu_role == 2u) {
        if (e_ready > 0u)
            return 2u;
        return p_ready > 0u ? 1u : 0u;
    }
    if (p_ready > 0u)
        return 1u;
    return e_ready > 0u ? 2u : 0u;
}

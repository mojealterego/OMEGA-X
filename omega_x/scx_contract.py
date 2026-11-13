"""Portable high-level reference for a *subset* of the opt-in sched_ext policy.

This models only queue selection / fallback for physical CPU role hints.
It does not load, attach, compile or claim to validate the kernel BPF program.
"""

def policy_choice(opt_in: int, cpu_role: int, task_hint: int,
                  p_ready: int, e_ready: int) -> int:
    """0 no dispatch, 1 P queue, 2 E queue. Role 2 = E, others prefer P.

    Task hint is intentionally ignored at dispatch time; the BPF enqueue hook
    has already selected a queue based on the hint. This is a reference for
    the `dispatch` hook's fallback behavior, not a general-purpose scheduler.
    """
    if any(type(x) is not int or not 0 <= x <= 0xFFFFFFFF
           for x in (opt_in, cpu_role, task_hint, p_ready, e_ready)):
        raise ValueError('invalid u32 scheduler inputs')
    if opt_in != 1:
        return 0
    if cpu_role == 2:
        return 2 if e_ready else 1 if p_ready else 0
    return 1 if p_ready else 2 if e_ready else 0

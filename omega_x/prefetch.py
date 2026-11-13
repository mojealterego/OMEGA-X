"""Bounded per-task Markov transition learner with stride confidence and no IO."""
from collections import OrderedDict


class MarkovPrefetcher:
    def __init__(self, depth: int = 8, max_transitions: int = 4096, max_tasks: int = 1024):
        if not 1 <= depth <= 8 or not 16 <= max_transitions <= 65536 or not 1 <= max_tasks <= 4096:
            raise ValueError('prefetch budget outside bounds')
        self.depth = depth
        self.max_transitions = max_transitions
        self.max_tasks = max_tasks
        self.transitions: OrderedDict[tuple[int, int], dict[int, int]] = OrderedDict()
        self.history: OrderedDict[int, tuple[int, int | None, int]] = OrderedDict()

    @property
    def transition_count(self) -> int:
        return len(self.transitions)

    def observe(self, task_id: int, line: int) -> None:
        if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id < 0:
            raise ValueError('invalid task id')
        if isinstance(line, bool) or not isinstance(line, int) or not 0 <= line < 2**64:
            raise ValueError('invalid cache line')
        previous = self.history.get(task_id)
        delta = None
        confidence = 0
        if previous is not None:
            prev_line, prev_delta, streak = previous
            delta = line - prev_line
            confidence = streak + 1 if delta == prev_delta else 1
            key = (task_id, prev_line)
            successors = self.transitions.setdefault(key, {})
            successors[line] = min(2**31 - 1, successors.get(line, 0) + 1)
            if len(successors) > 4:
                evict = min(successors, key=lambda x: (successors[x], x))
                del successors[evict]
            self.transitions.move_to_end(key)
            while len(self.transitions) > self.max_transitions:
                self.transitions.popitem(last=False)
        self.history[task_id] = (line, delta, confidence)
        self.history.move_to_end(task_id)
        while len(self.history) > self.max_tasks:
            self.history.popitem(last=False)

    def predict(self, task_id: int, line: int) -> tuple[int, ...]:
        if not isinstance(line, int) or not 0 <= line < 2**64 - self.depth:
            return ()
        state = self.history.get(task_id)
        if state is not None and state[0] == line and state[2] >= 3 and state[1] is not None:
            delta = state[1]
            predicted = tuple(line + delta * i for i in range(1, self.depth + 1))
            if all(0 <= value < 2**64 for value in predicted):
                return predicted
        result = []
        current = line
        for _ in range(self.depth):
            successors = self.transitions.get((task_id, current))
            if not successors:
                break
            current = min(successors, key=lambda x: (-successors[x], x))
            result.append(current)
        return tuple(result)

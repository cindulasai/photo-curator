from __future__ import annotations
import math


class LLMBudgetCounter:
    """Tracks extra LLM calls added by critique loops."""

    def __init__(self, base_count: int, cap_fraction: float = 0.15):
        self._cap = math.floor(base_count * cap_fraction)
        self._used = 0

    @property
    def remaining(self) -> int:
        return max(0, self._cap - self._used)

    def charge(self, n: int = 1) -> bool:
        if self._used + n > self._cap:
            return False
        self._used += n
        return True

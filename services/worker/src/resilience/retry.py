"""Small provider-neutral retry policy; no sleeping in deterministic tests."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    jitter_ratio: float = 0.2

    def delay(self, attempt: int, retry_after: float | None = None, *, random_fn: Callable[[], float] = random.random) -> float:
        if attempt < 1:
            raise ValueError("attempt must be positive")
        exponential = min(self.max_delay_seconds, self.base_delay_seconds * (2 ** (attempt - 1)))
        requested = max(exponential, retry_after or 0.0)
        jitter = requested * self.jitter_ratio * random_fn()
        return min(self.max_delay_seconds, requested + jitter)


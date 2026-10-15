"""Redis-backed circuit breaker with deterministic clock injection."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class CircuitState:
    state: str
    failures: int
    opened_at: float | None = None


class RedisCircuitBreaker:
    def __init__(
        self,
        redis_client: Any,
        name: str,
        *,
        failure_threshold: int = 3,
        window_seconds: float = 60.0,
        cooldown_seconds: float = 30.0,
        max_half_open_probes: int = 1,
        clock: Callable[[], float] = time.monotonic,
        on_state_change: Callable[[str, str, str], None] | None = None,
    ) -> None:
        if failure_threshold <= 0 or max_half_open_probes <= 0:
            raise ValueError("circuit thresholds must be positive")
        self.redis = redis_client
        self.key = f"triphony:circuit:{name}"
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self.max_half_open_probes = max_half_open_probes
        self.clock = clock
        self.on_state_change = on_state_change or (lambda _old, _new, _reason: None)

    def _read(self) -> CircuitState:
        raw = self.redis.get(self.key)
        if not raw:
            return CircuitState("closed", 0)
        if isinstance(raw, bytes):
            raw = raw.decode()
        value = json.loads(raw)
        return CircuitState(value.get("state", "closed"), int(value.get("failures", 0)), value.get("opened_at"))

    def _write(self, state: CircuitState) -> None:
        self.redis.set(self.key, json.dumps(state.__dict__, separators=(",", ":")), ex=max(60, int(self.window_seconds + self.cooldown_seconds + 5)))

    def state(self) -> CircuitState:
        current = self._read()
        now = self.clock()
        if current.state == "open" and current.opened_at is not None and now - current.opened_at >= self.cooldown_seconds:
            return CircuitState("half_open", current.failures, current.opened_at)
        return current

    def allow(self) -> bool:
        current = self.state()
        if current.state == "closed":
            return True
        if current.state == "open":
            return False
        probe_key = f"{self.key}:probe"
        acquired = self.redis.set(probe_key, "1", nx=True, ex=max(1, int(self.cooldown_seconds)))
        return bool(acquired)

    def record_success(self) -> None:
        old = self.state().state
        self._write(CircuitState("closed", 0))
        if old != "closed":
            self.on_state_change(old, "closed", "success")

    def record_failure(self, *, infrastructure: bool = True) -> None:
        if not infrastructure:
            return
        current = self.state()
        if current.state == "open":
            return
        failures = current.failures + 1
        if failures >= self.failure_threshold or current.state == "half_open":
            self._write(CircuitState("open", failures, self.clock()))
            self.on_state_change(current.state, "open", "failure_threshold")
        else:
            self._write(CircuitState("closed", failures))


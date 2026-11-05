"""Small resilience primitives: a circuit breaker for the LLM dependency."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class CircuitBreaker:
    """Opens after `threshold` consecutive failures and stays open for `cooldown_s`.

    While open, callers skip the LLM entirely and go straight to degraded mode. After the cooldown
    one trial request is let through (half-open); success closes the breaker, failure re-opens it.
    This stops an outage from making every customer wait out the full request timeout.
    """

    def __init__(self, threshold: int = 3, cooldown_s: float = 30.0, clock: Callable[[], float] = time.monotonic):
        self.threshold, self.cooldown_s, self._clock = threshold, cooldown_s, clock
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._opened_at is None:
                return "closed"
            return "half-open" if self._clock() - self._opened_at >= self.cooldown_s else "open"

    def allow(self) -> bool:
        return self.state != "open"

    def record_success(self) -> None:
        with self._lock:
            self._failures, self._opened_at = 0, None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.threshold or self._opened_at is not None:
                self._opened_at = self._clock()

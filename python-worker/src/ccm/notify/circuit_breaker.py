from __future__ import annotations

import time
from enum import IntEnum


class CircuitState(IntEnum):
    CLOSED = 0
    OPEN = 1
    HALF_OPEN = 2


class CircuitOpenError(RuntimeError):
    pass


class CircuitBreaker:
    def __init__(self, failure_threshold: int, open_seconds: float):
        self.failure_threshold = failure_threshold
        self.open_seconds = open_seconds
        self.failures = 0
        self.state = CircuitState.CLOSED
        self.opened_at = 0.0

    def allow(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self.opened_at >= self.open_seconds:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        return True  # half-open: allow a probe

    def record_success(self) -> None:
        self.failures = 0
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self.failures += 1
        if self.state == CircuitState.HALF_OPEN or self.failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = time.time()

    def guard(self) -> None:
        if not self.allow():
            raise CircuitOpenError("circuit breaker is open")

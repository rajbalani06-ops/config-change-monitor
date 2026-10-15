from __future__ import annotations

import threading
import time
from collections.abc import Callable


class Debouncer:
    def __init__(self, delay_ms: int, callback: Callable[[str, str], None]):
        self.delay = delay_ms / 1000.0
        self.callback = callback
        self._lock = threading.Lock()
        self._timers: dict[str, threading.Timer] = {}
        self._latest: dict[str, str] = {}

    def submit(self, path: str, event_kind: str) -> None:
        with self._lock:
            self._latest[path] = event_kind
            existing = self._timers.get(path)
            if existing:
                existing.cancel()
            timer = threading.Timer(self.delay, self._fire, args=(path,))
            timer.daemon = True
            self._timers[path] = timer
            timer.start()

    def _fire(self, path: str) -> None:
        with self._lock:
            kind = self._latest.pop(path, "modified")
            self._timers.pop(path, None)
        self.callback(path, kind)

    def pending_count(self) -> int:
        with self._lock:
            return len(self._timers)

    def shutdown(self) -> None:
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
            self._latest.clear()

    def flush_now(self, path: str) -> None:
        """Used by tests to skip wall-clock waiting."""
        time.sleep(0)
        self._fire(path)

from __future__ import annotations

import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def compute_backoff_ms(attempt: int, base_ms: int, max_ms: int) -> int:
    exp = min(max_ms, base_ms * (2 ** max(attempt - 1, 0)))
    jitter = random.randint(0, max(base_ms, 1))
    return min(max_ms, exp + jitter)


def retry_after_ms(headers: dict[str, str] | None) -> int | None:
    if not headers:
        return None
    value = headers.get("Retry-After") or headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0, int(value) * 1000)
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
            delta = (dt - datetime.now(timezone.utc)).total_seconds()
            return max(0, int(delta * 1000))
        except Exception:
            return None


def is_retryable_status(status: int) -> bool:
    return status in RETRYABLE_STATUS

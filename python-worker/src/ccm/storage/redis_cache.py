from __future__ import annotations

from typing import Any


class SnapshotCache:
    """Optional Redis cache. PostgreSQL remains source of truth.

    Cache is only used as a hint. A miss or Redis outage never suppresses events.
    Entries are invalidated whenever a valid snapshot is stored or a file is deleted.
    A cached hash equal to the current hash may skip a parse only after durable
    snapshot metadata is also confirmed by the caller.
    """

    def __init__(self, client=None, ttl_seconds: int = 3600):
        self.client = client
        self.ttl = ttl_seconds

    def get_hash(self, file_id: str) -> str | None:
        if self.client is None:
            return None
        try:
            value = self.client.get(self._key(file_id))
            if value is None:
                return None
            return value.decode() if isinstance(value, bytes) else str(value)
        except Exception:
            return None

    def set_hash(self, file_id: str, content_hash: str) -> None:
        if self.client is None:
            return
        try:
            self.client.setex(self._key(file_id), self.ttl, content_hash)
        except Exception:
            return

    def invalidate(self, file_id: str) -> None:
        if self.client is None:
            return
        try:
            self.client.delete(self._key(file_id))
        except Exception:
            return

    def _key(self, file_id: str) -> str:
        return f"ccm:snap:{file_id}"


class InMemoryRedis:
    def __init__(self):
        self.store: dict[str, Any] = {}

    def get(self, key: str):
        return self.store.get(key)

    def setex(self, key: str, ttl: int, value: str):
        self.store[key] = value

    def delete(self, key: str):
        self.store.pop(key, None)

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonicalize(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def content_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def structure_hash(data: Any) -> str:
    return hashlib.sha256(canonicalize(data).encode("utf-8")).hexdigest()


class MemorySnapshotStore:
    def __init__(self):
        self._by_file: dict[str, dict[str, Any]] = {}

    def get(self, file_id: str) -> dict[str, Any] | None:
        return self._by_file.get(file_id)

    def save_valid(self, file_id: str, data: Any, raw_hash: str) -> None:
        self._by_file[file_id] = {
            "data": data,
            "raw_hash": raw_hash,
            "structure_hash": structure_hash(data),
            "valid": True,
        }

    def mark_invalid(self, file_id: str) -> None:
        current = self._by_file.get(file_id)
        if current:
            current = dict(current)
            current["valid"] = False
            self._by_file[file_id] = current

    def clear(self, file_id: str) -> None:
        self._by_file.pop(file_id, None)

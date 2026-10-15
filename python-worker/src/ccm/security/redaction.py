from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"


class Redactor:
    """Pattern-based key redaction.

    Limitations: only key-name patterns are matched. Values that look like
    secrets but live under innocuous keys are not detected. Nested keys are
    matched against the leaf name and the full dotted path.
    """

    def __init__(self, patterns: list[str]):
        self._compiled = [re.compile(p, re.IGNORECASE) for p in patterns]

    def is_sensitive(self, key: str) -> bool:
        leaf = key.split(".")[-1].replace("\\.", ".")
        return any(p.search(leaf) or p.search(key) for p in self._compiled)

    def redact_tree(self, data: Any, prefix: str = "") -> Any:
        if isinstance(data, dict):
            out = {}
            for k, v in data.items():
                path = f"{prefix}.{k}" if prefix else str(k)
                if self.is_sensitive(str(k)) or self.is_sensitive(path):
                    out[k] = REDACTED
                else:
                    out[k] = self.redact_tree(v, path)
            return out
        if isinstance(data, list):
            return [self.redact_tree(v, f"{prefix}.{i}") for i, v in enumerate(data)]
        return data

    def redact_flat_changes(self, changes: dict[str, Any]) -> dict[str, Any]:
        redacted = {"added": {}, "updated": {}, "removed": {}, "type_changes": {}}
        for path, value in (changes.get("added") or {}).items():
            redacted["added"][path] = REDACTED if self.is_sensitive(path) else value
        for path, value in (changes.get("removed") or {}).items():
            redacted["removed"][path] = REDACTED if self.is_sensitive(path) else value
        for path, payload in (changes.get("updated") or {}).items():
            if self.is_sensitive(path):
                redacted["updated"][path] = {"changed": True, "redacted": True}
            else:
                redacted["updated"][path] = payload
        for path, payload in (changes.get("type_changes") or {}).items():
            if self.is_sensitive(path):
                redacted["type_changes"][path] = {
                    "oldType": payload.get("oldType"),
                    "newType": payload.get("newType"),
                    "changed": True,
                    "redacted": True,
                }
            else:
                redacted["type_changes"][path] = payload
        return redacted

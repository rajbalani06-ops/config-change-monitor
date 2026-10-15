from __future__ import annotations

from typing import Any

from ccm.diff.paths import join_path


def value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "number"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


class DiffEngine:
    def diff(self, old: Any, new: Any, parent: str = "") -> dict[str, dict]:
        added: dict[str, Any] = {}
        removed: dict[str, Any] = {}
        updated: dict[str, Any] = {}
        type_changes: dict[str, Any] = {}
        self._walk(old, new, parent, added, removed, updated, type_changes)
        return {
            "added": dict(sorted(added.items())),
            "removed": dict(sorted(removed.items())),
            "updated": dict(sorted(updated.items())),
            "type_changes": dict(sorted(type_changes.items())),
        }

    def has_changes(self, changes: dict) -> bool:
        return any(changes[k] for k in ("added", "removed", "updated", "type_changes"))

    def _walk(
        self,
        old: Any,
        new: Any,
        parent: str,
        added: dict,
        removed: dict,
        updated: dict,
        type_changes: dict,
    ) -> None:
        if old is new:
            return
        old_t = value_type(old)
        new_t = value_type(new)
        if old_t != new_t:
            if parent:
                type_changes[parent] = {
                    "oldType": old_t,
                    "newType": new_t,
                    "old": old,
                    "new": new,
                }
            elif old_t == "object" and new_t == "object":
                pass
            else:
                type_changes["$"] = {
                    "oldType": old_t,
                    "newType": new_t,
                    "old": old,
                    "new": new,
                }
            if old_t in {"object", "array"} or new_t in {"object", "array"}:
                if old_t in {"object", "array"}:
                    self._collect(old, parent, removed)
                if new_t in {"object", "array"}:
                    self._collect(new, parent, added)
            return
        if old_t == "object":
            old_keys = set(old.keys())
            new_keys = set(new.keys())
            for key in sorted(old_keys - new_keys, key=str):
                self._collect(old[key], join_path(parent, str(key)), removed)
            for key in sorted(new_keys - old_keys, key=str):
                self._collect(new[key], join_path(parent, str(key)), added)
            for key in sorted(old_keys & new_keys, key=str):
                self._walk(
                    old[key],
                    new[key],
                    join_path(parent, str(key)),
                    added,
                    removed,
                    updated,
                    type_changes,
                )
            return
        if old_t == "array":
            max_len = max(len(old), len(new))
            for idx in range(max_len):
                path = join_path(parent, str(idx))
                if idx >= len(old):
                    self._collect(new[idx], path, added)
                elif idx >= len(new):
                    self._collect(old[idx], path, removed)
                else:
                    old_item, new_item = old[idx], new[idx]
                    scalar_types = {"null", "boolean", "number", "string"}
                    if value_type(old_item) in scalar_types and value_type(new_item) in scalar_types:
                        if old_item != new_item:
                            updated[path] = {"old": old_item, "new": new_item}
                    else:
                        self._walk(old_item, new_item, path, added, removed, updated, type_changes)
            return
        if old != new:
            if parent:
                updated[parent] = {"old": old, "new": new}
            else:
                updated["$"] = {"old": old, "new": new}

    def _collect(self, value: Any, path: str, bucket: dict) -> None:
        t = value_type(value)
        if t == "object":
            if not value:
                bucket[path] = value
                return
            for key in sorted(value.keys(), key=str):
                self._collect(value[key], join_path(path, str(key)), bucket)
            return
        if t == "array":
            if not value:
                bucket[path] = value
                return
            for idx, item in enumerate(value):
                self._collect(item, join_path(path, str(idx)), bucket)
            return
        bucket[path] = value

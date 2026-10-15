from __future__ import annotations

import os
import time
from pathlib import Path


TEMP_SUFFIXES = {".swp", ".swx", ".tmp", ".temp", ".bak"}
TEMP_PREFIXES = (".", "~")
EDITOR_PATTERNS = (".swp", ".swo", ".orig")


def is_editor_temp(path: str | Path) -> bool:
    p = Path(path)
    name = p.name
    if name.endswith("~"):
        return True
    if name.startswith(".#") or name.startswith(".~"):
        return True
    if p.suffix.lower() in TEMP_SUFFIXES and p.suffix.lower() not in {".env"}:
        return True
    if name.startswith(".") and name.endswith(".swp"):
        return True
    return False


def wait_until_stable(path: Path, stable_ms: int, timeout_ms: int = 5000) -> bool:
    if not path.exists():
        return False
    delay = max(stable_ms, 1) / 1000.0
    deadline = time.time() + (timeout_ms / 1000.0)
    last = None
    while time.time() < deadline:
        try:
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            time.sleep(delay)
            continue
        if last == signature:
            return True
        last = signature
        time.sleep(delay)
    return False


def read_stable(path: Path, stable_ms: int) -> tuple[bytes | None, str | None]:
    """Return (bytes, error_kind). error_kind is permission/missing/unstable."""
    if is_editor_temp(path):
        return None, "temp"
    if not path.exists():
        return None, "missing"
    if not wait_until_stable(path, stable_ms):
        return None, "unstable"
    try:
        with open(path, "rb") as handle:
            return handle.read(), None
    except PermissionError:
        return None, "permission"
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "io"

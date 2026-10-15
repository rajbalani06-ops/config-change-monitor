from __future__ import annotations


def escape_key(key: str) -> str:
    return str(key).replace("\\", "\\\\").replace(".", "\\.")


def join_path(parent: str, key: str) -> str:
    escaped = escape_key(key)
    return escaped if not parent else f"{parent}.{escaped}"


def split_path(path: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(path):
        ch = path[i]
        if ch == "\\" and i + 1 < len(path):
            buf.append(path[i + 1])
            i += 2
            continue
        if ch == ".":
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts

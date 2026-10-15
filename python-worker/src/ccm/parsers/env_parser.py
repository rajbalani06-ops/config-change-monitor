from __future__ import annotations

import io
import re
from typing import Any

from dotenv import dotenv_values

from ccm.parsers.base import ConfigParser, ParseError, ParseResult


UNQUOTED_INVALID = re.compile(r"^\s*[^#\s][^=]*\s*$", re.MULTILINE)


class EnvParser(ConfigParser):
    format_name = "env"
    extensions = (".env",)

    def parse(self, text: str) -> ParseResult:
        stripped = text.strip()
        if stripped == "":
            return ParseResult(data={}, format_name=self.format_name, empty=True)
        warnings: list[str] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            if raw.startswith("export "):
                raw = raw[len("export ") :].strip()
            if "=" not in raw:
                raise ParseError(f"invalid .env syntax at line {line_no}", self.format_name)
        try:
            values = dotenv_values(stream=io.StringIO(text))
        except Exception as exc:
            raise ParseError(f"invalid .env syntax: {exc}", self.format_name) from exc
        data: dict[str, Any] = {}
        for key, value in values.items():
            if key is None:
                continue
            data[key] = _coerce(value)
        return ParseResult(data=data, format_name=self.format_name, warnings=warnings)


def _coerce(value: str | None) -> Any:
    if value is None:
        return ""
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null" or lowered == "none":
        return None
    try:
        if value.strip().isdigit() or (value.strip().startswith("-") and value.strip()[1:].isdigit()):
            return int(value.strip())
        if _is_float(value.strip()):
            return float(value.strip())
    except ValueError:
        return value
    return value


def _is_float(value: str) -> bool:
    try:
        float(value)
        return "." in value or "e" in value.lower()
    except ValueError:
        return False

from __future__ import annotations

import re
from typing import Any

from ccm.parsers.base import ConfigParser, ParseError, ParseResult


class PropertiesParser(ConfigParser):
    format_name = "properties"
    extensions = (".properties",)

    def parse(self, text: str) -> ParseResult:
        stripped = text.strip()
        if stripped == "":
            return ParseResult(data={}, format_name=self.format_name, empty=True)
        data: dict[str, Any] = {}
        pending = ""
        for line_no, line in enumerate(text.splitlines(), start=1):
            if pending:
                line = pending + line.lstrip()
                pending = ""
            if line.endswith("\\") and not line.endswith("\\\\"):
                pending = line[:-1]
                continue
            raw = line.strip()
            if not raw or raw.startswith("#") or raw.startswith("!"):
                continue
            match = re.split(r"(?<!\\)[=:]", raw, maxsplit=1)
            if len(match) != 2:
                raise ParseError(f"invalid .properties syntax at line {line_no}", self.format_name)
            key = _unescape(match[0].strip())
            value = _unescape(match[1].strip())
            if key in data:
                raise ParseError(f"duplicate properties key: {key}", self.format_name)
            data[key] = _coerce(value)
        if pending:
            raise ParseError("unterminated continuation line", self.format_name)
        return ParseResult(data=data, format_name=self.format_name)


def _unescape(value: str) -> str:
    value = value.replace(r"\t", "\t").replace(r"\n", "\n").replace(r"\r", "\r")
    value = value.replace(r"\=", "=").replace(r"\:", ":").replace(r"\ ", " ")

    def repl(match: re.Match[str]) -> str:
        return chr(int(match.group(1), 16))

    return re.sub(r"\\u([0-9a-fA-F]{4})", repl, value)


def _coerce(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value

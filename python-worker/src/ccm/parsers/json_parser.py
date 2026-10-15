from __future__ import annotations

import json
from typing import Any

from ccm.parsers.base import ConfigParser, ParseError, ParseResult


class JsonParser(ConfigParser):
    format_name = "json"
    extensions = (".json",)

    def parse(self, text: str) -> ParseResult:
        stripped = text.strip()
        if stripped == "":
            return ParseResult(data={}, format_name=self.format_name, empty=True)
        try:
            data: Any = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ParseError(f"malformed JSON: {exc.msg}", self.format_name) from exc
        if not isinstance(data, (dict, list)):
            raise ParseError("JSON root must be an object or array", self.format_name)
        return ParseResult(data=data, format_name=self.format_name)

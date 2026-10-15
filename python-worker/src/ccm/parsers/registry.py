from __future__ import annotations

from pathlib import Path

from ccm.parsers.base import ConfigParser, ParseError, ParseResult
from ccm.parsers.env_parser import EnvParser
from ccm.parsers.json_parser import JsonParser
from ccm.parsers.properties_parser import PropertiesParser
from ccm.parsers.yaml_parser import YamlParser


class ParserRegistry:
    def __init__(self, parsers: list[ConfigParser] | None = None):
        self._parsers = parsers or [JsonParser(), YamlParser(), EnvParser(), PropertiesParser()]
        self._by_ext: dict[str, ConfigParser] = {}
        for parser in self._parsers:
            for ext in parser.extensions:
                self._by_ext[ext] = parser

    def for_path(self, path: str | Path) -> ConfigParser:
        p = Path(path)
        name = p.name
        if name == ".env":
            return self._by_ext[".env"]
        ext = p.suffix.lower()
        if ext not in self._by_ext:
            raise ParseError(f"no parser for extension {ext}", "unknown")
        return self._by_ext[ext]

    def parse_text(self, path: str | Path, text: str) -> ParseResult:
        return self.for_path(path).parse(text)

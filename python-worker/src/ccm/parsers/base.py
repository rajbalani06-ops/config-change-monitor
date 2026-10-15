from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class ParseError(Exception):
    def __init__(self, message: str, format_name: str):
        super().__init__(message)
        self.format_name = format_name


@dataclass
class ParseResult:
    data: dict[str, Any] | list[Any] | None
    format_name: str
    warnings: list[str] = field(default_factory=list)
    empty: bool = False


class ConfigParser(ABC):
    format_name: str
    extensions: tuple[str, ...]

    @abstractmethod
    def parse(self, text: str) -> ParseResult:
        raise NotImplementedError

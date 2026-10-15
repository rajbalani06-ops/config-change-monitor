from pathlib import Path

import pytest

from ccm.parsers.base import ParseError
from ccm.parsers.registry import ParserRegistry

REG = ParserRegistry()


def parse(name: str, text: str):
    return REG.parse_text(name, text)


def test_json_nested_types():
    result = parse("a.json", '{"n": 1, "s": "x", "b": true, "z": null, "arr": [1, "a"], "o": {"k": 2}}')
    assert result.data["n"] == 1
    assert result.data["s"] == "x"
    assert result.data["b"] is True
    assert result.data["z"] is None
    assert result.data["arr"] == [1, "a"]
    assert result.data["o"]["k"] == 2


def test_json_empty_and_malformed():
    assert parse("a.json", "").empty
    with pytest.raises(ParseError):
        parse("a.json", "{")


def test_json_unicode():
    result = parse("a.json", '{"city": "München"}')
    assert result.data["city"] == "München"


def test_yaml_nested_and_duplicates():
    result = parse("a.yaml", "db:\n  host: localhost\nlist:\n  - 1\n  - two\n")
    assert result.data["db"]["host"] == "localhost"
    assert result.data["list"] == [1, "two"]
    with pytest.raises(ParseError, match="duplicate"):
        parse("a.yaml", "a: 1\na: 2\n")
    with pytest.raises(ParseError):
        parse("a.yml", ":\n  -")


def test_yaml_empty():
    assert parse("a.yaml", "").empty


def test_env_parser():
    result = parse(".env", "HOST=localhost\nDEBUG=true\nPORT=8080\nNAME=München\nEMPTY=\n# comment\nexport FOO=bar\n")
    assert result.data["HOST"] == "localhost"
    assert result.data["DEBUG"] is True
    assert result.data["PORT"] == 8080
    assert result.data["NAME"] == "München"
    assert result.data["FOO"] == "bar"
    with pytest.raises(ParseError):
        parse(".env", "NOT_A_KEY\n")


def test_properties_parser():
    result = parse("a.properties", "db.host=localhost\nflag=true\nnum=3.5\nunicode=\\u0041\n")
    assert result.data["db.host"] == "localhost"
    assert result.data["flag"] is True
    assert result.data["num"] == 3.5
    assert result.data["unicode"] == "A"
    with pytest.raises(ParseError, match="duplicate"):
        parse("a.properties", "a=1\na=2\n")
    with pytest.raises(ParseError):
        parse("a.properties", "no-separator\n")


def test_registry_unknown_extension():
    with pytest.raises(ParseError):
        parse("file.txt", "x=1")

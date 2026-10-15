from __future__ import annotations

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

from ccm.parsers.base import ConfigParser, ParseError, ParseResult


class DuplicateKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: yaml.SafeLoader, node: MappingNode, deep: bool = False):
    if not isinstance(node, MappingNode):
        raise ConstructorError(None, None, f"expected a mapping node, got {node.id}", node.start_mark)
    loader.flatten_mapping(node)
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ParseError(f"duplicate YAML key: {key}", "yaml")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


DuplicateKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


class YamlParser(ConfigParser):
    format_name = "yaml"
    extensions = (".yaml", ".yml")

    def parse(self, text: str) -> ParseResult:
        stripped = text.strip()
        if stripped == "":
            return ParseResult(data={}, format_name=self.format_name, empty=True)
        try:
            data = yaml.load(text, Loader=DuplicateKeySafeLoader)
        except ParseError:
            raise
        except yaml.YAMLError as exc:
            raise ParseError(f"invalid YAML: {exc}", self.format_name) from exc
        if data is None:
            return ParseResult(data={}, format_name=self.format_name, empty=True)
        if not isinstance(data, (dict, list)):
            raise ParseError("YAML root must be a mapping or sequence", self.format_name)
        return ParseResult(data=data, format_name=self.format_name)

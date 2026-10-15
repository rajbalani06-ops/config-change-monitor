from ccm.diff.engine import DiffEngine, value_type
from ccm.diff.paths import escape_key, join_path, split_path

ENG = DiffEngine()


def test_added_removed_updated():
    old = {"a": 1, "b": 2, "c": True}
    new = {"a": 1, "b": 3, "d": 4}
    d = ENG.diff(old, new)
    assert d["added"] == {"d": 4}
    assert d["removed"] == {"c": True}
    assert d["updated"]["b"] == {"old": 2, "new": 3}


def test_nested_and_type_change():
    old = {"logging": {"level": "info"}, "featureFlags": "off"}
    new = {"logging": {"level": "debug"}, "featureFlags": {"x": True}}
    d = ENG.diff(old, new)
    assert d["updated"]["logging.level"] == {"old": "info", "new": "debug"}
    assert d["type_changes"]["featureFlags"]["oldType"] == "string"
    assert d["type_changes"]["featureFlags"]["newType"] == "object"
    assert d["added"]["featureFlags.x"] is True


def test_arrays_and_null():
    old = {"items": [1, None, "x"], "n": None}
    new = {"items": [1, 2], "n": 0}
    d = ENG.diff(old, new)
    assert d["updated"]["items.1"] == {"old": None, "new": 2}
    assert d["removed"]["items.2"] == "x"
    assert d["type_changes"]["n"]["oldType"] == "null"
    assert d["type_changes"]["n"]["newType"] == "number"


def test_number_to_string():
    d = ENG.diff({"port": 80}, {"port": "80"})
    assert d["type_changes"]["port"]["oldType"] == "number"
    assert d["type_changes"]["port"]["newType"] == "string"


def test_dot_escaping():
    path = join_path("", "db.host")
    assert path == r"db\.host"
    assert split_path(path) == ["db.host"]
    old = {"db.host": 1, "nested": {"x.y": 2}}
    new = {"db.host": 2, "nested": {"x.y": 2}}
    d = ENG.diff(old, new)
    assert r"db\.host" in d["updated"]


def test_deterministic_key_order():
    d1 = ENG.diff({"z": 1, "a": 1}, {"z": 1, "a": 2, "m": 3})
    d2 = ENG.diff({"a": 1, "z": 1}, {"m": 3, "a": 2, "z": 1})
    assert list(d1["added"].keys()) == list(d2["added"].keys())
    assert list(d1["updated"].keys()) == list(d2["updated"].keys())


def test_types():
    assert value_type(None) == "null"
    assert value_type(True) == "boolean"
    assert value_type(1) == "number"
    assert value_type([]) == "array"
    assert value_type({}) == "object"
    assert escape_key("a.b") == r"a\.b"

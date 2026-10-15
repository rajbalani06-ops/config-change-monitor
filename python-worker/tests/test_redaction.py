from ccm.security.redaction import REDACTED, Redactor

R = Redactor(["password", "token", "api[_-]?key", "secret"])


def test_redact_tree():
    data = {"db": {"password": "s3cret", "host": "localhost"}, "API_KEY": "abc"}
    out = R.redact_tree(data)
    assert out["db"]["password"] == REDACTED
    assert out["db"]["host"] == "localhost"
    assert out["API_KEY"] == REDACTED


def test_redact_changes_hides_secret_values():
    changes = {
        "added": {"db.password": "n"},
        "removed": {"old.token": "t"},
        "updated": {"db.host": {"old": "a", "new": "b"}, "api_key": {"old": "1", "new": "2"}},
        "type_changes": {},
    }
    out = R.redact_flat_changes(changes)
    assert out["added"]["db.password"] == REDACTED
    assert out["removed"]["old.token"] == REDACTED
    assert out["updated"]["api_key"] == {"changed": True, "redacted": True}
    assert out["updated"]["db.host"]["new"] == "b"

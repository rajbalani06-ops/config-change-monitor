from ccm.diff.engine import DiffEngine
from ccm.events.processor import ChangeProcessor
from ccm.parsers.registry import ParserRegistry
from ccm.security.redaction import Redactor
from ccm.snapshots.manager import MemorySnapshotStore, content_hash
from ccm.storage.redis_cache import InMemoryRedis, SnapshotCache


class RecordingSink:
    def __init__(self):
        self.events = []
        self.errors = []

    def persist_change(self, **kwargs):
        self.events.append(kwargs)

    def mark_file_error(self, file_id, error):
        self.errors.append((file_id, error))


def make_proc(emit_initial=False, cache=None):
    sink = RecordingSink()
    proc = ChangeProcessor(
        ParserRegistry(),
        DiffEngine(),
        Redactor(["password", "secret", "token"]),
        MemorySnapshotStore(),
        sink=sink,
        emit_initial=emit_initial,
        cache=cache,
    )
    return proc, sink


def test_creation_modification_deletion():
    proc, sink = make_proc(emit_initial=True)
    r1 = proc.process_bytes(
        file_id="f1", tenant_id="t", display_path="c.json",
        raw=b'{"a": 1}', operation_hint="created",
    )
    assert r1.emitted and r1.reason == "created"
    r2 = proc.process_bytes(
        file_id="f1", tenant_id="t", display_path="c.json",
        raw=b'{"a": 2, "b": true}', operation_hint="modified",
    )
    assert r2.event["changes"]["updated"]["a"]["new"] == 2
    assert r2.event["changes"]["added"]["b"] is True
    r3 = proc.process_bytes(
        file_id="f1", tenant_id="t", display_path="c.json",
        raw=None, operation_hint="deleted", missing=True,
    )
    assert r3.event["operation"] == "deleted"
    assert "a" in r3.event["changes"]["removed"]


def test_recreation_after_deletion_emits_created_event_by_default():
    proc, _ = make_proc(emit_initial=False)
    first = proc.process_bytes(file_id="f1", tenant_id="t", display_path="c.json", raw=b'{"a":1}', operation_hint="created")
    assert first.reason == "initial_snapshot"
    deleted = proc.process_bytes(file_id="f1", tenant_id="t", display_path="c.json", raw=None, operation_hint="deleted", missing=True)
    assert deleted.emitted
    recreated = proc.process_bytes(file_id="f1", tenant_id="t", display_path="c.json", raw=b'{"a":2}', operation_hint="created")
    assert recreated.emitted
    assert recreated.event["operation"] == "created"


def test_failed_event_transaction_does_not_advance_memory_snapshot():
    class FailingSink(RecordingSink):
        def persist_change(self, **kwargs):
            raise RuntimeError("database unavailable")

    snapshots = MemorySnapshotStore()
    proc = ChangeProcessor(ParserRegistry(), DiffEngine(), Redactor([]), snapshots, sink=FailingSink(), emit_initial=True)
    try:
        proc.process_bytes(file_id="f1", tenant_id="t", display_path="c.json", raw=b'{"a":1}', operation_hint="created")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected persistence error")
    assert snapshots.get("f1") is None


def test_initial_snapshot_does_not_emit_by_default():
    proc, sink = make_proc(emit_initial=False)
    r = proc.process_bytes(
        file_id="f1", tenant_id="t", display_path="c.json",
        raw=b'{"a": 1}', operation_hint="created",
    )
    assert not r.emitted and r.reason == "initial_snapshot"
    assert sink.events == []


def test_invalid_keeps_last_valid_snapshot():
    proc, sink = make_proc(emit_initial=True)
    proc.process_bytes(file_id="f1", tenant_id="t", display_path="c.json", raw=b'{"a": 1}', operation_hint="created")
    invalid = proc.process_bytes(
        file_id="f1", tenant_id="t", display_path="c.json",
        raw=b"{not-json", operation_hint="modified",
    )
    assert not invalid.emitted
    assert sink.errors
    later = proc.process_bytes(
        file_id="f1", tenant_id="t", display_path="c.json",
        raw=b'{"a": 2}', operation_hint="modified",
    )
    assert later.emitted
    assert later.event["changes"]["updated"]["a"]["old"] == 1


def test_content_hash_dedup():
    proc, _ = make_proc(emit_initial=True)
    raw = b'{"a": 1}'
    proc.process_bytes(file_id="f1", tenant_id="t", display_path="c.json", raw=raw, operation_hint="created")
    again = proc.process_bytes(file_id="f1", tenant_id="t", display_path="c.json", raw=raw, operation_hint="modified")
    assert again.reason == "duplicate_hash"


def test_secret_redaction_in_event():
    proc, _ = make_proc(emit_initial=True)
    proc.process_bytes(file_id="f1", tenant_id="t", display_path="c.json", raw=b'{"password": "a"}', operation_hint="created")
    out = proc.process_bytes(
        file_id="f1", tenant_id="t", display_path="c.json",
        raw=b'{"password": "b"}', operation_hint="modified",
    )
    payload = out.event["changes"]["updated"]["password"]
    assert payload["redacted"] is True
    assert "old" not in payload


def test_snapshot_recovery_hydrate():
    proc, _ = make_proc()
    proc.hydrate_from_durable("f1", {"a": 1}, content_hash(b'{"a":1}'))
    out = proc.process_bytes(
        file_id="f1", tenant_id="t", display_path="c.json",
        raw=b'{"a": 2}', operation_hint="modified",
    )
    assert out.event["changes"]["updated"]["a"]["old"] == 1


def test_redis_hit_and_unavailable():
    cache = SnapshotCache(InMemoryRedis())
    proc, _ = make_proc(emit_initial=True, cache=cache)
    raw = b'{"a": 1}'
    proc.process_bytes(file_id="f1", tenant_id="t", display_path="c.json", raw=raw, operation_hint="created")
    assert cache.get_hash("f1") is not None
    cache.invalidate("f1")
    assert cache.get_hash("f1") is None
    dead = SnapshotCache(None)
    proc2, _ = make_proc(emit_initial=True, cache=dead)
    r = proc2.process_bytes(file_id="f2", tenant_id="t", display_path="c.json", raw=raw, operation_hint="created")
    assert r.emitted


class BoomRedis:
    def get(self, key):
        raise RuntimeError("down")

    def setex(self, *a, **k):
        raise RuntimeError("down")

    def delete(self, key):
        raise RuntimeError("down")


def test_redis_errors_are_non_fatal():
    proc, _ = make_proc(emit_initial=True, cache=SnapshotCache(BoomRedis()))
    r = proc.process_bytes(file_id="f1", tenant_id="t", display_path="c.json", raw=b'{"a":1}', operation_hint="created")
    assert r.emitted

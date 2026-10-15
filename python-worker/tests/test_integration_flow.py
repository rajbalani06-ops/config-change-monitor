"""Logical end-to-end flow without external internet services."""

from pathlib import Path

from ccm.diff.engine import DiffEngine
from ccm.events.processor import ChangeProcessor
from ccm.events.schema import ChangeEvent
from ccm.notify.webhook import DeliveryResult
from ccm.parsers.registry import ParserRegistry
from ccm.security.redaction import Redactor
from ccm.snapshots.manager import MemorySnapshotStore
from ccm.storage.redis_cache import InMemoryRedis, SnapshotCache
from ccm.workers.webhook_worker import NotificationHandler
from ccm.config import Settings
from test_webhook_worker import FakeDestDb, FakePublisher, FakeClient, sample_event


def test_file_modify_persist_deliver_retry_dlq_replay(tmp_path: Path):
    config = tmp_path / "app.yaml"
    config.write_text("db:\n  host: localhost\n", encoding="utf-8")
    sink_events = []

    class Sink:
        def persist_change(self, **kwargs):
            sink_events.append(kwargs)

        def mark_file_error(self, file_id, error):
            pass

    proc = ChangeProcessor(
        ParserRegistry(),
        DiffEngine(),
        Redactor(["password"]),
        MemorySnapshotStore(),
        sink=Sink(),
        emit_initial=True,
        cache=SnapshotCache(InMemoryRedis()),
    )
    created = proc.process_bytes(
        file_id="file-1",
        tenant_id="t",
        display_path="app.yaml",
        raw=config.read_bytes(),
        operation_hint="created",
    )
    assert created.emitted
    config.write_text("db:\n  host: prod-db\n  password: hunter2\n", encoding="utf-8")
    modified = proc.process_bytes(
        file_id="file-1",
        tenant_id="t",
        display_path="app.yaml",
        raw=config.read_bytes(),
        operation_hint="modified",
    )
    assert modified.emitted
    assert modified.event["changes"]["updated"]["db.host"]["new"] == "prod-db"
    assert modified.event["changes"]["added"]["db.password"] == "[REDACTED]"
    assert sink_events[-1]["event"]["event_id"] == modified.event["event_id"]
    ChangeEvent.model_validate(modified.event)

    config.write_text("db: [unterminated", encoding="utf-8")
    invalid = proc.process_bytes(
        file_id="file-1",
        tenant_id="t",
        display_path="app.yaml",
        raw=config.read_bytes(),
        operation_hint="modified",
    )
    assert not invalid.emitted
    config.write_text("db:\n  host: other\n  password: x\n", encoding="utf-8")
    recovered = proc.process_bytes(
        file_id="file-1",
        tenant_id="t",
        display_path="app.yaml",
        raw=config.read_bytes(),
        operation_hint="modified",
    )
    assert recovered.event["changes"]["updated"]["db.host"]["old"] == "prod-db"

    settings = Settings(webhook_max_retries=2, webhook_allow_private_networks=True)
    db = FakeDestDb()
    pub = FakePublisher()
    ok = NotificationHandler(settings, db, pub, __import__("logging").getLogger("t"), FakeClient([DeliveryResult(True, 200, False, None)]))
    assert ok.deliver_event(modified.event) == "ack"

    failing = NotificationHandler(
        settings, FakeDestDb(), pub, __import__("logging").getLogger("t"),
        FakeClient([DeliveryResult(False, 500, True, "http_500")]),
    )
    event = sample_event()
    assert failing.deliver_event(event) == "retry"
    event["_attempt"] = 2
    assert failing.deliver_event(event) == "drop"
    assert pub.dlq

    replay_db = FakeDestDb()
    replay = NotificationHandler(
        settings, replay_db, FakePublisher(), __import__("logging").getLogger("t"),
        FakeClient([DeliveryResult(True, 200, False, None)]),
    )
    again = dict(event)
    again["_attempt"] = 1
    assert replay.deliver_event(again) == "ack"

    dup = proc.process_bytes(
        file_id="file-1",
        tenant_id="t",
        display_path="app.yaml",
        raw=config.read_bytes(),
        operation_hint="modified",
    )
    assert dup.reason == "duplicate_hash"

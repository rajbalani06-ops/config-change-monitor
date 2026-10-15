from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ccm.diff.engine import DiffEngine
from ccm.events.schema import ChangeEvent
from ccm.metrics import CHANGES_DETECTED, PARSE_FAILURES, PROCESSING_LATENCY
from ccm.parsers.base import ParseError
from ccm.parsers.registry import ParserRegistry
from ccm.security.redaction import Redactor
from ccm.snapshots.manager import MemorySnapshotStore, canonicalize, content_hash
from ccm.tracing import span


class EventSink(Protocol):
    def persist_change(self, **kwargs) -> None: ...
    def mark_file_error(self, file_id: str, error: str) -> None: ...


class SnapshotWriter(Protocol):
    def write_snapshot(self, file_id: str, tenant_id: str, structure_json: str, raw_hash: str) -> None: ...


@dataclass
class ProcessOutcome:
    emitted: bool
    reason: str
    event: dict[str, Any] | None = None


class ChangeProcessor:
    def __init__(
        self,
        parsers: ParserRegistry,
        diff: DiffEngine,
        redactor: Redactor,
        snapshots: MemorySnapshotStore,
        sink: EventSink | None = None,
        snapshot_writer: SnapshotWriter | None = None,
        schema_version: str = "1.0",
        emit_initial: bool = False,
        cache=None,
    ):
        self.parsers = parsers
        self.diff = diff
        self.redactor = redactor
        self.snapshots = snapshots
        self.sink = sink
        self.snapshot_writer = snapshot_writer
        self.schema_version = schema_version
        self.emit_initial = emit_initial
        self.cache = cache
        self._deleted_files: set[str] = set()

    def process_bytes(
        self,
        *,
        file_id: str,
        tenant_id: str,
        display_path: str,
        raw: bytes | None,
        operation_hint: str,
        missing: bool = False,
    ) -> ProcessOutcome:
        with PROCESSING_LATENCY.time():
            with span("process_change", file_id=file_id, operation=operation_hint):
                return self._process(
                    file_id=file_id,
                    tenant_id=tenant_id,
                    display_path=display_path,
                    raw=raw,
                    operation_hint=operation_hint,
                    missing=missing,
                )

    def _process(
        self,
        *,
        file_id: str,
        tenant_id: str,
        display_path: str,
        raw: bytes | None,
        operation_hint: str,
        missing: bool,
    ) -> ProcessOutcome:
        previous = self.snapshots.get(file_id)
        previous_hash = previous.get("raw_hash") if previous else None
        previous_data = previous.get("data") if previous else None

        if missing or operation_hint == "deleted":
            if previous_data is None:
                return ProcessOutcome(False, "delete_without_snapshot")
            changes = self.diff.diff(previous_data, {})
            event = self._event(
                display_path,
                file_id,
                tenant_id,
                "deleted",
                changes,
                None,
                previous_hash,
                "missing",
            )
            self._emit(file_id, tenant_id, event, None, None, False, deleted=True)
            self.snapshots.clear(file_id)
            self._deleted_files.add(file_id)
            if self.cache:
                self.cache.invalidate(file_id)
            CHANGES_DETECTED.labels(operation="deleted").inc()
            return ProcessOutcome(True, "deleted", event)

        assert raw is not None
        raw_hash = content_hash(raw)
        if previous and previous.get("raw_hash") == raw_hash and previous.get("valid"):
            return ProcessOutcome(False, "duplicate_hash")
        if self.cache and previous and previous.get("valid") and self.cache.get_hash(file_id) == raw_hash:
            return ProcessOutcome(False, "duplicate_hash_cache")

        try:
            parsed = self.parsers.parse_text(display_path, raw.decode("utf-8"))
        except UnicodeDecodeError:
            PARSE_FAILURES.labels(format="unknown").inc()
            self._keep_last_valid(file_id, "invalid encoding")
            return ProcessOutcome(False, "invalid")
        except ParseError as exc:
            PARSE_FAILURES.labels(format=exc.format_name).inc()
            self._keep_last_valid(file_id, "parse_error")
            return ProcessOutcome(False, "invalid")

        data = parsed.data if parsed.data is not None else {}
        is_initial = previous_data is None
        baseline = {} if is_initial else previous_data
        changes = self.diff.diff(baseline, data)
        operation = "created" if is_initial else "modified"

        is_recreation = file_id in self._deleted_files or operation_hint == "created_after_delete"
        if is_initial and not self.emit_initial and not is_recreation:
            self._save_valid(file_id, tenant_id, data, raw_hash)
            return ProcessOutcome(False, "initial_snapshot")

        if not is_initial and not self.diff.has_changes(changes):
            self._save_valid(file_id, tenant_id, data, raw_hash)
            return ProcessOutcome(False, "no_structural_change")

        event = self._event(
            display_path,
            file_id,
            tenant_id,
            operation,
            changes,
            raw_hash,
            previous_hash,
            "ok",
        )
        structure = canonicalize(data)
        # Persist the event, snapshot, and outbox row in one database transaction.
        # Updating the independent snapshot writer first could make a crash here
        # hide this change forever on the next scan.
        self._emit(file_id, tenant_id, event, structure, raw_hash, True, deleted=False)
        self._save_valid(file_id, tenant_id, data, raw_hash, persist=False)
        self._deleted_files.discard(file_id)
        CHANGES_DETECTED.labels(operation=operation).inc()
        return ProcessOutcome(True, operation, event)

    def _event(self, display_path, file_id, tenant_id, operation, changes, content_hash_val, previous_hash, parse_status):
        return ChangeEvent.build(
            file=display_path,
            file_id=file_id,
            tenant_id=tenant_id,
            operation=operation,
            changes=self.redactor.redact_flat_changes(changes),
            schema_version=self.schema_version,
            content_hash=content_hash_val,
            previous_hash=previous_hash,
            parse_status=parse_status,
        ).model_dump()

    def _save_valid(self, file_id: str, tenant_id: str, data: Any, raw_hash: str, *, persist: bool = True) -> None:
        self.snapshots.save_valid(file_id, data, raw_hash)
        if self.cache:
            self.cache.set_hash(file_id, raw_hash)
        if persist and self.snapshot_writer:
            self.snapshot_writer.write_snapshot(
                file_id, tenant_id, canonicalize(data), raw_hash
            )

    def _keep_last_valid(self, file_id: str, error: str) -> None:
        self.snapshots.mark_invalid(file_id)
        if self.sink:
            self.sink.mark_file_error(file_id, error)

    def _emit(self, file_id, tenant_id, event, snapshot_json, snapshot_hash, snapshot_valid, deleted):
        if not self.sink:
            return
        self.sink.persist_change(
            file_row={"id": file_id, "tenant_id": tenant_id},
            event=event,
            snapshot_json=snapshot_json,
            snapshot_hash=snapshot_hash,
            snapshot_valid=snapshot_valid,
            deleted=deleted,
        )

    def hydrate_from_durable(self, file_id: str, structure: Any, raw_hash: str) -> None:
        self.snapshots.save_valid(file_id, structure, raw_hash)

    def note_deleted(self, file_id: str) -> None:
        """Restore the deletion transition when startup finds no snapshot."""
        self._deleted_files.add(file_id)

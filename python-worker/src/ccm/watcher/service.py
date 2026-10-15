from __future__ import annotations

import hashlib
import logging
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ccm.diff.engine import DiffEngine
from ccm.events.processor import ChangeProcessor
from ccm.metrics import LEASE_OWNED, WATCHER_ERRORS, WATCHER_SCANS
from ccm.parsers.registry import ParserRegistry
from ccm.security.paths import PathGuard, PathPolicyError
from ccm.security.redaction import Redactor
from ccm.snapshots.manager import MemorySnapshotStore
from ccm.watcher.debounce import Debouncer
from ccm.watcher.stable import is_editor_temp, read_stable


class _Handler(FileSystemEventHandler):
    def __init__(self, debouncer: Debouncer):
        self.debouncer = debouncer

    def on_created(self, event):
        if event.is_directory:
            return
        self.debouncer.submit(event.src_path, "created")

    def on_modified(self, event):
        if event.is_directory:
            return
        self.debouncer.submit(event.src_path, "modified")

    def on_deleted(self, event):
        if event.is_directory:
            return
        self.debouncer.submit(event.src_path, "deleted")

    def on_moved(self, event):
        if event.is_directory:
            return
        self.debouncer.submit(event.src_path, "deleted")
        self.debouncer.submit(event.dest_path, "created")


class WatcherService:
    def __init__(self, settings, database, cache, logger: logging.Logger):
        self.settings = settings
        self.db = database
        self.cache = cache
        self.log = logger
        self.guard = PathGuard(settings.allowlisted_roots())
        self.processor = ChangeProcessor(
            ParserRegistry(),
            DiffEngine(),
            Redactor(settings.redaction_patterns()),
            MemorySnapshotStore(),
            sink=database,
            snapshot_writer=database,
            schema_version=settings.schema_version,
            emit_initial=settings.emit_initial_snapshot_events,
            cache=cache,
        )
        self.files_by_path: dict[str, dict] = {}
        self.debouncer = Debouncer(settings.debounce_ms, self._on_debounced)
        self.executor = ThreadPoolExecutor(max_workers=settings.watcher_concurrency)
        self.observer = Observer()
        self._stop = threading.Event()
        self.worker_id = settings.worker_id or f"{os.uname().nodename if hasattr(os, 'uname') else 'win'}-{os.getpid()}"
        self._owned_dirs: set[str] = set()

    def start(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        signal.signal(signal.SIGINT, lambda *_: self.stop())
        self._reconcile()
        self._start_observers()
        poll = threading.Thread(target=self._poll_loop, daemon=True)
        lease = threading.Thread(target=self._lease_loop, daemon=True)
        poll.start()
        lease.start()
        self.log.info("watcher started", extra={"worker_id": self.worker_id})
        while not self._stop.is_set():
            time.sleep(0.5)

    def stop(self) -> None:
        self._stop.set()
        self.debouncer.shutdown()
        self.observer.stop()
        try:
            self.observer.join(timeout=5)
        except Exception:
            pass
        self.executor.shutdown(wait=False)
        self.log.info("watcher stopped")

    def _reconcile(self) -> None:
        rows = self.db.fetch_monitored_files()
        self.files_by_path = {}
        for row in rows:
            try:
                path = self.guard.validate_access(row["path"])
            except PathPolicyError:
                WATCHER_ERRORS.labels(kind="path_policy").inc()
                self.db.mark_file_error(row["id"], "path_policy")
                continue
            self.files_by_path[str(path)] = row
            snap = self.db.get_snapshot(row["id"])
            if snap and snap.get("structure") is not None:
                self.processor.hydrate_from_durable(row["id"], snap["structure"], snap["content_hash"])
            elif row.get("last_operation") == "deleted":
                self.processor.note_deleted(row["id"])
            if path.exists():
                hint = "created_after_delete" if row.get("last_operation") == "deleted" else "modified"
                self.executor.submit(self._scan_path, str(path), hint)
            elif snap:
                self.executor.submit(self._scan_path, str(path), "deleted")
        self.log.info("startup reconciliation complete", extra={"files": len(self.files_by_path)})

    def _start_observers(self) -> None:
        watched = set()
        for path in self.files_by_path:
            directory = str(Path(path).parent)
            if directory in watched:
                continue
            if not self._owns(directory):
                continue
            watched.add(directory)
            handler = _Handler(self.debouncer)
            try:
                self.observer.schedule(handler, directory, recursive=False)
            except Exception:
                WATCHER_ERRORS.labels(kind="schedule").inc()
        self.observer.start()

    def _owns(self, directory: str) -> bool:
        owned = self.db.acquire_lease(directory, self.worker_id, self.settings.watcher_lease_seconds)
        digest = hashlib.sha256(directory.encode()).hexdigest()[:10]
        LEASE_OWNED.labels(directory_hash=digest).set(1 if owned else 0)
        if owned:
            self._owned_dirs.add(directory)
        return owned

    def _lease_loop(self) -> None:
        while not self._stop.wait(max(3, self.settings.watcher_lease_seconds // 3)):
            for directory in list(self._owned_dirs):
                if not self._owns(directory):
                    self._owned_dirs.discard(directory)

    def _poll_loop(self) -> None:
        while not self._stop.wait(self.settings.poll_fallback_seconds):
            try:
                self._poll_once()
            except Exception:
                self.log.exception("watcher polling cycle failed")

    def _poll_once(self) -> None:
            self.files_by_path = {}
            for row in self.db.fetch_monitored_files():
                try:
                    path = str(self.guard.validate_access(row["path"]))
                except PathPolicyError:
                    continue
                self.files_by_path[path] = row
                directory = str(Path(path).parent)
                if directory not in self._owned_dirs and not self._owns(directory):
                    WATCHER_SCANS.labels(result="lease_denied_poll").inc()
                    continue
                self.executor.submit(self._scan_path, path, "modified")

    def _on_debounced(self, path: str, kind: str) -> None:
        if is_editor_temp(path):
            return
        self.executor.submit(self._scan_path, path, kind)

    def _scan_path(self, path: str, kind: str) -> None:
        try:
            self._scan_path_inner(path, kind)
        except Exception:
            WATCHER_ERRORS.labels(kind="scan").inc()
            self.log.exception("watcher scan failed", extra={"path": path, "operation_hint": kind})

    def _scan_path_inner(self, path: str, kind: str) -> None:
        try:
            resolved = self.guard.validate_access(path)
        except PathPolicyError:
            return
        key = str(resolved)
        row = self.files_by_path.get(key)
        if row is None:
            return
        WATCHER_SCANS.labels(result="started").inc()
        directory = str(resolved.parent)
        if directory not in self._owned_dirs and not self._owns(directory):
            WATCHER_SCANS.labels(result="lease_denied_scan").inc()
            return
        if kind == "deleted" or not resolved.exists():
            outcome = self.processor.process_bytes(
                file_id=row["id"],
                tenant_id=row["tenant_id"],
                display_path=row["display_name"] or resolved.name,
                raw=None,
                operation_hint="deleted",
                missing=True,
            )
            WATCHER_SCANS.labels(result=outcome.reason).inc()
            return
        raw, error = read_stable(resolved, self.settings.stable_file_ms)
        if error == "permission":
            WATCHER_ERRORS.labels(kind="permission").inc()
            self.db.mark_file_error(row["id"], "permission")
            return
        if error in {"unstable", "temp", "io"}:
            WATCHER_ERRORS.labels(kind=error).inc()
            return
        if error == "missing":
            outcome = self.processor.process_bytes(
                file_id=row["id"],
                tenant_id=row["tenant_id"],
                display_path=row["display_name"] or resolved.name,
                raw=None,
                operation_hint="deleted",
                missing=True,
            )
            WATCHER_SCANS.labels(result=outcome.reason).inc()
            return
        outcome = self.processor.process_bytes(
            file_id=row["id"],
            tenant_id=row["tenant_id"],
            display_path=row["display_name"] or resolved.name,
            raw=raw,
            operation_hint=kind,
            missing=False,
        )
        WATCHER_SCANS.labels(result=outcome.reason).inc()

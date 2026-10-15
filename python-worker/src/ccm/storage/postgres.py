from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row


class Database:
    def __init__(self, dsn: str):
        self.dsn = dsn

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        conn = psycopg.connect(self.dsn, row_factory=dict_row, autocommit=False)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def fetch_monitored_files(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM monitored_files WHERE enabled = TRUE"
        params: list[Any] = []
        if tenant_id:
            sql += " AND tenant_id = %s"
            params.append(tenant_id)
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return list(rows)

    def get_snapshot(self, file_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM file_snapshots WHERE file_id = %s", (file_id,)
            ).fetchone()
        return row

    def persist_change(
        self,
        *,
        file_row: dict[str, Any],
        event: dict[str, Any],
        snapshot_json: str | None,
        snapshot_hash: str | None,
        snapshot_valid: bool,
        deleted: bool = False,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO change_events (
                    id, tenant_id, file_id, correlation_id, schema_version, operation,
                    parse_status, content_hash, previous_hash, payload, created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb, NOW())
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    event["event_id"],
                    event["tenant_id"],
                    event["file_id"],
                    event["correlation_id"],
                    event["schema_version"],
                    event["operation"],
                    event["parse_status"],
                    event.get("content_hash"),
                    event.get("previous_hash"),
                    json.dumps(event),
                ),
            )
            if snapshot_valid and snapshot_json is not None:
                conn.execute(
                    """
                    INSERT INTO file_snapshots (file_id, tenant_id, content_hash, structure, valid, updated_at)
                    VALUES (%s,%s,%s,%s::jsonb, TRUE, NOW())
                    ON CONFLICT (file_id) DO UPDATE SET
                        content_hash = EXCLUDED.content_hash,
                        structure = EXCLUDED.structure,
                        valid = TRUE,
                        updated_at = NOW()
                    """,
                    (file_row["id"], file_row["tenant_id"], snapshot_hash, snapshot_json),
                )
            elif not snapshot_valid and not deleted:
                conn.execute(
                    "UPDATE file_snapshots SET valid = FALSE, updated_at = NOW() WHERE file_id = %s",
                    (file_row["id"],),
                )
            if deleted:
                conn.execute("DELETE FROM file_snapshots WHERE file_id = %s", (file_row["id"],))
            conn.execute(
                """
                UPDATE monitored_files
                SET last_scan_at = NOW(), last_error = NULL, last_operation = %s
                WHERE id = %s
                """,
                (event["operation"], file_row["id"]),
            )
            conn.execute(
                """
                INSERT INTO outbox (id, event_id, tenant_id, payload, status, attempts, available_at, created_at)
                VALUES (%s,%s,%s,%s::jsonb, 'pending', 0, NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
                """,
                (event["event_id"], event["event_id"], event["tenant_id"], json.dumps(event)),
            )
            conn.execute(
                """
                INSERT INTO audit_log (tenant_id, actor, action, target, metadata, created_at)
                VALUES (%s, 'watcher', 'change_event', %s, %s::jsonb, NOW())
                """,
                (
                    event["tenant_id"],
                    event["file_id"],
                    json.dumps({"event_id": event["event_id"], "operation": event["operation"]}),
                ),
            )

    def mark_file_error(self, file_id: str, error: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE monitored_files SET last_error = %s, last_scan_at = NOW() WHERE id = %s",
                (error, file_id),
            )

    def claim_outbox(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM outbox
                WHERE (status = 'pending' AND available_at <= NOW())
                   OR (status = 'publishing' AND locked_at < NOW() - INTERVAL '2 minutes')
                ORDER BY created_at
                LIMIT %s
                FOR UPDATE SKIP LOCKED
                """,
                (limit,),
            ).fetchall()
            ids = [r["id"] for r in rows]
            if ids:
                conn.execute(
                    "UPDATE outbox SET status = 'publishing', attempts = attempts + 1, locked_at = NOW() WHERE id = ANY(%s)",
                    (ids,),
                )
                for row in rows:
                    row["attempts"] = int(row["attempts"]) + 1
        return list(rows)

    def mark_outbox_published(self, outbox_id: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE outbox SET status = 'published', published_at = NOW(), locked_at = NULL WHERE id = %s",
                (outbox_id,),
            )

    def mark_outbox_failed(self, outbox_id: str, delay_seconds: int, error: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE outbox
                SET status = 'pending', last_error = %s,
                    available_at = NOW() + (%s || ' seconds')::interval,
                    locked_at = NULL
                WHERE id = %s
                """,
                (error[:500], str(delay_seconds), outbox_id),
            )

    def insert_delivery_attempt(
        self,
        *,
        event_id: str,
        tenant_id: str,
        destination_id: str,
        status: str,
        http_status: int | None,
        error: str | None,
        attempt: int,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO delivery_attempts (
                    event_id, tenant_id, destination_id, status, http_status, error, attempt, created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s, NOW())
                """,
                (event_id, tenant_id, destination_id, status, http_status, error, attempt),
            )

    def mark_event_delivery(self, event_id: str, status: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE change_events SET delivery_status = %s, updated_at = NOW() WHERE id = %s",
                (status, event_id),
            )

    def insert_dead_letter(self, event_id: str, tenant_id: str, payload: dict, reason: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO dead_letter_events (event_id, tenant_id, payload, reason, created_at)
                VALUES (%s,%s,%s::jsonb,%s, NOW())
                ON CONFLICT (event_id) DO UPDATE SET reason = EXCLUDED.reason, created_at = NOW()
                """,
                (event_id, tenant_id, json.dumps(payload), reason),
            )
            conn.execute(
                "UPDATE change_events SET delivery_status = 'dead_lettered', updated_at = NOW() WHERE id = %s",
                (event_id,),
            )

    def write_snapshot(self, file_id: str, tenant_id: str, structure_json: str, raw_hash: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO file_snapshots (file_id, tenant_id, content_hash, structure, valid, updated_at)
                VALUES (%s,%s,%s,%s::jsonb, TRUE, NOW())
                ON CONFLICT (file_id) DO UPDATE SET
                    content_hash = EXCLUDED.content_hash,
                    structure = EXCLUDED.structure,
                    valid = TRUE,
                    updated_at = NOW()
                """,
                (file_id, tenant_id, raw_hash, structure_json),
            )
            conn.execute(
                "UPDATE monitored_files SET last_scan_at = NOW() WHERE id = %s",
                (file_id,),
            )

    def health(self) -> bool:
        try:
            with self.connection() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def acquire_lease(self, directory: str, worker_id: str, ttl_seconds: int) -> bool:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO watcher_leases (directory, worker_id, expires_at, updated_at)
                VALUES (%s, %s, NOW() + (%s || ' seconds')::interval, NOW())
                ON CONFLICT (directory) DO UPDATE
                SET worker_id = EXCLUDED.worker_id,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = NOW()
                WHERE watcher_leases.expires_at < NOW()
                   OR watcher_leases.worker_id = EXCLUDED.worker_id
                """,
                (directory, worker_id, str(ttl_seconds)),
            )
            row = conn.execute(
                "SELECT worker_id FROM watcher_leases WHERE directory = %s",
                (directory,),
            ).fetchone()
        return bool(row and row["worker_id"] == worker_id)

    def list_destinations(self, tenant_id: str) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM notification_destinations WHERE enabled = TRUE AND tenant_id = %s",
                (tenant_id,),
            ).fetchall()
        return list(rows)

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM change_events WHERE id = %s", (event_id,)).fetchone()

from __future__ import annotations

import os


def ensure_default_destination(db, tenant_id: str, url: str | None) -> None:
    if not url:
        return
    with db.connection() as conn:
        existing = conn.execute(
            "SELECT id FROM notification_destinations WHERE tenant_id = %s AND url = %s",
            (tenant_id, url),
        ).fetchone()
        if existing:
            return
        conn.execute(
            """
            INSERT INTO notification_destinations (tenant_id, url, enabled)
            VALUES (%s, %s, TRUE)
            """,
            (tenant_id, url),
        )

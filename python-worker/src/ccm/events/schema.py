from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


Operation = Literal["created", "modified", "deleted"]


class ChangeSet(BaseModel):
    added: dict[str, Any] = Field(default_factory=dict)
    updated: dict[str, Any] = Field(default_factory=dict)
    removed: dict[str, Any] = Field(default_factory=dict)
    type_changes: dict[str, Any] = Field(default_factory=dict)


class ChangeEvent(BaseModel):
    event_id: str
    schema_version: str = "1.0"
    file: str
    file_id: str
    tenant_id: str
    timestamp: str
    operation: Operation
    content_hash: str | None = None
    previous_hash: str | None = None
    correlation_id: str
    parse_status: Literal["ok", "invalid", "missing"] = "ok"
    changes: ChangeSet = Field(default_factory=ChangeSet)
    redacted: bool = True

    @classmethod
    def build(
        cls,
        *,
        file: str,
        file_id: str,
        tenant_id: str,
        operation: Operation,
        changes: dict,
        schema_version: str = "1.0",
        content_hash: str | None = None,
        previous_hash: str | None = None,
        correlation_id: str | None = None,
        parse_status: Literal["ok", "invalid", "missing"] = "ok",
        event_id: str | None = None,
    ) -> "ChangeEvent":
        cid = correlation_id or str(uuid4())
        return cls(
            event_id=event_id or str(uuid4()),
            schema_version=schema_version,
            file=file,
            # psycopg returns UUID columns as uuid.UUID instances, while the
            # event contract and webhook payload use string identifiers.
            file_id=str(file_id),
            tenant_id=tenant_id,
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            operation=operation,
            content_hash=content_hash,
            previous_hash=previous_hash,
            correlation_id=cid,
            parse_status=parse_status,
            changes=ChangeSet.model_validate(changes),
            redacted=True,
        )

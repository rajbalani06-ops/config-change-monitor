from datetime import datetime
from uuid import UUID

from ccm.events.schema import ChangeEvent


REQUIRED = [
    "event_id",
    "schema_version",
    "file",
    "file_id",
    "tenant_id",
    "timestamp",
    "operation",
    "correlation_id",
    "changes",
]


def test_versioned_payload_contract():
    event = ChangeEvent.build(
        file="config.yaml",
        file_id="11111111-1111-1111-1111-111111111111",
        tenant_id="default",
        operation="modified",
        changes={
            "added": {"logging.level": "debug"},
            "updated": {"db.host": {"old": "localhost", "new": "prod-db"}},
            "removed": {"cache.enabled": True},
            "type_changes": {"featureFlags": {"oldType": "string", "newType": "object"}},
        },
    )
    data = event.model_dump()
    for key in REQUIRED:
        assert key in data
    datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
    assert data["schema_version"] == "1.0"
    assert set(data["changes"].keys()) == {"added", "updated", "removed", "type_changes"}
    assert data["operation"] in {"created", "modified", "deleted"}


def test_uuid_file_id_is_serialized_as_string():
    event = ChangeEvent.build(
        file="config.json",
        file_id=UUID("11111111-1111-1111-1111-111111111111"),
        tenant_id="default",
        operation="modified",
        changes={},
    )
    assert event.file_id == "11111111-1111-1111-1111-111111111111"

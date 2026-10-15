import httpx
import pytest

from ccm.notify.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState
from ccm.notify.retry import compute_backoff_ms, is_retryable_status, retry_after_ms
from ccm.notify.webhook import WebhookClient
from ccm.events.schema import ChangeEvent


def test_circuit_breaker_states():
    cb = CircuitBreaker(2, 0.01)
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        cb.guard()
    cb.opened_at = 0
    assert cb.allow()
    assert cb.state == CircuitState.HALF_OPEN
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_backoff_and_retry_after():
    ms = compute_backoff_ms(3, 100, 10000)
    assert 100 <= ms <= 10000
    assert is_retryable_status(429)
    assert is_retryable_status(503)
    assert not is_retryable_status(400)
    assert retry_after_ms({"Retry-After": "2"}) == 2000


def test_webhook_success_and_retryable():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ok":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(503, headers={"Retry-After": "1"})

    transport = httpx.MockTransport(handler)
    client = WebhookClient(timeout=1, allow_private=True, transport=transport)
    ok = client.deliver("http://127.0.0.1/ok", {"event_id": "1"}, idempotency_key="1")
    assert ok.success
    bad = client.deliver("http://127.0.0.1/fail", {"event_id": "1"})
    assert not bad.success
    assert bad.retryable
    assert bad.retry_after_ms == 1000


def test_event_schema_required_fields():
    event = ChangeEvent.build(
        file="c.yaml",
        file_id="fid",
        tenant_id="t",
        operation="modified",
        changes={"added": {"a": 1}, "updated": {}, "removed": {}, "type_changes": {}},
    )
    dumped = event.model_dump()
    assert dumped["event_id"]
    assert dumped["schema_version"] == "1.0"
    assert dumped["timestamp"].endswith("Z") or "T" in dumped["timestamp"]
    assert dumped["changes"]["added"]["a"] == 1
    with pytest.raises(Exception):
        ChangeEvent.model_validate({"file": "x"})

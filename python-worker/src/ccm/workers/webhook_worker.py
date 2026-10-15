from __future__ import annotations

import logging
import time
from collections import defaultdict

from pydantic import ValidationError

from ccm.events.schema import ChangeEvent
from ccm.metrics import CIRCUIT_STATE, DEAD_LETTER_COUNT, RETRY_COUNT, WEBHOOK_FAILURE, WEBHOOK_LATENCY, WEBHOOK_SUCCESS
from ccm.notify.circuit_breaker import CircuitBreaker, CircuitOpenError
from ccm.notify.retry import compute_backoff_ms
from ccm.notify.webhook import WebhookClient
from ccm.tracing import span


class NotificationHandler:
    def __init__(self, settings, db, publisher, logger: logging.Logger, webhook_client: WebhookClient | None = None):
        self.settings = settings
        self.db = db
        self.publisher = publisher
        self.log = logger
        self.client = webhook_client or WebhookClient(
            timeout=settings.webhook_timeout_seconds,
            allow_private=settings.webhook_allow_private_networks,
        )
        self.breakers: dict[str, CircuitBreaker] = defaultdict(
            lambda: CircuitBreaker(settings.circuit_failure_threshold, settings.circuit_open_seconds)
        )

    def __call__(self, payload: dict) -> str:
        try:
            event = ChangeEvent.model_validate(payload)
        except ValidationError:
            self.log.error("invalid event payload")
            WEBHOOK_FAILURE.labels(kind="validation").inc()
            return "drop"
        normalized = event.model_dump()
        normalized["_attempt"] = int(payload.get("_attempt") or 1)
        result = self.deliver_event(normalized)
        if result == "retry" and callable(getattr(self.publisher, "publish", None)):
            # Publish the incremented attempt before acknowledging the current
            # delivery. A RabbitMQ nack/requeue would redeliver the old payload
            # and reset the retry counter indefinitely.
            attempt = normalized["_attempt"]
            delay = compute_backoff_ms(
                attempt - 1,
                self.settings.webhook_base_backoff_ms,
                self.settings.webhook_max_backoff_ms,
            )
            retry_after = int(normalized.pop("_retry_after_ms", 0) or 0)
            delay = min(self.settings.webhook_max_backoff_ms, max(delay, retry_after))
            time.sleep(delay / 1000)
            try:
                self.publisher.publish(normalized)
                return "ack"
            except Exception:
                self.log.exception("webhook retry publish failed", extra={"event_id": normalized.get("event_id")})
                return "retry"
        return result

    def deliver_event(self, event: dict) -> str:
        dests = self.db.list_destinations(event["tenant_id"])
        if not dests:
            self.db.mark_event_delivery(event["event_id"], "no_destination")
            return "ack"
        attempt = int(event.get("_attempt") or 1)
        all_ok = True
        retry = False
        for dest in dests:
            breaker = self.breakers[dest["id"]]
            CIRCUIT_STATE.labels(destination="grouped").set(int(breaker.state))
            try:
                breaker.guard()
            except CircuitOpenError:
                WEBHOOK_FAILURE.labels(kind="circuit_open").inc()
                retry = True
                all_ok = False
                self.db.insert_delivery_attempt(
                    event_id=event["event_id"],
                    tenant_id=event["tenant_id"],
                    destination_id=dest["id"],
                    status="circuit_open",
                    http_status=None,
                    error="circuit_open",
                    attempt=attempt,
                )
                continue
            headers = {}
            if dest.get("auth_header_name") and dest.get("auth_header_value"):
                headers[dest["auth_header_name"]] = dest["auth_header_value"]
            with span("webhook.deliver", destination_id=dest["id"], event_id=event["event_id"]):
                with WEBHOOK_LATENCY.time():
                    result = self.client.deliver(
                        dest["url"],
                        event,
                        headers=headers,
                        idempotency_key=event["event_id"],
                    )
            if result.success:
                breaker.record_success()
                WEBHOOK_SUCCESS.inc()
                self.db.insert_delivery_attempt(
                    event_id=event["event_id"],
                    tenant_id=event["tenant_id"],
                    destination_id=dest["id"],
                    status="success",
                    http_status=result.status_code,
                    error=None,
                    attempt=attempt,
                )
            else:
                breaker.record_failure()
                WEBHOOK_FAILURE.labels(kind="http" if result.status_code else "network").inc()
                all_ok = False
                self.db.insert_delivery_attempt(
                    event_id=event["event_id"],
                    tenant_id=event["tenant_id"],
                    destination_id=dest["id"],
                    status="failed" if not result.retryable else "retryable",
                    http_status=result.status_code,
                    error=result.error,
                    attempt=attempt,
                )
                if result.retryable:
                    retry = True
                    if result.retry_after_ms is not None:
                        event["_retry_after_ms"] = result.retry_after_ms
        if all_ok:
            self.db.mark_event_delivery(event["event_id"], "delivered")
            return "ack"
        if retry and attempt < self.settings.webhook_max_retries:
            RETRY_COUNT.inc()
            event["_attempt"] = attempt + 1
            backoff = compute_backoff_ms(attempt, self.settings.webhook_base_backoff_ms, self.settings.webhook_max_backoff_ms)
            self.log.warning(
                "webhook retry scheduled",
                extra={"event_id": event["event_id"], "attempt": attempt, "backoff_ms": backoff},
            )
            return "retry"
        self.db.insert_dead_letter(event["event_id"], event["tenant_id"], event, "retries_exhausted")
        try:
            self.publisher.publish_dlq(event)
        except Exception:
            self.log.exception("dlq publish failed")
        DEAD_LETTER_COUNT.inc()
        return "drop"

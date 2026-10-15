from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from ccm.notify.retry import is_retryable_status, retry_after_ms
from ccm.security.ssrf import UnsafeWebhookError, WebhookUrlValidator


@dataclass
class DeliveryResult:
    success: bool
    status_code: int | None
    retryable: bool
    error: str | None
    retry_after_ms: int | None = None
    latency_s: float = 0.0


class WebhookClient:
    def __init__(self, timeout: float, allow_private: bool = False, transport=None):
        self.timeout = timeout
        self.validator = WebhookUrlValidator(allow_private=allow_private)
        self._transport = transport

    def deliver(
        self,
        url: str,
        payload: dict,
        headers: dict[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> DeliveryResult:
        try:
            self.validator.validate(url)
            self.validator.revalidate_after_dns(url)
        except UnsafeWebhookError as exc:
            return DeliveryResult(False, None, False, str(exc))
        request_headers = dict(headers or {})
        request_headers.setdefault("Content-Type", "application/json")
        if idempotency_key:
            request_headers["Idempotency-Key"] = idempotency_key
            request_headers["X-Event-Id"] = idempotency_key
        client_kwargs = {"timeout": self.timeout, "follow_redirects": False}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.post(url, content=json.dumps(payload).encode("utf-8"), headers=request_headers)
        except httpx.TimeoutException:
            return DeliveryResult(False, None, True, "timeout")
        except httpx.TransportError as exc:
            return DeliveryResult(False, None, True, f"network: {exc.__class__.__name__}")
        retryable = is_retryable_status(response.status_code)
        success = 200 <= response.status_code < 300
        return DeliveryResult(
            success=success,
            status_code=response.status_code,
            retryable=retryable and not success,
            error=None if success else f"http_{response.status_code}",
            retry_after_ms=retry_after_ms(dict(response.headers)),
        )

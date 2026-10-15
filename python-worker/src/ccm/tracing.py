from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Span, Status, StatusCode

_initialized = False


def init_tracing(enabled: bool, service_name: str, endpoint: str) -> None:
    global _initialized
    if not enabled or _initialized:
        return
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
    except Exception:
        exporter = ConsoleSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _initialized = True


def tracer():
    return trace.get_tracer("ccm")


@contextmanager
def span(name: str, **attrs) -> Iterator[Span]:
    with tracer().start_as_current_span(name) as current:
        for k, v in attrs.items():
            if v is None:
                continue
            if k.lower() in {"content", "authorization", "secret", "token", "password"}:
                continue
            current.set_attribute(k, str(v)[:200])
        try:
            yield current
        except Exception as exc:
            current.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def inject_trace_headers(headers: dict[str, str]) -> dict[str, str]:
    span_ctx = trace.get_current_span().get_span_context()
    if span_ctx.is_valid:
        headers["traceparent"] = (
            f"00-{format(span_ctx.trace_id, '032x')}-{format(span_ctx.span_id, '016x')}-01"
        )
    return headers

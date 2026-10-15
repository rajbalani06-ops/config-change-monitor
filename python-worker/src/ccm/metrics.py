from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, start_http_server


CHANGES_DETECTED = Counter("ccm_changes_detected_total", "Configuration changes detected", ["operation"])
EVENTS_PUBLISHED = Counter("ccm_events_published_total", "Events published to RabbitMQ")
EVENTS_PROCESSED = Counter("ccm_events_processed_total", "Events consumed for delivery")
WEBHOOK_SUCCESS = Counter("ccm_webhook_success_total", "Successful webhook deliveries")
WEBHOOK_FAILURE = Counter("ccm_webhook_failure_total", "Failed webhook deliveries", ["kind"])
RETRY_COUNT = Counter("ccm_webhook_retries_total", "Webhook retry attempts")
DEAD_LETTER_COUNT = Counter("ccm_dead_letter_total", "Events routed to dead-letter")
QUEUE_DEPTH = Gauge("ccm_queue_depth", "Approximate queue depth", ["queue"])
PROCESSING_LATENCY = Histogram("ccm_processing_latency_seconds", "Change processing latency")
WEBHOOK_LATENCY = Histogram("ccm_webhook_latency_seconds", "Webhook HTTP latency")
PARSE_FAILURES = Counter("ccm_parse_failures_total", "Parser failures", ["format"])
WATCHER_ERRORS = Counter("ccm_watcher_errors_total", "File watcher errors", ["kind"])
WATCHER_SCANS = Counter("ccm_watcher_scans_total", "Watcher scan results", ["result"])
CIRCUIT_STATE = Gauge("ccm_circuit_breaker_state", "Circuit breaker state (0 closed, 1 open, 2 half-open)", ["destination"])
LEASE_OWNED = Gauge("ccm_lease_owned", "Whether this replica owns a watch lease", ["directory_hash"])
RABBITMQ_CONNECTED = Gauge("ccm_rabbitmq_connected", "Whether an authenticated AMQP connection is established")
RABBITMQ_CONSUMER_READY = Gauge("ccm_rabbitmq_consumer_ready", "Whether the notification consumer is attached to its queue")
WORKER_COMPONENT_UP = Gauge("ccm_worker_component_up", "Whether a worker loop is alive", ["component"])


def start_metrics_server(port: int) -> None:
    start_http_server(port)

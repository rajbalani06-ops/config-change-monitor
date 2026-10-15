from __future__ import annotations

import os
import sys
import threading

from ccm.config import get_settings
from ccm.logging import configure_logging
from ccm.metrics import RABBITMQ_CONNECTED, RABBITMQ_CONSUMER_READY, WORKER_COMPONENT_UP, start_metrics_server
from ccm.queue.rabbit import EventPublisher, EventConsumer, RabbitConnection
from ccm.storage.postgres import Database
from ccm.storage.redis_cache import SnapshotCache
from ccm.tracing import init_tracing
from ccm.watcher.service import WatcherService
from ccm.workers.outbox import OutboxPublisherWorker
from ccm.workers.webhook_worker import NotificationHandler


def _run_component(name: str, target, logger) -> None:
    metric = WORKER_COMPONENT_UP.labels(component=name)
    metric.set(1)
    try:
        target()
    except Exception:
        logger.exception("worker component stopped", extra={"component": name})
    finally:
        metric.set(0)


def _redis_client(settings):
    if not settings.redis_enabled:
        return None
    try:
        import redis

        kwargs = {"host": settings.redis_host, "port": settings.redis_port, "socket_timeout": 1}
        if settings.redis_password:
            kwargs["password"] = settings.redis_password
        client = redis.Redis(**kwargs)
        client.ping()
        return client
    except Exception:
        return None


def main() -> None:
    role = os.environ.get("CCM_ROLE", "all")
    settings = get_settings()
    log = configure_logging(settings.log_level, settings.service_name)
    init_tracing(settings.otel_enabled, settings.otel_service_name, settings.otel_exporter_otlp_endpoint)
    start_metrics_server(settings.metrics_port)
    RABBITMQ_CONNECTED.set(0)
    RABBITMQ_CONSUMER_READY.set(0)
    db = Database(settings.database_url)
    from ccm.bootstrap import ensure_default_destination

    ensure_default_destination(
        db,
        settings.default_tenant_id,
        os.environ.get("DEFAULT_WEBHOOK_URL"),
    )
    cache = SnapshotCache(_redis_client(settings), settings.redis_ttl_seconds)
    rabbit = RabbitConnection(
        settings.rabbitmq_host,
        settings.rabbitmq_port,
        settings.rabbitmq_user,
        settings.rabbitmq_password,
        settings.rabbitmq_vhost,
    )
    publisher = EventPublisher(rabbit, settings.rabbitmq_exchange, settings.rabbitmq_queue, settings.rabbitmq_dlq)

    threads: list[threading.Thread] = []
    for component in ("outbox", "consumer", "watcher"):
        WORKER_COMPONENT_UP.labels(component=component).set(0)
    if role in {"all", "outbox"}:
        outbox = OutboxPublisherWorker(db, publisher, log)
        t = threading.Thread(target=_run_component, args=("outbox", outbox.run, log), daemon=True, name="outbox")
        threads.append(t)
        t.start()
    if role in {"all", "notify"}:
        handler = NotificationHandler(settings, db, publisher, log)
        consumer = EventConsumer(
            rabbit,
            settings.rabbitmq_exchange,
            settings.rabbitmq_queue,
            settings.rabbitmq_dlq,
            handler,
            settings.consumer_prefetch,
            logger=log,
        )
        t = threading.Thread(target=_run_component, args=("consumer", consumer.run, log), daemon=True, name="consumer")
        threads.append(t)
        t.start()
    if role in {"all", "watch"}:
        watcher = WatcherService(settings, db, cache, log)
        WORKER_COMPONENT_UP.labels(component="watcher").set(1)
        try:
            watcher.start()
        finally:
            WORKER_COMPONENT_UP.labels(component="watcher").set(0)
            watcher.stop()
    else:
        for t in threads:
            t.join()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)

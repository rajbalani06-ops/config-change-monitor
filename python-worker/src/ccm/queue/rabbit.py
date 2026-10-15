from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

import pika

from ccm.metrics import EVENTS_PROCESSED, EVENTS_PUBLISHED, QUEUE_DEPTH, RABBITMQ_CONNECTED, RABBITMQ_CONSUMER_READY
from ccm.tracing import inject_trace_headers, span


class RabbitConnection:
    def __init__(self, host: str, port: int, user: str, password: str, vhost: str):
        self.params = pika.ConnectionParameters(
            host=host,
            port=port,
            virtual_host=vhost,
            credentials=pika.PlainCredentials(user, password),
            heartbeat=0,
            blocked_connection_timeout=300,
        )

    def connect(self) -> pika.BlockingConnection:
        try:
            connection = pika.BlockingConnection(self.params)
        except Exception:
            RABBITMQ_CONNECTED.set(0)
            raise
        RABBITMQ_CONNECTED.set(1)
        return connection


def declare_topology(channel, exchange: str, queue: str, dlq: str) -> None:
    channel.exchange_declare(exchange, exchange_type="topic", durable=True)
    channel.exchange_declare(f"{exchange}.dlx", exchange_type="fanout", durable=True)
    channel.queue_declare(dlq, durable=True)
    channel.queue_bind(dlq, f"{exchange}.dlx")
    channel.queue_declare(
        queue,
        durable=True,
        arguments={
            "x-dead-letter-exchange": f"{exchange}.dlx",
        },
    )
    channel.queue_bind(queue, exchange, routing_key="config.changed")
    channel.queue_bind(queue, exchange, routing_key="config.replay")


class EventPublisher:
    def __init__(self, conn_factory: RabbitConnection, exchange: str, queue: str, dlq: str):
        self.conn_factory = conn_factory
        self.exchange = exchange
        self.queue = queue
        self.dlq = dlq
        self._lock = threading.Lock()
        self._conn = None
        self._channel = None

    def _ensure(self):
        if self._conn and self._conn.is_open and self._channel and self._channel.is_open:
            return
        self._conn = self.conn_factory.connect()
        self._channel = self._conn.channel()
        self._channel.confirm_delivery()
        declare_topology(self._channel, self.exchange, self.queue, self.dlq)

    def publish(self, payload: dict, routing_key: str = "config.changed") -> None:
        body = json.dumps(payload).encode("utf-8")
        headers = inject_trace_headers({})
        properties = pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,
            message_id=payload.get("event_id"),
            correlation_id=payload.get("correlation_id"),
            headers=headers,
        )
        with self._lock:
            self._ensure()
            with span("rabbitmq.publish", event_id=payload.get("event_id")):
                self._channel.basic_publish(
                    exchange=self.exchange,
                    routing_key=routing_key,
                    body=body,
                    properties=properties,
                    mandatory=True,
                )
            EVENTS_PUBLISHED.inc()

    def publish_dlq(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        with self._lock:
            self._ensure()
            self._channel.basic_publish(
                exchange=f"{self.exchange}.dlx",
                routing_key="",
                body=body,
                properties=pika.BasicProperties(delivery_mode=2, message_id=payload.get("event_id")),
            )

    def close(self) -> None:
        with self._lock:
            if self._conn and self._conn.is_open:
                self._conn.close()


class EventConsumer:
    def __init__(
        self,
        conn_factory: RabbitConnection,
        exchange: str,
        queue: str,
        dlq: str,
        handler: Callable[[dict], str],
        prefetch: int = 16,
        logger: logging.Logger | None = None,
    ):
        self.conn_factory = conn_factory
        self.exchange = exchange
        self.queue = queue
        self.dlq = dlq
        self.handler = handler
        self.prefetch = prefetch
        self.log = logger or logging.getLogger(__name__)
        self._stopping = threading.Event()

    def run(self) -> None:
        while not self._stopping.is_set():
            try:
                self._consume_once()
            except Exception:
                RABBITMQ_CONNECTED.set(0)
                RABBITMQ_CONSUMER_READY.set(0)
                self.log.exception("RabbitMQ consumer disconnected; retrying")
                self._stopping.wait(1)

    def _consume_once(self) -> None:
        conn = self.conn_factory.connect()
        channel = None
        try:
            channel = conn.channel()
            declare_topology(channel, self.exchange, self.queue, self.dlq)
            channel.basic_qos(prefetch_count=self.prefetch)

            def on_message(ch, method, properties, body):
                if self._stopping.is_set():
                    ch.basic_nack(method.delivery_tag, requeue=True)
                    return
                try:
                    payload = json.loads(body.decode("utf-8"))
                except json.JSONDecodeError:
                    ch.basic_nack(method.delivery_tag, requeue=False)
                    return
                with span("rabbitmq.consume", event_id=payload.get("event_id")):
                    result = self.handler(payload)
                EVENTS_PROCESSED.inc()
                if result == "ack":
                    ch.basic_ack(method.delivery_tag)
                elif result == "retry":
                    ch.basic_nack(method.delivery_tag, requeue=True)
                else:
                    ch.basic_nack(method.delivery_tag, requeue=False)

            channel.basic_consume(self.queue, on_message)
            RABBITMQ_CONSUMER_READY.set(1)
            while not self._stopping.is_set():
                conn.process_data_events(time_limit=1)
                try:
                    q = channel.queue_declare(self.queue, durable=True, passive=True)
                    QUEUE_DEPTH.labels(queue=self.queue).set(q.method.message_count)
                except Exception:
                    self.log.exception("RabbitMQ queue depth check failed")
                    raise
        finally:
            RABBITMQ_CONSUMER_READY.set(0)
            if channel is not None and channel.is_open:
                channel.close()
            if conn.is_open:
                conn.close()

    def stop(self) -> None:
        self._stopping.set()

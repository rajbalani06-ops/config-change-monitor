from __future__ import annotations

import logging
from types import SimpleNamespace

from ccm.queue.rabbit import EventConsumer


class FakeChannel:
    is_open = True

    def exchange_declare(self, *args, **kwargs):
        pass

    def queue_declare(self, *args, **kwargs):
        return SimpleNamespace(method=SimpleNamespace(message_count=0))

    def queue_bind(self, *args, **kwargs):
        pass

    def basic_qos(self, *args, **kwargs):
        pass

    def basic_consume(self, *args, **kwargs):
        pass

    def close(self):
        self.is_open = False


class FakeConnection:
    is_open = True

    def __init__(self, consumer):
        self.consumer = consumer

    def channel(self):
        return FakeChannel()

    def process_data_events(self, **kwargs):
        self.consumer.stop()

    def close(self):
        self.is_open = False


class FlakyFactory:
    def __init__(self):
        self.calls = 0
        self.consumer = None

    def connect(self):
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("temporary broker handshake timeout")
        return FakeConnection(self.consumer)


def test_consumer_reconnects_after_broker_handshake_failure():
    factory = FlakyFactory()
    consumer = EventConsumer(factory, "events", "notifications", "dead", lambda _: "ack", logger=logging.getLogger("test"))
    factory.consumer = consumer

    consumer.run()

    assert factory.calls == 2

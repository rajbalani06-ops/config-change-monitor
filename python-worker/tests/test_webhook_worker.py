from ccm.config import Settings
from ccm.events.schema import ChangeEvent
from ccm.notify.webhook import DeliveryResult
from ccm.workers.webhook_worker import NotificationHandler


class FakeDestDb:
    def __init__(self, dests=None):
        self.dests = dests or [{"id": "d1", "url": "http://127.0.0.1/h", "auth_header_name": None, "auth_header_value": None}]
        self.attempts = []
        self.delivery = []
        self.dlq = []

    def list_destinations(self, tenant_id):
        return self.dests

    def insert_delivery_attempt(self, **kw):
        self.attempts.append(kw)

    def mark_event_delivery(self, event_id, status):
        self.delivery.append((event_id, status))

    def insert_dead_letter(self, event_id, tenant_id, payload, reason):
        self.dlq.append((event_id, reason))


class FakePublisher:
    def __init__(self):
        self.dlq = []

    def publish_dlq(self, payload):
        self.dlq.append(payload)


class FakeClient:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def deliver(self, *a, **k):
        self.calls += 1
        return self.results.pop(0) if self.results else DeliveryResult(False, 500, True, "http_500")


def sample_event():
    return ChangeEvent.build(
        file="c.json", file_id="f", tenant_id="t", operation="modified",
        changes={"added": {"a": 1}, "updated": {}, "removed": {}, "type_changes": {}},
    ).model_dump()


def test_success_and_dead_letter():
    settings = Settings(webhook_max_retries=2, webhook_allow_private_networks=True)
    db = FakeDestDb()
    pub = FakePublisher()
    handler = NotificationHandler(settings, db, pub, __import__("logging").getLogger("t"), FakeClient([DeliveryResult(True, 200, False, None)]))
    assert handler.deliver_event(sample_event()) == "ack"
    assert db.delivery[-1][1] == "delivered"

    handler2 = NotificationHandler(
        settings, FakeDestDb(), pub, __import__("logging").getLogger("t"),
        FakeClient([DeliveryResult(False, 500, True, "http_500")]),
    )
    event = sample_event()
    event["_attempt"] = 2
    assert handler2.deliver_event(event) == "drop"
    assert pub.dlq


def test_invalid_payload_dropped():
    settings = Settings()
    handler = NotificationHandler(settings, FakeDestDb(), FakePublisher(), __import__("logging").getLogger("t"), FakeClient([]))
    assert handler({"nope": True}) == "drop"

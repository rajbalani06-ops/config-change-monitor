from __future__ import annotations

import logging
import math
import time

from ccm.queue.rabbit import EventPublisher
from ccm.notify.retry import compute_backoff_ms


class OutboxPublisherWorker:
    """Publishes persisted outbox rows after commit (transactional outbox).

    Events are inserted into PostgreSQL in the same transaction as snapshots.
    This worker then publishes to RabbitMQ with publisher confirms and marks
    the row published. Queue publication is therefore at-least-once.
    """

    def __init__(self, db, publisher: EventPublisher, logger: logging.Logger, interval: float = 0.5):
        self.db = db
        self.publisher = publisher
        self.log = logger
        self.interval = interval
        self._stop = False

    def run(self) -> None:
        self.log.info("outbox publisher started")
        while not self._stop:
            try:
                rows = self.db.claim_outbox(20)
                for row in rows:
                    try:
                        self.publisher.publish(row["payload"])
                        self.db.mark_outbox_published(row["id"])
                    except Exception as exc:
                        self.log.error("outbox publish failed", extra={"event_id": row["event_id"]})
                        delay = math.ceil(compute_backoff_ms(row.get("attempts", 1), 500, 60_000) / 1000)
                        self.db.mark_outbox_failed(row["id"], delay, str(exc))
            except Exception:
                self.log.exception("outbox loop error")
            time.sleep(self.interval)

    def stop(self) -> None:
        self._stop = True

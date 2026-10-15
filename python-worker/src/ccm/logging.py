from __future__ import annotations

import logging
import sys
from pythonjsonlogger import jsonlogger


SENSITIVE_KEYS = {
    "authorization",
    "password",
    "secret",
    "token",
    "api_key",
    "content",
    "raw",
    "old",
    "new",
    "snapshot",
}


class RedactingJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record.setdefault("service", getattr(record, "service", "ccm-worker"))
        log_record.setdefault("level", record.levelname)
        for key in list(log_record.keys()):
            if str(key).lower() in SENSITIVE_KEYS:
                log_record[key] = "[REDACTED]"


def configure_logging(level: str = "INFO", service: str = "ccm-worker") -> logging.Logger:
    logger = logging.getLogger(service)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    formatter = RedactingJsonFormatter("%(asctime)s %(level)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger

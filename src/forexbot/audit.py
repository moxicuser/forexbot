"""Structured local audit logging."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path


class JsonEventFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "data": getattr(record, "event_data", {}),
        }
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_audit_logger(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"forexbot.audit.{log_path.resolve()}")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(JsonEventFormatter())
    logger.addHandler(handler)
    return logger


def log_event(logger: logging.Logger | None, event: str, **data: object) -> None:
    if logger is not None:
        logger.info(event, extra={"event_data": data})

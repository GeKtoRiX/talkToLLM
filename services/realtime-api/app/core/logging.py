import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if hasattr(record, "event"):
            payload["event"] = getattr(record, "event")
        if hasattr(record, "session_id"):
            payload["session_id"] = getattr(record, "session_id")
        if hasattr(record, "turn_id"):
            payload["turn_id"] = getattr(record, "turn_id")

        return json.dumps(payload)


def configure_logging(level: str) -> None:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())


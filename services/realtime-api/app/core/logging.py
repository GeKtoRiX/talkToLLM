"""Structured JSON logging with pipeline context and stage-timing support."""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Generator


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record with all structured context fields.

    Standard stdlib attributes are excluded from the output to keep records
    clean.  Every ``extra=`` key in a logging call is promoted to a top-level
    JSON field.  Exception information is serialised as ``exc_type``,
    ``exc_message`` and ``traceback``.
    """

    _STDLIB_KEYS: frozenset[str] = frozenset({
        "args", "created", "exc_info", "exc_text", "filename", "funcName",
        "levelname", "levelno", "lineno", "message", "module", "msecs", "msg",
        "name", "pathname", "process", "processName", "relativeCreated",
        "stack_info", "thread", "threadName",
        # promoted fields — handled explicitly, not via the fallback loop
        "event", "session_id", "turn_id", "pipeline_step", "elapsed_ms",
    })

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "source": f"{record.filename}:{record.lineno}",
            "message": record.getMessage(),
        }

        # Promote named context fields to top level (appear before extras)
        for field in ("event", "session_id", "turn_id", "pipeline_step", "elapsed_ms"):
            if hasattr(record, field):
                payload[field] = getattr(record, field)

        # Serialise exception info when present
        if record.exc_info and record.exc_info[0] is not None:
            payload["exc_type"] = record.exc_info[0].__name__
            payload["exc_message"] = str(record.exc_info[1])
            payload["traceback"] = self.formatException(record.exc_info)

        # Pass through any other non-standard extra fields
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in self._STDLIB_KEYS:
                continue
            payload[key] = value

        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())


class BoundLogger:
    """Logger pre-bound with session/turn context for consistent extra fields.

    Reduces the boilerplate of passing ``extra={"session_id": ..., "turn_id":
    ...}`` on every call when the same context applies throughout a scope.

    Usage::

        log = BoundLogger(logger, session_id=sid, turn_id=tid)
        log.info("stt started", event="stt.start")

        # Add a new field without mutating the original
        inner = log.bind(pipeline_step="stt")
        inner.debug("model loaded", model="medium.en")
    """

    __slots__ = ("_logger", "_context")

    def __init__(self, logger: logging.Logger, **context: Any) -> None:
        self._logger = logger
        self._context = context

    def _extra(self, **kwargs: Any) -> dict[str, Any]:
        return {**self._context, **kwargs}

    def bind(self, **extra: Any) -> "BoundLogger":
        """Return a new BoundLogger with additional context fields merged in."""
        return BoundLogger(self._logger, **{**self._context, **extra})

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._logger.debug(msg, extra=self._extra(**kwargs))

    def info(self, msg: str, **kwargs: Any) -> None:
        self._logger.info(msg, extra=self._extra(**kwargs))

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._logger.warning(msg, extra=self._extra(**kwargs))

    def error(self, msg: str, **kwargs: Any) -> None:
        self._logger.error(msg, extra=self._extra(**kwargs))

    def exception(self, msg: str, **kwargs: Any) -> None:
        self._logger.exception(msg, extra=self._extra(**kwargs))


@contextmanager
def log_stage(
    log: BoundLogger,
    step: str,
    **extra: Any,
) -> Generator[dict[str, Any], None, None]:
    """Context manager that logs a pipeline stage start and end with elapsed ms.

    A mutable ``meta`` dict is yielded and populated with ``elapsed_ms`` once
    the block exits, so surrounding code can read the measured duration::

        with log_stage(log, "stt.finalize") as meta:
            transcript = await stt.finalize_utterance()
        stt_latency_s = meta["elapsed_ms"] / 1000

    Both start and end records include ``pipeline_step=step`` plus any
    additional keyword arguments passed to this function.
    """
    meta: dict[str, Any] = {}
    t0 = perf_counter()
    log.debug(f"{step} started", event=f"{step}.start", pipeline_step=step, **extra)
    try:
        yield meta
    finally:
        elapsed_ms = round((perf_counter() - t0) * 1000, 1)
        meta["elapsed_ms"] = elapsed_ms
        log.debug(
            f"{step} completed",
            event=f"{step}.end",
            pipeline_step=step,
            elapsed_ms=elapsed_ms,
            **extra,
        )

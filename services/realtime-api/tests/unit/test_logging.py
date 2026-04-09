"""Unit tests for the structured logging utilities."""
from __future__ import annotations

import json
import logging

import pytest

from app.core.logging import BoundLogger, JsonFormatter, log_stage


# ── JsonFormatter ─────────────────────────────────────────────────────────────


def _capture_record(message: str = "hello", **extra) -> str:
    """Emit a single log record through JsonFormatter and return the JSON string."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test_logging.py",
        lineno=42,
        msg=message,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return formatter.format(record)


def test_json_formatter_includes_required_fields():
    output = json.loads(_capture_record("test message"))
    assert "timestamp" in output
    assert "level" in output
    assert "logger" in output
    assert "source" in output
    assert "message" in output


def test_json_formatter_source_has_file_and_line():
    output = json.loads(_capture_record())
    assert ":" in output["source"]


def test_json_formatter_promotes_event_field():
    output = json.loads(_capture_record(event="stt.start"))
    assert output.get("event") == "stt.start"


def test_json_formatter_promotes_session_and_turn_id():
    output = json.loads(_capture_record(session_id="s1", turn_id="t1"))
    assert output["session_id"] == "s1"
    assert output["turn_id"] == "t1"


def test_json_formatter_promotes_pipeline_step_and_elapsed_ms():
    output = json.loads(_capture_record(pipeline_step="stt", elapsed_ms=42.5))
    assert output["pipeline_step"] == "stt"
    assert output["elapsed_ms"] == 42.5


def test_json_formatter_includes_extra_fields():
    output = json.loads(_capture_record(custom_key="custom_value"))
    assert output.get("custom_key") == "custom_value"


def test_json_formatter_serialises_exception():
    formatter = JsonFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test", level=logging.ERROR, pathname="x.py",
        lineno=1, msg="error occurred", args=(), exc_info=exc_info,
    )
    output = json.loads(formatter.format(record))
    assert output["exc_type"] == "ValueError"
    assert "boom" in output["exc_message"]
    assert "traceback" in output


def test_json_formatter_no_exc_info_field_when_no_exception():
    output = json.loads(_capture_record())
    assert "exc_type" not in output
    assert "traceback" not in output


# ── BoundLogger ───────────────────────────────────────────────────────────────


class _ListHandler(logging.Handler):
    """Collects LogRecord objects for inspection."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _bound_logger_with_handler() -> tuple[BoundLogger, _ListHandler]:
    raw = logging.getLogger("test.bound")
    raw.setLevel(logging.DEBUG)
    handler = _ListHandler()
    raw.addHandler(handler)
    raw.propagate = False
    bound = BoundLogger(raw, session_id="s1", turn_id="t1")
    return bound, handler


def test_bound_logger_injects_context_fields():
    bound, handler = _bound_logger_with_handler()
    bound.info("hello")
    record = handler.records[-1]
    assert getattr(record, "session_id") == "s1"
    assert getattr(record, "turn_id") == "t1"


def test_bound_logger_extra_kwargs_are_included():
    bound, handler = _bound_logger_with_handler()
    bound.info("step", event="stt.start", latency_ms=123)
    record = handler.records[-1]
    assert getattr(record, "event") == "stt.start"
    assert getattr(record, "latency_ms") == 123


def test_bound_logger_bind_creates_new_instance_with_merged_context():
    bound, handler = _bound_logger_with_handler()
    child = bound.bind(pipeline_step="tts")
    child.info("chunk sent")
    record = handler.records[-1]
    assert getattr(record, "session_id") == "s1"
    assert getattr(record, "pipeline_step") == "tts"


def test_bound_logger_bind_does_not_mutate_parent():
    bound, handler = _bound_logger_with_handler()
    _ = bound.bind(pipeline_step="extra")
    bound.info("parent log")
    record = handler.records[-1]
    assert not hasattr(record, "pipeline_step")


def test_bound_logger_debug_level():
    bound, handler = _bound_logger_with_handler()
    bound.debug("low-level")
    assert handler.records[-1].levelname == "DEBUG"


def test_bound_logger_warning_level():
    bound, handler = _bound_logger_with_handler()
    bound.warning("careful")
    assert handler.records[-1].levelname == "WARNING"


# ── log_stage ─────────────────────────────────────────────────────────────────


def test_log_stage_emits_start_and_end_records():
    bound, handler = _bound_logger_with_handler()
    with log_stage(bound, "stt.transcribe"):
        pass
    events = [getattr(r, "event", None) for r in handler.records]
    assert "stt.transcribe.start" in events
    assert "stt.transcribe.end" in events


def test_log_stage_meta_contains_elapsed_ms():
    bound, _ = _bound_logger_with_handler()
    with log_stage(bound, "ocr") as meta:
        pass
    assert "elapsed_ms" in meta
    assert isinstance(meta["elapsed_ms"], float)
    assert meta["elapsed_ms"] >= 0.0


def test_log_stage_propagates_extra_to_both_records():
    bound, handler = _bound_logger_with_handler()
    with log_stage(bound, "llm", model="gpt"):
        pass
    for record in handler.records:
        assert getattr(record, "model", None) == "gpt"


def test_log_stage_end_record_includes_elapsed_ms_field():
    bound, handler = _bound_logger_with_handler()
    with log_stage(bound, "tts"):
        pass
    end_record = next(r for r in handler.records if getattr(r, "event", "") == "tts.end")
    assert hasattr(end_record, "elapsed_ms")


@pytest.mark.asyncio
async def test_log_stage_works_around_async_code():
    import asyncio

    bound, handler = _bound_logger_with_handler()
    with log_stage(bound, "async.step") as meta:
        await asyncio.sleep(0)
    assert meta["elapsed_ms"] >= 0.0
    events = [getattr(r, "event", None) for r in handler.records]
    assert "async.step.start" in events
    assert "async.step.end" in events

"""Integration tests for TurnOrchestrator with mock providers."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest

from app.api.protocol import ImageAttachment
from app.core.config import AppSettings
from app.core.orchestrator import TurnOrchestrator
from app.core.session_manager import SessionContext
from app.core.state_machine import SessionState
from app.providers.base import ChatMessage, ChatTextPart, LLMProvider
from app.providers.llm import MockLLMProvider
from app.providers.stt import MockWhisperProvider
from app.providers.tts import MockKokoroProvider


# ── Helpers ───────────────────────────────────────────────────────────────────


class CapturingWS:
    """Fake WebSocket that records all send_json calls."""

    sent: list[dict]

    def __init__(self) -> None:
        self.sent = []

    async def send_json(self, data: dict) -> None:  # noqa: D102
        self.sent.append(data)

    async def send_bytes(self, data: bytes) -> None:  # noqa: D102
        pass


def _make_ctx(state: SessionState = SessionState.TRANSCRIBING) -> tuple[SessionContext, CapturingWS]:
    ws: Any = CapturingWS()
    ctx = SessionContext(websocket=ws, session_id="test-session")
    ctx.state = state
    return ctx, ws


def _make_orchestrator() -> TurnOrchestrator:
    return TurnOrchestrator(
        stt_factory=MockWhisperProvider,
        llm=MockLLMProvider(),
        tts=MockKokoroProvider(),
        system_prompt="You are helpful.",
    )


# ── Voice turn ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_voice_turn_emits_transcript_llm_and_tts_events():
    ctx, ws = _make_ctx(SessionState.TRANSCRIBING)
    ctx.current_turn_id = "turn-voice"
    ctx.current_audio = bytearray(b"\x00\x00" * 3200)

    await _make_orchestrator().process_turn(ctx)

    types = {e["type"] for e in ws.sent}
    assert "llm.thinking" in types
    assert "transcript.final" in types
    assert "response.text.delta" in types
    assert "response.text.final" in types
    assert "tts.chunk" in types


@pytest.mark.asyncio
async def test_voice_turn_appends_history():
    ctx, _ = _make_ctx(SessionState.TRANSCRIBING)
    ctx.current_turn_id = "turn-hist"
    ctx.current_audio = bytearray(b"\x00\x00" * 3200)

    await _make_orchestrator().process_turn(ctx)

    roles = [m["role"] for m in ctx.history]
    assert "user" in roles
    assert "assistant" in roles


@pytest.mark.asyncio
async def test_voice_turn_ends_in_listening_state():
    ctx, _ = _make_ctx(SessionState.TRANSCRIBING)
    ctx.current_turn_id = "turn-state"
    ctx.current_audio = bytearray(b"\x00\x00" * 3200)

    await _make_orchestrator().process_turn(ctx)

    assert ctx.state == SessionState.LISTENING


# ── Text turn ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_text_turn_skips_stt():
    ctx, ws = _make_ctx(SessionState.THINKING)
    ctx.current_turn_id = "turn-text"
    ctx.current_text_input = "Hello there"
    ctx.current_audio = bytearray()

    await _make_orchestrator().process_turn(ctx)

    types = {e["type"] for e in ws.sent}
    assert "transcript.final" not in types
    assert "llm.thinking" in types
    assert "response.text.final" in types


@pytest.mark.asyncio
async def test_text_turn_with_screenshot_response_mentions_screenshot():
    from app.providers.base import ChatImagePart

    ctx, ws = _make_ctx(SessionState.THINKING)
    ctx.current_turn_id = "turn-vision"
    ctx.current_text_input = "Analyze this"
    ctx.current_attachments = [
        ImageAttachment(mimeType="image/png", dataBase64="ZmFrZQ==", width=100, height=100)
    ]

    await _make_orchestrator().process_turn(ctx)

    final = next(e for e in ws.sent if e["type"] == "response.text.final")
    assert "screenshot" in final["payload"]["text"].lower()


# ── Interruption ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pre_cancelled_turn_does_not_send_response_final():
    ctx, ws = _make_ctx(SessionState.TRANSCRIBING)
    ctx.current_turn_id = "turn-interrupt"
    ctx.current_audio = bytearray(b"\x00\x00" * 3200)

    await ctx.interruption_manager.mark_cancelled("turn-interrupt")
    await _make_orchestrator().process_turn(ctx)

    types = {e["type"] for e in ws.sent}
    assert "response.text.final" not in types


# ── Error handling ────────────────────────────────────────────────────────────


class _FailingLLM(LLMProvider):
    async def stream(self, messages: list[ChatMessage], config: dict[str, Any]) -> AsyncIterator[str]:
        raise RuntimeError("LLM exploded")
        yield ""  # type: ignore[misc]  # makes this an async generator

    async def cancel(self, request_id: str) -> None:
        pass


class _CapturingLLM(LLMProvider):
    def __init__(self) -> None:
        self.messages: list[ChatMessage] | None = None
        self.config: dict[str, Any] | None = None

    async def stream(self, messages: list[ChatMessage], config: dict[str, Any]) -> AsyncIterator[str]:
        self.messages = messages
        self.config = config
        yield "OCR only response"

    async def cancel(self, request_id: str) -> None:
        pass


@pytest.mark.asyncio
async def test_llm_error_sends_error_event():
    ctx, ws = _make_ctx(SessionState.THINKING)
    ctx.current_turn_id = "turn-err"
    ctx.current_text_input = "test"

    orch = TurnOrchestrator(
        stt_factory=MockWhisperProvider,
        llm=_FailingLLM(),
        tts=MockKokoroProvider(),
        system_prompt="system",
    )
    await orch.process_turn(ctx)

    error_events = [e for e in ws.sent if e["type"] == "error"]
    assert len(error_events) == 1
    assert error_events[0]["payload"]["code"] == "TURN_FAILED"


@pytest.mark.asyncio
async def test_llm_error_does_not_append_to_history():
    ctx, _ = _make_ctx(SessionState.THINKING)
    ctx.current_turn_id = "turn-err-hist"
    ctx.current_text_input = "crash me"

    orch = TurnOrchestrator(
        stt_factory=MockWhisperProvider,
        llm=_FailingLLM(),
        tts=MockKokoroProvider(),
        system_prompt="system",
    )
    initial_history = list(ctx.history)
    await orch.process_turn(ctx)

    # user entry was appended before LLM ran; assistant should NOT be added
    assistant_entries = [m for m in ctx.history if m["role"] == "assistant"]
    assert len(assistant_entries) == 0


@pytest.mark.asyncio
async def test_error_turn_recovers_to_listening_state():
    ctx, _ = _make_ctx(SessionState.THINKING)
    ctx.current_turn_id = "turn-recover"
    ctx.current_text_input = "crash"

    orch = TurnOrchestrator(
        stt_factory=MockWhisperProvider,
        llm=_FailingLLM(),
        tts=MockKokoroProvider(),
        system_prompt="system",
    )
    await orch.process_turn(ctx)

    assert ctx.state == SessionState.LISTENING


# ── Cancel turn ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_turn_with_none_does_not_raise():
    orch = _make_orchestrator()
    await orch.cancel_turn(None)


@pytest.mark.asyncio
async def test_successful_ocr_uses_text_only_prompt_and_text_model():
    ctx, _ = _make_ctx(SessionState.THINKING)
    ctx.current_turn_id = "turn-ocr"
    ctx.current_text_input = "What does this say?"
    ctx.current_attachments = [
        ImageAttachment(mimeType="image/png", dataBase64="ZmFrZQ==", width=100, height=100)
    ]

    llm = _CapturingLLM()
    orch = TurnOrchestrator(
        stt_factory=MockWhisperProvider,
        llm=llm,
        tts=MockKokoroProvider(),
        system_prompt="system",
        settings=AppSettings(_env_file=None, ocr_backend="tesseract"),
    )

    with patch("app.core.orchestrator.extract_text_from_image", return_value="# Personal information\nWilliam Brown"):
        await orch.process_turn(ctx)

    assert llm.config is not None
    assert llm.config["has_images"] is False
    assert llm.messages is not None
    assert len(llm.messages[-1].content_parts) == 1
    assert isinstance(llm.messages[-1].content_parts[0], ChatTextPart)
    assert "Personal information" in llm.messages[-1].content_parts[0].text

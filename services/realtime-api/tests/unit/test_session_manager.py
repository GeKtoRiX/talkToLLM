"""Unit tests for SessionManager and SessionContext."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.protocol import ImageAttachment
from app.core.session_manager import SessionContext, SessionManager
from app.core.state_machine import SessionState


def _attachment() -> ImageAttachment:
    return ImageAttachment(mimeType="image/png", dataBase64="ZmFrZQ==", width=100, height=100)


def _mock_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


# ── create / close ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_returns_idle_context():
    manager = SessionManager()
    ctx = await manager.create(_mock_ws())

    assert ctx.state == SessionState.IDLE
    assert ctx.session_id
    assert ctx.session_id in manager.sessions


@pytest.mark.asyncio
async def test_close_removes_session_from_registry():
    manager = SessionManager()
    ctx = await manager.create(_mock_ws())
    session_id = ctx.session_id

    await manager.close(ctx)

    assert session_id not in manager.sessions


@pytest.mark.asyncio
async def test_close_cancels_running_task():
    manager = SessionManager()
    ctx = await manager.create(_mock_ws())
    task = asyncio.create_task(asyncio.sleep(100))
    ctx.current_task = task

    await manager.close(ctx)
    await asyncio.sleep(0)  # let the event loop process the cancellation

    assert task.cancelled()


# ── begin_voice_turn ─────────────────────────────────────────────────────────


def test_begin_voice_turn_transitions_to_capturing_speech():
    manager = SessionManager()
    ctx = SessionContext(websocket=_mock_ws(), session_id="s1", state=SessionState.LISTENING)

    turn_id = manager.begin_voice_turn(ctx)

    assert turn_id == ctx.current_turn_id
    assert ctx.state == SessionState.CAPTURING_SPEECH


def test_begin_voice_turn_clears_prior_audio_and_text():
    manager = SessionManager()
    ctx = SessionContext(websocket=_mock_ws(), session_id="s1", state=SessionState.LISTENING)
    ctx.current_audio.extend(b"\x01\x02\x03")
    ctx.current_text_input = "leftover"

    manager.begin_voice_turn(ctx)

    assert ctx.current_audio == bytearray()
    assert ctx.current_text_input is None


def test_begin_voice_turn_stores_attachments():
    manager = SessionManager()
    ctx = SessionContext(websocket=_mock_ws(), session_id="s1", state=SessionState.LISTENING)
    att = _attachment()

    manager.begin_voice_turn(ctx, attachments=[att])

    assert ctx.current_attachments == [att]


# ── begin_text_turn ──────────────────────────────────────────────────────────


def test_begin_text_turn_transitions_to_thinking():
    manager = SessionManager()
    ctx = SessionContext(websocket=_mock_ws(), session_id="s1", state=SessionState.LISTENING)

    turn_id = manager.begin_text_turn(ctx, "hello world")

    assert turn_id == ctx.current_turn_id
    assert ctx.current_text_input == "hello world"
    assert ctx.state == SessionState.THINKING


def test_begin_text_turn_stores_attachments():
    manager = SessionManager()
    ctx = SessionContext(websocket=_mock_ws(), session_id="s1", state=SessionState.LISTENING)
    att = _attachment()

    manager.begin_text_turn(ctx, "analyze this", attachments=[att])

    assert ctx.current_attachments == [att]


# ── append_audio ─────────────────────────────────────────────────────────────


def test_append_audio_accumulates_bytes():
    manager = SessionManager()
    ctx = SessionContext(websocket=_mock_ws(), session_id="s1")

    manager.append_audio(ctx, b"\x01\x02")
    manager.append_audio(ctx, b"\x03\x04")

    assert bytes(ctx.current_audio) == b"\x01\x02\x03\x04"


# ── mark_interrupted ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_interrupted_transitions_to_interrupted():
    manager = SessionManager()
    ctx = SessionContext(websocket=_mock_ws(), session_id="s1", state=SessionState.SPEAKING)
    ctx.current_turn_id = "turn-1"

    await manager.mark_interrupted(ctx)

    assert ctx.state == SessionState.INTERRUPTED


@pytest.mark.asyncio
async def test_mark_interrupted_cancels_current_turn_id():
    manager = SessionManager()
    ctx = SessionContext(websocket=_mock_ws(), session_id="s1", state=SessionState.SPEAKING)
    ctx.current_turn_id = "turn-x"

    await manager.mark_interrupted(ctx)

    assert await ctx.interruption_manager.is_cancelled("turn-x")


# ── send_event ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_event_increments_sequence():
    ws = _mock_ws()
    ctx = SessionContext(websocket=ws, session_id="s1")
    ctx.current_turn_id = "t1"

    await ctx.send_event("some.event", {"key": "val"})
    await ctx.send_event("other.event", {})

    calls = ws.send_json.call_args_list
    assert calls[0][0][0]["seq"] == 1
    assert calls[1][0][0]["seq"] == 2


@pytest.mark.asyncio
async def test_send_event_includes_session_and_turn_ids():
    ws = _mock_ws()
    ctx = SessionContext(websocket=ws, session_id="my-session")
    ctx.current_turn_id = "my-turn"

    await ctx.send_event("test.event", {})

    payload = ws.send_json.call_args[0][0]
    assert payload["sessionId"] == "my-session"
    assert payload["turnId"] == "my-turn"

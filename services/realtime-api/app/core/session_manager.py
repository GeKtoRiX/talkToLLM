from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from fastapi import WebSocket

from app.api.protocol import ImageAttachment
from app.core.interruption import InterruptionManager
from app.core.metrics import interruption_counter, session_counter
from app.core.state_machine import SessionState, transition_state

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SessionContext:
    websocket: WebSocket
    session_id: str
    state: SessionState = SessionState.IDLE
    current_turn_id: str | None = None
    current_audio: bytearray = field(default_factory=bytearray)
    current_text_input: str | None = None
    current_attachments: list[ImageAttachment] = field(default_factory=list)
    history: list[dict[str, str]] = field(default_factory=list)
    response_text: str = ""
    current_task: asyncio.Task[None] | None = None
    sequence: int = 0
    interruption_manager: InterruptionManager = field(default_factory=InterruptionManager)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    turn_started_perf: float | None = None
    speech_ended_perf: float | None = None

    async def send_event(self, event_type: str, payload: dict) -> None:
        self.sequence += 1
        await self.websocket.send_json(
            {
                "type": event_type,
                "sessionId": self.session_id,
                "turnId": self.current_turn_id,
                "seq": self.sequence,
                "timestamp": datetime.now(UTC).isoformat(),
                "payload": payload,
            }
        )

    async def send_tts_chunk(self, chunk_index: int, text: str, audio_bytes: bytes) -> None:
        await self.send_event(
            "tts.chunk",
            {
                "audioBase64": base64.b64encode(audio_bytes).decode("ascii"),
                "mimeType": "audio/wav",
                "chunkIndex": chunk_index,
                "text": text,
            },
        )


class SessionManager:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionContext] = {}

    async def create(self, websocket: WebSocket) -> SessionContext:
        session = SessionContext(websocket=websocket, session_id=str(uuid4()))
        self.sessions[session.session_id] = session
        session_counter.labels(event="started").inc()
        return session

    async def close(self, session: SessionContext) -> None:
        if session.current_task:
            session.current_task.cancel()
        self.sessions.pop(session.session_id, None)
        session_counter.labels(event="stopped").inc()

    def begin_voice_turn(self, session: SessionContext, attachments: list[ImageAttachment] | None = None) -> str:
        session.current_turn_id = str(uuid4())
        session.current_audio.clear()
        session.current_text_input = None
        session.current_attachments = list(attachments or [])
        session.response_text = ""
        session.turn_started_perf = perf_counter()
        session.speech_ended_perf = None
        session.state = transition_state(session.state, "speech_started")
        return session.current_turn_id

    def begin_text_turn(self, session: SessionContext, text: str, attachments: list[ImageAttachment] | None = None) -> str:
        session.current_turn_id = str(uuid4())
        session.current_audio.clear()
        session.current_text_input = text
        session.current_attachments = list(attachments or [])
        session.response_text = ""
        session.turn_started_perf = perf_counter()
        session.speech_ended_perf = perf_counter()
        session.state = transition_state(session.state, "text_submitted")
        return session.current_turn_id

    def append_audio(self, session: SessionContext, chunk: bytes) -> None:
        session.current_audio.extend(chunk)

    async def mark_interrupted(self, session: SessionContext) -> None:
        if session.current_turn_id:
            await session.interruption_manager.mark_cancelled(session.current_turn_id)
        session.state = transition_state(session.state, "playback_interrupted")
        interruption_counter.inc()
        logger.info(
            "playback interrupted",
            extra={"event": "playback.interrupt", "session_id": session.session_id, "turn_id": session.current_turn_id},
        )

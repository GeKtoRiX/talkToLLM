from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api.protocol import EventEnvelope, SessionStartPayload
from app.core.config import AppSettings
from app.core.logging import configure_logging
from app.core.metrics import metrics_response
from app.core.orchestrator import TurnOrchestrator
from app.core.session_manager import SessionManager
from app.core.state_machine import transition_state
from app.providers.factory import create_llm_provider, create_stt_factory, create_tts_provider

logger = logging.getLogger(__name__)


def create_app(settings: AppSettings | None = None) -> FastAPI:
    app_settings = settings or AppSettings()
    configure_logging(app_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        session_manager = SessionManager()
        llm = create_llm_provider(app_settings)
        tts = create_tts_provider(app_settings)
        app.state.settings = app_settings
        app.state.session_manager = session_manager
        app.state.orchestrator = TurnOrchestrator(
            stt_factory=create_stt_factory(app_settings),
            llm=llm,
            tts=tts,
            system_prompt=app_settings.assistant_system_prompt,
        )
        yield

    app = FastAPI(title="talkToLLM realtime api", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[app_settings.allowed_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    async def healthcheck():
        return {"status": "ok", "environment": app_settings.app_env}

    @app.get("/metrics")
    async def metrics():
        return metrics_response()

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        session = await app.state.session_manager.create(websocket)

        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.receive":
                    if "bytes" in message and message["bytes"] is not None:
                        app.state.session_manager.append_audio(session, message["bytes"])
                        continue

                    if "text" in message and message["text"] is not None:
                        event = EventEnvelope.model_validate_json(message["text"])

                        if event.type == "session.start":
                            payload = SessionStartPayload.model_validate(event.payload)
                            session.state = transition_state(session.state, "session_started")
                            await session.send_event("session.started", payload.model_dump())
                        elif event.type == "speech.start":
                            if session.state.value == "speaking":
                                await app.state.session_manager.mark_interrupted(session)
                                await app.state.orchestrator.cancel_turn(session.current_turn_id)
                                if session.current_task and not session.current_task.done():
                                    session.current_task.cancel()
                                await session.send_event("playback.stop", {})
                            app.state.session_manager.begin_turn(session)
                        elif event.type == "speech.end":
                            session.state = transition_state(session.state, "speech_ended")
                            session.speech_ended_perf = perf_counter()
                            if session.current_task and not session.current_task.done():
                                await app.state.orchestrator.cancel_turn(session.current_turn_id)
                                session.current_task.cancel()
                            session.current_task = asyncio.create_task(app.state.orchestrator.process_turn(session))
                        elif event.type == "playback.interrupt":
                            await app.state.session_manager.mark_interrupted(session)
                            await app.state.orchestrator.cancel_turn(session.current_turn_id)
                            if session.current_task:
                                session.current_task.cancel()
                            await session.send_event("playback.stop", {})
                        elif event.type == "session.stop":
                            session.state = transition_state(session.state, "session_stopped")
                            await app.state.orchestrator.cancel_turn(session.current_turn_id)
                            await session.send_event("playback.stop", {})
                            await websocket.close()
                            break
                elif message["type"] == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            logger.info(
                "websocket disconnected",
                extra={"event": "session.disconnect", "session_id": session.session_id, "turn_id": session.current_turn_id},
            )
        finally:
            await app.state.session_manager.close(session)

    return app


app = create_app()

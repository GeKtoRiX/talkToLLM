from __future__ import annotations

import asyncio
import base64
import binascii
import logging
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from app.api.protocol import EventEnvelope, ImageAttachment, SessionStartPayload, SpeechStartPayload, TextSubmitPayload
from app.core.config import AppSettings
from app.core.logging import configure_logging
from app.core.metrics import metrics_response
from app.core.orchestrator import TurnOrchestrator
from app.core.session_manager import SessionManager
from app.core.state_machine import transition_state
from app.providers.factory import create_llm_provider, create_stt_factory, create_tts_provider
from app.study.router import router as study_router
from app.study.service import StudyService

logger = logging.getLogger(__name__)


def create_app(settings: AppSettings | None = None) -> FastAPI:
    app_settings = settings or AppSettings()
    configure_logging(app_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        session_manager = SessionManager(app_settings)
        llm = create_llm_provider(app_settings)
        tts = create_tts_provider(app_settings)
        app.state.settings = app_settings
        app.state.session_manager = session_manager
        app.state.study_service = StudyService(app_settings.study_db_path_resolved)
        app.state.orchestrator = TurnOrchestrator(
            stt_factory=create_stt_factory(app_settings),
            llm=llm,
            tts=tts,
            system_prompt=app_settings.assistant_system_prompt,
            settings=app_settings,
        )
        logger.info(
            "application started",
            extra={
                "event": "app.started",
                "env": app_settings.app_env,
                "llm_provider": app_settings.llm_provider,
                "stt_provider": app_settings.stt_provider,
                "tts_provider": app_settings.tts_provider,
                "ocr_backend": app_settings.ocr_backend,
                "log_level": app_settings.log_level,
            },
        )
        yield
        logger.info("application shutting down", extra={"event": "app.shutdown"})

    app = FastAPI(title="talkToLLM realtime api", lifespan=lifespan)
    app.include_router(study_router)
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

        # Log connection details when available (Starlette exposes client info)
        client = getattr(websocket, "client", None)
        remote = f"{client.host}:{client.port}" if client else "unknown"
        logger.info(
            "websocket connection accepted",
            extra={
                "event": "ws.connected",
                "session_id": session.session_id,
                "remote": remote,
            },
        )
        conn_t0 = perf_counter()

        def validate_attachments(attachments: list[ImageAttachment]) -> list[ImageAttachment]:
            validated: list[ImageAttachment] = []
            allowed_mime_types = app_settings.screenshot_allowed_mime_type_set

            for attachment in attachments:
                if attachment.mimeType not in allowed_mime_types:
                    allowed = ", ".join(sorted(allowed_mime_types))
                    raise ValueError(
                        f"Unsupported screenshot format '{attachment.mimeType}'. Allowed formats: {allowed}."
                    )

                try:
                    payload_bytes = base64.b64decode(attachment.dataBase64, validate=True)
                except (binascii.Error, ValueError) as error:
                    raise ValueError("Screenshot payload is not valid base64 image data.") from error

                if len(payload_bytes) > app_settings.screenshot_max_bytes:
                    raise ValueError(f"Screenshot exceeds the {app_settings.screenshot_max_bytes}-byte limit.")

                validated.append(attachment)

            return validated

        async def cancel_active_turn(send_playback_stop: bool = False, mark_interrupted: bool = False) -> None:
            if mark_interrupted:
                await app.state.session_manager.mark_interrupted(session)
            await app.state.orchestrator.cancel_turn(session.current_turn_id)
            if session.current_task and not session.current_task.done():
                session.current_task.cancel()
            if send_playback_stop:
                await session.send_event("playback.stop", {})

        async def send_error(code: str, message: str) -> None:
            session.state = transition_state(session.state, "failed")
            logger.warning(
                "sending error event",
                extra={
                    "event": "ws.error",
                    "session_id": session.session_id,
                    "turn_id": session.current_turn_id,
                    "code": code,
                    "detail": message,
                },
            )
            await session.send_event("error", {"code": code, "message": message})

        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.receive":
                    if "bytes" in message and message["bytes"] is not None:
                        app.state.session_manager.append_audio(session, message["bytes"])
                        continue

                    if "text" in message and message["text"] is not None:
                        event = EventEnvelope.model_validate_json(message["text"])

                        logger.debug(
                            "ws event received",
                            extra={
                                "event": "ws.event.received",
                                "session_id": session.session_id,
                                "turn_id": session.current_turn_id,
                                "event_type": event.type,
                                "state": session.state.value,
                            },
                        )

                        if event.type == "session.start":
                            payload = SessionStartPayload.model_validate(event.payload)
                            prev_state = session.state
                            session.state = transition_state(session.state, "session_started")
                            logger.info(
                                "session started",
                                extra={
                                    "event": "session.start",
                                    "session_id": session.session_id,
                                    "state": f"{prev_state.value} -> {session.state.value}",
                                    "sample_rate": payload.sampleRate,
                                    "language": payload.language,
                                },
                            )
                            await session.send_event("session.started", payload.model_dump())

                        elif event.type == "speech.start":
                            try:
                                payload = SpeechStartPayload.model_validate(event.payload)
                            except ValidationError as error:
                                await send_error("INVALID_ATTACHMENT", str(error))
                                continue

                            try:
                                attachments = validate_attachments(payload.attachments)
                            except ValueError as error:
                                await send_error("INVALID_ATTACHMENT", str(error))
                                continue

                            if session.state.value in {"speaking", "synthesizing"}:
                                logger.info(
                                    "speech.start interrupting active playback",
                                    extra={
                                        "event": "ws.interrupt.on_speech",
                                        "session_id": session.session_id,
                                        "state": session.state.value,
                                    },
                                )
                                await cancel_active_turn(send_playback_stop=True, mark_interrupted=True)
                            elif session.current_task and not session.current_task.done():
                                await cancel_active_turn()

                            app.state.session_manager.begin_voice_turn(session, attachments)

                        elif event.type == "speech.end":
                            prev_state = session.state
                            session.state = transition_state(session.state, "speech_ended")
                            session.speech_ended_perf = perf_counter()
                            logger.debug(
                                "speech ended — launching turn",
                                extra={
                                    "event": "ws.speech.end",
                                    "session_id": session.session_id,
                                    "turn_id": session.current_turn_id,
                                    "state": f"{prev_state.value} -> {session.state.value}",
                                    "audio_bytes": len(session.current_audio),
                                },
                            )
                            session.current_task = asyncio.create_task(
                                app.state.orchestrator.process_turn(session)
                            )

                        elif event.type == "text.submit":
                            try:
                                payload = TextSubmitPayload.model_validate(event.payload)
                                text = payload.text.strip()
                            except ValidationError as error:
                                await send_error("INVALID_TEXT_INPUT", str(error))
                                continue

                            try:
                                attachments = validate_attachments(payload.attachments)
                            except ValueError as error:
                                await send_error("INVALID_ATTACHMENT", str(error))
                                continue

                            if not text:
                                await send_error("INVALID_TEXT_INPUT", "Text question cannot be empty.")
                                continue

                            if session.state.value in {"speaking", "synthesizing"}:
                                logger.info(
                                    "text.submit interrupting active playback",
                                    extra={
                                        "event": "ws.interrupt.on_text",
                                        "session_id": session.session_id,
                                        "state": session.state.value,
                                    },
                                )
                                await cancel_active_turn(send_playback_stop=True, mark_interrupted=True)
                            elif session.current_task and not session.current_task.done():
                                await cancel_active_turn()

                            app.state.session_manager.begin_text_turn(session, text, attachments)
                            await session.send_event("transcript.final", {"text": text, "isFinal": True})
                            session.current_task = asyncio.create_task(
                                app.state.orchestrator.process_turn(session)
                            )

                        elif event.type == "playback.interrupt":
                            logger.info(
                                "playback interrupt requested",
                                extra={
                                    "event": "ws.playback.interrupt",
                                    "session_id": session.session_id,
                                    "turn_id": session.current_turn_id,
                                    "state": session.state.value,
                                },
                            )
                            await cancel_active_turn(send_playback_stop=True, mark_interrupted=True)

                        elif event.type == "session.stop":
                            session.state = transition_state(session.state, "session_stopped")
                            await app.state.orchestrator.cancel_turn(session.current_turn_id)
                            if session.current_task and not session.current_task.done():
                                session.current_task.cancel()
                            await session.send_event("playback.stop", {})
                            logger.info(
                                "session stop requested — closing websocket",
                                extra={
                                    "event": "ws.session.stop",
                                    "session_id": session.session_id,
                                    "conn_duration_s": round(perf_counter() - conn_t0, 1),
                                },
                            )
                            await websocket.close()
                            break

                elif message["type"] == "websocket.disconnect":
                    logger.info(
                        "websocket disconnected",
                        extra={
                            "event": "ws.disconnected",
                            "session_id": session.session_id,
                            "turn_id": session.current_turn_id,
                            "conn_duration_s": round(perf_counter() - conn_t0, 1),
                        },
                    )
                    break

        except WebSocketDisconnect:
            logger.info(
                "websocket disconnected (exception)",
                extra={
                    "event": "ws.disconnect.exception",
                    "session_id": session.session_id,
                    "turn_id": session.current_turn_id,
                    "conn_duration_s": round(perf_counter() - conn_t0, 1),
                },
            )
        finally:
            await app.state.session_manager.close(session)

    return app


app = create_app()

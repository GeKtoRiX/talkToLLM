from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Callable

from app.core.config import AppSettings
from app.core.logging import BoundLogger, log_stage
from app.core.metrics import observe_stage, provider_errors
from app.core.ocr import extract_text_from_image
from app.core.state_machine import SessionState, transition_state
from app.core.text import SentenceChunker, build_prompt_messages, strip_tts_noise
from app.providers.base import LLMProvider, STTProvider, TTSProvider

_base_logger = logging.getLogger(__name__)


class TurnOrchestrator:
    def __init__(
        self,
        stt_factory: Callable[[], STTProvider],
        llm: LLMProvider,
        tts: TTSProvider,
        system_prompt: str,
        settings: AppSettings | None = None,
    ) -> None:
        self.stt_factory = stt_factory
        self.llm = llm
        self.tts = tts
        self.system_prompt = system_prompt
        self.settings = settings or AppSettings()

    async def cancel_turn(self, turn_id: str | None) -> None:
        if turn_id is None:
            return
        await asyncio.gather(
            self.llm.cancel(turn_id),
            self.tts.cancel(turn_id),
            return_exceptions=True,
        )

    async def process_turn(self, session) -> None:  # noqa: ANN001
        turn_id = session.current_turn_id
        if turn_id is None:
            return

        # Bind session/turn context once; use this logger for the whole turn
        log = BoundLogger(_base_logger, session_id=session.session_id, turn_id=turn_id)

        turn_started = session.turn_started_perf or perf_counter()
        turn_type = "text" if session.current_text_input is not None else "voice"
        attachments = list(session.current_attachments)

        log.info(
            "turn started",
            event="turn.start",
            turn_type=turn_type,
            attachment_count=len(attachments),
            history_size=len(session.history),
            audio_bytes=len(session.current_audio),
        )

        user_text = ""
        llm_first_token_latency: float | None = None
        tts_first_audio_latency: float | None = None
        time_to_first_audio: float | None = None
        tts_generation_started: float | None = None
        stt_latency: float | None = None
        ocr_latency: float | None = None
        ocr_total_chars: int = 0

        try:
            # ── Phase 0: Speech-to-Text (voice turns only) ────────────────────
            if session.current_text_input is None:
                stt = self.stt_factory()
                await stt.start_session({"sample_rate": 16000, "language": "en"})

                audio_chunk = bytes(session.current_audio)
                if audio_chunk:
                    await stt.append_audio(audio_chunk)

                log.info(
                    "stt transcription started",
                    event="stt.start",
                    pipeline_step="stt",
                    audio_bytes=len(audio_chunk),
                    timeout_s=self.settings.stt_timeout_seconds,
                )
                stt_started = perf_counter()
                try:
                    transcript = await asyncio.wait_for(
                        stt.finalize_utterance(),
                        timeout=self.settings.stt_timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    log.warning(
                        "stt transcription timed out",
                        event="stt.timeout",
                        pipeline_step="stt",
                        timeout_s=self.settings.stt_timeout_seconds,
                    )
                    raise RuntimeError(
                        f"STT transcription timed out after {self.settings.stt_timeout_seconds}s. "
                        "Try speaking again or check the STT provider."
                    )

                stt_latency = perf_counter() - stt_started
                observe_stage("stt_completed", stt_latency)
                user_text = transcript.text

                log.info(
                    "stt transcription completed",
                    event="stt.end",
                    pipeline_step="stt",
                    latency_ms=round(stt_latency * 1000, 1),
                    transcript_length=len(user_text),
                    is_final=transcript.is_final,
                )

                session.state = transition_state(session.state, "transcript_finalized")
                session.history.append({"role": "user", "content": user_text})
                await session.send_event("transcript.final", {"text": user_text, "isFinal": True})
            else:
                user_text = session.current_text_input
                session.history.append({"role": "user", "content": user_text})
                log.debug(
                    "text input accepted — skipping stt",
                    event="stt.skip",
                    pipeline_step="stt",
                    text_length=len(user_text),
                )

            await session.send_event("llm.thinking", {"state": "thinking"})

            # ── Phase 1: OCR (when attachments present and vision bypass is off) ──
            ocr_texts: list[str] | None = None
            vision_handles_images = bool(
                attachments
                and self.settings.llm_vision_model
                and self.settings.llm_vision_bypass_ocr
            )
            if vision_handles_images:
                log.info(
                    "vision model will handle images directly — OCR skipped",
                    event="vision.bypass_ocr",
                    pipeline_step="ocr",
                    model=self.settings.llm_vision_model,
                    attachment_count=len(attachments),
                )
            elif attachments and self.settings.ocr_enabled:
                log.info(
                    "ocr started",
                    event="ocr.start",
                    pipeline_step="ocr",
                    attachment_count=len(attachments),
                    backend=self.settings.ocr_backend,
                )
                ocr_t0 = perf_counter()
                loop = asyncio.get_running_loop()
                ocr_tasks = [
                    loop.run_in_executor(None, extract_text_from_image, att.dataBase64, self.settings)
                    for att in attachments
                ]
                raw_results = await asyncio.gather(*ocr_tasks, return_exceptions=True)
                ocr_latency = perf_counter() - ocr_t0
                extracted: list[str] = []
                for idx, result in enumerate(raw_results):
                    if isinstance(result, Exception):
                        log.warning(
                            "ocr attachment failed",
                            event="ocr.attachment.failed",
                            pipeline_step="ocr",
                            attachment_index=idx,
                            error=str(result),
                        )
                    elif result:
                        extracted.append(result)
                        ocr_total_chars += len(result)
                        log.debug(
                            "ocr attachment extracted",
                            event="ocr.attachment.ok",
                            pipeline_step="ocr",
                            attachment_index=idx,
                            chars=len(result),
                        )
                log.info(
                    "ocr completed",
                    event="ocr.end",
                    pipeline_step="ocr",
                    latency_ms=round(ocr_latency * 1000, 1),
                    total_chars=ocr_total_chars,
                    attachments_ok=len(extracted),
                    attachments_failed=len(attachments) - len(extracted),
                )
                if extracted:
                    ocr_texts = extracted
                else:
                    # All OCR attempts failed — fall back to passing raw images
                    log.warning(
                        "all ocr attachments failed — falling back to raw image passthrough",
                        event="ocr.fallback",
                        pipeline_step="ocr",
                        attachment_count=len(attachments),
                    )

            # ── Phase 2: Build prompt ─────────────────────────────────────────
            effective_attachments = None if ocr_texts else attachments
            messages = build_prompt_messages(
                self.system_prompt,
                session.history[:-1],
                user_text,
                attachments=effective_attachments,
                ocr_texts=ocr_texts,
            )
            log.debug(
                "prompt built",
                event="llm.prompt.built",
                pipeline_step="llm",
                message_count=len(messages),
                has_images=bool(effective_attachments),
                ocr_chars=ocr_total_chars,
            )

            # ── Phase 3: LLM streaming ────────────────────────────────────────
            llm_stream_started = perf_counter()
            first_token_seen = False
            interrupted = False
            llm_delta_count = 0

            log.info(
                "llm stream started",
                event="llm.stream.start",
                pipeline_step="llm",
                has_images=bool(effective_attachments),
            )

            async for delta in self.llm.stream(
                messages,
                config={"turn_id": turn_id, "has_images": bool(effective_attachments)},
            ):
                if await session.interruption_manager.is_cancelled(turn_id):
                    interrupted = True
                    log.info(
                        "llm stream interrupted",
                        event="llm.stream.interrupted",
                        pipeline_step="llm",
                        deltas_received=llm_delta_count,
                    )
                    break

                if not first_token_seen:
                    llm_first_token_latency = perf_counter() - llm_stream_started
                    observe_stage("llm_first_token", llm_first_token_latency)
                    first_token_seen = True
                    log.info(
                        "llm first token received",
                        event="llm.first_token",
                        pipeline_step="llm",
                        latency_ms=round(llm_first_token_latency * 1000, 1),
                    )

                llm_delta_count += 1
                session.response_text += delta
                await session.send_event("response.text.delta", {"text": delta})
                log.debug(
                    "llm delta",
                    event="llm.delta",
                    pipeline_step="llm",
                    delta_len=len(delta),
                    response_len=len(session.response_text),
                )

            if not interrupted:
                llm_total_latency = perf_counter() - llm_stream_started
                log.info(
                    "llm stream completed",
                    event="llm.stream.end",
                    pipeline_step="llm",
                    total_latency_ms=round(llm_total_latency * 1000, 1),
                    response_length=len(session.response_text),
                    delta_count=llm_delta_count,
                )

            if interrupted:
                return

            # ── Phase 4: TTS streaming ────────────────────────────────────────
            tts_text = strip_tts_noise(session.response_text)
            chunker = SentenceChunker()
            sentences: list[tuple[int, str]] = []
            for sentence in chunker.push(tts_text):
                sentences.append((len(sentences), sentence))
            for sentence in chunker.flush():
                sentences.append((len(sentences), sentence))

            log.info(
                "tts synthesis started",
                event="tts.start",
                pipeline_step="tts",
                sentence_count=len(sentences),
                tts_text_length=len(tts_text),
            )

            if sentences:
                tts_generation_started = perf_counter()
                tts_chunk_count = 0

                async def sentence_stream() -> AsyncIterator[tuple[int, str]]:
                    for item in sentences:
                        yield item

                first_audio_sent = False
                async for audio_chunk in self.tts.stream_synthesize(
                    sentence_stream(),
                    voice="default",
                    format="wav",
                    job_id=turn_id,
                ):
                    if await session.interruption_manager.is_cancelled(turn_id):
                        log.info(
                            "tts synthesis interrupted",
                            event="tts.interrupted",
                            pipeline_step="tts",
                            chunks_sent=tts_chunk_count,
                        )
                        return

                    if not first_audio_sent:
                        tts_first_audio_latency = perf_counter() - tts_generation_started
                        time_to_first_audio = perf_counter() - turn_started
                        observe_stage("tts_first_audio", tts_first_audio_latency)
                        observe_stage("time_to_first_audio", time_to_first_audio)
                        log.info(
                            "tts first audio chunk ready",
                            event="tts.first_audio",
                            pipeline_step="tts",
                            tts_latency_ms=round(tts_first_audio_latency * 1000, 1),
                            time_to_first_audio_ms=round(time_to_first_audio * 1000, 1),
                        )

                    session.state = transition_state(session.state, "tts_started")
                    await session.send_tts_chunk(
                        chunk_index=audio_chunk.chunk_index,
                        text=audio_chunk.text,
                        audio_bytes=audio_chunk.audio_bytes,
                    )
                    tts_chunk_count += 1
                    log.debug(
                        "tts chunk sent",
                        event="tts.chunk.sent",
                        pipeline_step="tts",
                        chunk_index=audio_chunk.chunk_index,
                        audio_bytes=len(audio_chunk.audio_bytes),
                        text_preview=audio_chunk.text[:40],
                    )

                    if not first_audio_sent:
                        session.state = transition_state(session.state, "playback_started")
                        first_audio_sent = True

                log.info(
                    "tts synthesis completed",
                    event="tts.end",
                    pipeline_step="tts",
                    total_chunks=tts_chunk_count,
                    total_latency_ms=round((perf_counter() - tts_generation_started) * 1000, 1),
                )

            if await session.interruption_manager.is_cancelled(turn_id):
                log.info(
                    "turn interrupted before finalisation",
                    event="turn.interrupted.pre_final",
                )
                return

            # ── Finalise ──────────────────────────────────────────────────────
            session.history.append({"role": "assistant", "content": session.response_text})
            await session.send_event("response.text.final", {"text": session.response_text})
            session.state = SessionState.LISTENING

            total_turn_latency = perf_counter() - turn_started
            log.info(
                "turn completed",
                event="turn.completed",
                turn_type=turn_type,
                total_latency_ms=round(total_turn_latency * 1000, 1),
                stt_latency_ms=round((stt_latency or 0.0) * 1000, 1),
                ocr_latency_ms=round((ocr_latency or 0.0) * 1000, 1),
                ocr_total_chars=ocr_total_chars,
                llm_first_token_ms=round((llm_first_token_latency or 0.0) * 1000, 1),
                tts_first_audio_ms=round((tts_first_audio_latency or 0.0) * 1000, 1),
                time_to_first_audio_ms=round((time_to_first_audio or 0.0) * 1000, 1),
                transcript_length=len(user_text),
                response_length=len(session.response_text),
                attachment_count=len(attachments),
                history_turns=len(session.history),
            )

        except asyncio.CancelledError:
            await self.cancel_turn(turn_id)
            log.info("turn cancelled", event="turn.cancelled")
            raise

        except Exception as error:
            provider_errors.labels(provider="orchestrator").inc()
            session.state = transition_state(session.state, "failed")
            log.exception(
                "turn failed",
                event="turn.failed",
                error_type=type(error).__name__,
            )
            message = str(error).strip() or "The current turn failed before playback completed."
            await session.send_event("error", {"code": "TURN_FAILED", "message": message})
            session.state = SessionState.LISTENING

        finally:
            await self.cancel_turn(turn_id)
            await session.interruption_manager.clear(turn_id)
            session.current_text_input = None
            session.current_attachments = []
            session.current_task = None
            log.debug("turn cleanup complete", event="turn.cleanup")

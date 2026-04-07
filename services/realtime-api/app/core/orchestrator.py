from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Callable

from app.core.metrics import observe_stage, provider_errors
from app.core.state_machine import SessionState, transition_state
from app.core.text import SentenceChunker, build_prompt_messages
from app.providers.base import LLMProvider, STTProvider, TTSProvider

logger = logging.getLogger(__name__)


class TurnOrchestrator:
    def __init__(
        self,
        stt_factory: Callable[[], STTProvider],
        llm: LLMProvider,
        tts: TTSProvider,
        system_prompt: str,
    ) -> None:
        self.stt_factory = stt_factory
        self.llm = llm
        self.tts = tts
        self.system_prompt = system_prompt

    async def cancel_turn(self, turn_id: str | None) -> None:
        if turn_id is None:
            return
        await asyncio.gather(
            self.llm.cancel(turn_id),
            self.tts.cancel(turn_id),
            return_exceptions=True,
        )

    async def process_turn(self, session) -> None:
        turn_id = session.current_turn_id
        if turn_id is None:
            return

        turn_started = session.turn_started_perf or perf_counter()
        user_text = ""
        attachments = list(session.current_attachments)
        llm_first_token_latency: float | None = None
        tts_first_audio_latency: float | None = None
        time_to_first_audio: float | None = None
        tts_task: asyncio.Task[None] | None = None
        sentence_queue: asyncio.Queue[tuple[int, str] | None] = asyncio.Queue()
        tts_generation_started: float | None = None
        stt_latency: float | None = None

        try:
            if session.current_text_input is None:
                stt = self.stt_factory()
                await stt.start_session({"sample_rate": 16000, "language": "en"})

                audio_chunk = bytes(session.current_audio)
                if audio_chunk:
                    await stt.append_audio(audio_chunk)

                stt_started = perf_counter()
                transcript = await stt.finalize_utterance()
                stt_latency = perf_counter() - stt_started
                observe_stage("stt_completed", stt_latency)
                user_text = transcript.text

                session.state = transition_state(session.state, "transcript_finalized")
                session.history.append({"role": "user", "content": user_text})
                await session.send_event("transcript.final", {"text": user_text, "isFinal": True})
            else:
                user_text = session.current_text_input
                session.history.append({"role": "user", "content": user_text})

            await session.send_event("llm.thinking", {"state": "thinking"})

            messages = build_prompt_messages(self.system_prompt, session.history[:-1], user_text, attachments)
            chunker = SentenceChunker()

            async def sentence_stream() -> AsyncIterator[tuple[int, str]]:
                while True:
                    item = await sentence_queue.get()
                    if item is None:
                        break
                    yield item

            async def tts_worker() -> None:
                nonlocal tts_first_audio_latency, time_to_first_audio
                first_audio_sent = False
                async for audio_chunk in self.tts.stream_synthesize(
                    sentence_stream(),
                    voice="default",
                    format="wav",
                    job_id=turn_id,
                ):
                    if await session.interruption_manager.is_cancelled(turn_id):
                        return

                    if not first_audio_sent:
                        tts_first_audio_latency = perf_counter() - (tts_generation_started or llm_stream_started)
                        time_to_first_audio = perf_counter() - turn_started
                        observe_stage("tts_first_audio", tts_first_audio_latency)
                        observe_stage("time_to_first_audio", time_to_first_audio)
                    session.state = transition_state(session.state, "tts_started")
                    await session.send_tts_chunk(
                        chunk_index=audio_chunk.chunk_index,
                        text=audio_chunk.text,
                        audio_bytes=audio_chunk.audio_bytes,
                    )
                    if not first_audio_sent:
                        session.state = transition_state(session.state, "playback_started")
                        first_audio_sent = True

            tts_task = asyncio.create_task(tts_worker())
            chunk_index = 0
            llm_stream_started = perf_counter()
            first_token_seen = False
            interrupted = False

            async for delta in self.llm.stream(messages, config={"turn_id": turn_id, "has_images": bool(attachments)}):
                if await session.interruption_manager.is_cancelled(turn_id):
                    interrupted = True
                    break
                if not first_token_seen:
                    llm_first_token_latency = perf_counter() - llm_stream_started
                    observe_stage("llm_first_token", llm_first_token_latency)
                    first_token_seen = True
                session.response_text += delta
                await session.send_event("response.text.delta", {"text": delta})
                for sentence in chunker.push(delta):
                    if tts_generation_started is None:
                        tts_generation_started = perf_counter()
                    await sentence_queue.put((chunk_index, sentence))
                    chunk_index += 1

            if interrupted:
                await sentence_queue.put(None)
                return

            for sentence in chunker.flush():
                if tts_generation_started is None:
                    tts_generation_started = perf_counter()
                await sentence_queue.put((chunk_index, sentence))
                chunk_index += 1
            await sentence_queue.put(None)
            await tts_task

            if await session.interruption_manager.is_cancelled(turn_id):
                return

            session.history.append({"role": "assistant", "content": session.response_text})
            await session.send_event("response.text.final", {"text": session.response_text})
            session.state = SessionState.LISTENING
            logger.info(
                "turn completed",
                extra={
                    "event": "turn.completed",
                    "session_id": session.session_id,
                    "turn_id": turn_id,
                    "stt_latency_s": round(stt_latency or 0.0, 3),
                    "llm_first_token_latency_s": round(llm_first_token_latency or 0.0, 3),
                    "tts_first_audio_latency_s": round(tts_first_audio_latency or 0.0, 3),
                    "time_to_first_audio_s": round(time_to_first_audio or 0.0, 3),
                    "transcript_length": len(user_text),
                    "response_length": len(session.response_text),
                    "attachment_count": len(attachments),
                },
            )
        except asyncio.CancelledError:
            await self.cancel_turn(turn_id)
            logger.info(
                "turn cancelled",
                extra={"event": "turn.cancelled", "session_id": session.session_id, "turn_id": turn_id},
            )
            raise
        except Exception as error:
            provider_errors.labels(provider="orchestrator").inc()
            session.state = transition_state(session.state, "failed")
            logger.exception(
                "turn failed",
                extra={"event": "turn.failed", "session_id": session.session_id, "turn_id": turn_id},
            )
            message = str(error).strip() or "The current turn failed before playback completed."
            await session.send_event(
                "error",
                {
                    "code": "TURN_FAILED",
                    "message": message,
                },
            )
            session.state = SessionState.LISTENING
        finally:
            if tts_task is not None and not tts_task.done():
                tts_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await tts_task
            await self.cancel_turn(turn_id)
            await session.interruption_manager.clear(turn_id)
            session.current_text_input = None
            session.current_attachments = []
            session.current_task = None

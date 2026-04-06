from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Callable

from app.core.metrics import provider_errors, stage_latency
from app.core.state_machine import SessionState
from app.core.state_machine import transition_state
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

    async def process_turn(self, session) -> None:
        turn_id = session.current_turn_id
        if turn_id is None:
            return

        try:
            stt = self.stt_factory()
            await stt.start_session({"sample_rate": 16000, "language": "en"})
            for audio_chunk in [bytes(session.current_audio)]:
                with stage_latency.labels(stage="audio_received").time():
                    await stt.append_audio(audio_chunk)

            with stage_latency.labels(stage="stt_completed").time():
                transcript = await stt.finalize_utterance()

            session.state = transition_state(session.state, "transcript_finalized")
            session.history.append({"role": "user", "content": transcript.text})
            await session.send_event("transcript.final", {"text": transcript.text, "isFinal": True})
            await session.send_event("llm.thinking", {"state": "thinking"})

            with stage_latency.labels(stage="llm_started").time():
                messages = build_prompt_messages(self.system_prompt, session.history[:-1], transcript.text)

            chunker = SentenceChunker()
            sentence_queue: asyncio.Queue[tuple[int, str] | None] = asyncio.Queue()

            async def sentence_stream() -> AsyncIterator[tuple[int, str]]:
                while True:
                    item = await sentence_queue.get()
                    if item is None:
                        break
                    yield item

            async def tts_worker() -> None:
                first_audio_sent = False
                async for audio_chunk in self.tts.stream_synthesize(sentence_stream(), voice="default", format="wav"):
                    if await session.interruption_manager.is_cancelled(turn_id):
                        return
                    session.state = transition_state(session.state, "tts_started")
                    with stage_latency.labels(stage="tts_first_audio").time():
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

            async for delta in self.llm.stream(messages, config={"turn_id": turn_id}):
                if await session.interruption_manager.is_cancelled(turn_id):
                    tts_task.cancel()
                    return
                session.response_text += delta
                await session.send_event("response.text.delta", {"text": delta})
                for sentence in chunker.push(delta):
                    await sentence_queue.put((chunk_index, sentence))
                    chunk_index += 1

            for sentence in chunker.flush():
                await sentence_queue.put((chunk_index, sentence))
                chunk_index += 1
            await sentence_queue.put(None)
            await tts_task

            session.history.append({"role": "assistant", "content": session.response_text})
            await session.send_event("response.text.final", {"text": session.response_text})
            session.state = SessionState.LISTENING
            await session.interruption_manager.clear(turn_id)
        except asyncio.CancelledError:
            logger.info(
                "turn cancelled",
                extra={"event": "turn.cancelled", "session_id": session.session_id, "turn_id": turn_id},
            )
            raise
        except Exception:
            provider_errors.labels(provider="orchestrator").inc()
            session.state = transition_state(session.state, "failed")
            logger.exception(
                "turn failed",
                extra={"event": "turn.failed", "session_id": session.session_id, "turn_id": turn_id},
            )
            await session.send_event(
                "error",
                {"code": "TURN_FAILED", "message": "The current turn failed before playback completed."},
            )

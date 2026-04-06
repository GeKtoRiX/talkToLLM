from __future__ import annotations

from app.providers.base import STTProvider, TranscriptResult


class MockWhisperProvider(STTProvider):
    def __init__(self) -> None:
        self._buffer = bytearray()

    async def start_session(self, config: dict[str, str | int]) -> None:
        self._buffer.clear()

    async def append_audio(self, chunk: bytes) -> None:
        self._buffer.extend(chunk)

    async def finalize_utterance(self) -> TranscriptResult:
        duration_seconds = len(self._buffer) / (16000 * 2)
        duration_seconds = max(duration_seconds, 0.1)
        text = (
            f"Mock transcript from approximately {duration_seconds:.1f} seconds of English audio. "
            "Replace the provider to connect real Whisper transcription."
        )
        self._buffer.clear()
        return TranscriptResult(text=text, is_final=True)


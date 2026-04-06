from __future__ import annotations

import asyncio
import io
import math
import wave
from collections.abc import AsyncIterator

from app.providers.base import TTSProvider, TtsChunk


def build_tone_wav(duration_seconds: float, sample_rate: int = 16000, frequency: float = 440.0) -> bytes:
    frame_count = int(duration_seconds * sample_rate)
    amplitude = 18000
    buffer = io.BytesIO()

    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            value = int(amplitude * math.sin(2 * math.pi * frequency * (index / sample_rate)))
            frames.extend(value.to_bytes(2, byteorder="little", signed=True))
        wav_file.writeframes(bytes(frames))

    return buffer.getvalue()


class MockKokoroProvider(TTSProvider):
    async def stream_synthesize(
        self,
        text_stream: AsyncIterator[tuple[int, str]],
        voice: str,
        format: str,
    ) -> AsyncIterator[TtsChunk]:
        async for chunk_index, text in text_stream:
            await asyncio.sleep(0.03)
            duration_seconds = min(max(len(text) / 35, 0.35), 1.8)
            frequency = 380 + (chunk_index * 30)
            audio_bytes = build_tone_wav(duration_seconds=duration_seconds, frequency=frequency)
            yield TtsChunk(audio_bytes=audio_bytes, mime_type="audio/wav", chunk_index=chunk_index, text=text)

    async def cancel(self, job_id: str) -> None:
        return None


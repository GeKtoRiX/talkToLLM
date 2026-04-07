from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass(slots=True)
class TranscriptResult:
    text: str
    is_final: bool = True


@dataclass(slots=True)
class TtsChunk:
    audio_bytes: bytes
    mime_type: str
    chunk_index: int
    text: str


class STTProvider(ABC):
    @abstractmethod
    async def start_session(self, config: dict[str, str | int]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def append_audio(self, chunk: bytes) -> None:
        raise NotImplementedError

    @abstractmethod
    async def finalize_utterance(self) -> TranscriptResult:
        raise NotImplementedError


class LLMProvider(ABC):
    @abstractmethod
    async def stream(self, messages: list[dict[str, str]], config: dict[str, str | int]) -> AsyncIterator[str]:
        raise NotImplementedError

    @abstractmethod
    async def cancel(self, request_id: str) -> None:
        raise NotImplementedError


class TTSProvider(ABC):
    @abstractmethod
    async def stream_synthesize(
        self,
        text_stream: AsyncIterator[tuple[int, str]],
        voice: str,
        format: str,
        job_id: str | None = None,
    ) -> AsyncIterator[TtsChunk]:
        raise NotImplementedError

    @abstractmethod
    async def cancel(self, job_id: str) -> None:
        raise NotImplementedError

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any


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


@dataclass(slots=True)
class ChatTextPart:
    text: str


@dataclass(slots=True)
class ChatImagePart:
    mime_type: str
    data_base64: str

    @property
    def data_url(self) -> str:
        return f"data:{self.mime_type};base64,{self.data_base64}"


ChatContentPart = ChatTextPart | ChatImagePart


@dataclass(slots=True)
class ChatMessage:
    role: str
    content_parts: list[ChatContentPart]


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

    def is_warm(self) -> bool:
        """Return True if the model is already loaded into memory."""
        return True

    async def warm_up(self) -> None:
        """Pre-load the model so the first real transcription is not delayed."""
        return


class LLMProvider(ABC):
    @abstractmethod
    async def stream(self, messages: list[ChatMessage], config: dict[str, Any]) -> AsyncIterator[str]:
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

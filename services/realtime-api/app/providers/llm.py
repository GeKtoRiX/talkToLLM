from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.core.text import stream_words
from app.providers.base import LLMProvider


class MockLLMProvider(LLMProvider):
    async def stream(self, messages: list[dict[str, str]], config: dict[str, str | int]) -> AsyncIterator[str]:
        user_text = messages[-1]["content"]
        response = (
            "This is the prototype voice loop responding in concise English. "
            f"I heard: {user_text} "
            "The orchestration path from STT to LLM to TTS is active."
        )
        for token in stream_words(response):
            await asyncio.sleep(0.02)
            yield token

    async def cancel(self, request_id: str) -> None:
        return None


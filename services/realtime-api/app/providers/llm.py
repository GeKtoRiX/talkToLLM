from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from typing import Any

from app.core.config import AppSettings
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


class LMStudioLLMProvider(LLMProvider):
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._cancellations: dict[str, threading.Event] = {}

    async def stream(self, messages: list[dict[str, str]], config: dict[str, str | int]) -> AsyncIterator[str]:
        request_id = str(config.get("turn_id", "default"))
        cancellation = threading.Event()
        self._cancellations[request_id] = cancellation
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def run_stream() -> None:
            stream = None
            try:
                try:
                    from openai import OpenAI
                except ImportError as error:
                    raise RuntimeError(
                        "openai is not installed. Install the realtime provider dependencies first."
                    ) from error

                client = OpenAI(
                    api_key=self.settings.lmstudio_api_key,
                    base_url=self.settings.lmstudio_base_url,
                    timeout=self.settings.llm_timeout_seconds,
                )
                stream = client.chat.completions.create(
                    model=self.settings.llm_model,
                    messages=messages,
                    temperature=self.settings.llm_temperature,
                    stream=True,
                )

                for chunk in stream:
                    if cancellation.is_set():
                        break
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta.content or ""
                    if delta:
                        loop.call_soon_threadsafe(queue.put_nowait, ("delta", delta))
            except Exception as error:
                loop.call_soon_threadsafe(queue.put_nowait, ("error", error))
            finally:
                if stream is not None and hasattr(stream, "close"):
                    try:
                        stream.close()
                    except Exception:
                        pass
                loop.call_soon_threadsafe(queue.put_nowait, ("done", None))

        thread = threading.Thread(target=run_stream, daemon=True, name=f"lmstudio-stream-{request_id}")
        thread.start()

        try:
            while True:
                event_type, payload = await queue.get()
                if event_type == "delta":
                    yield str(payload)
                elif event_type == "error":
                    raise payload
                elif event_type == "done":
                    break
        finally:
            cancellation.set()
            self._cancellations.pop(request_id, None)

    async def cancel(self, request_id: str) -> None:
        cancellation = self._cancellations.get(request_id)
        if cancellation is not None:
            cancellation.set()

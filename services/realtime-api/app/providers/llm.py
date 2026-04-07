from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from typing import Any

from app.core.config import AppSettings
from app.core.text import stream_words
from app.providers.base import ChatImagePart, ChatMessage, ChatTextPart, LLMProvider


class MockLLMProvider(LLMProvider):
    async def stream(self, messages: list[ChatMessage], config: dict[str, Any]) -> AsyncIterator[str]:
        latest_message = messages[-1]
        user_text = "".join(part.text for part in latest_message.content_parts if isinstance(part, ChatTextPart))
        has_images = any(isinstance(part, ChatImagePart) for part in latest_message.content_parts)
        response = (
            "This is the prototype voice loop responding in concise English. "
            f"I heard: {user_text} "
            "The orchestration path from STT to LLM to TTS is active."
        )
        if has_images:
            response += " I also received a screenshot for the task."
        for token in stream_words(response):
            await asyncio.sleep(0.02)
            yield token

    async def cancel(self, request_id: str) -> None:
        return None


class LMStudioLLMProvider(LLMProvider):
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._cancellations: dict[str, threading.Event] = {}

    async def stream(self, messages: list[ChatMessage], config: dict[str, Any]) -> AsyncIterator[str]:
        request_id = str(config.get("turn_id", "default"))
        has_images = bool(config.get("has_images"))
        selected_model = self._select_model(has_images)
        openai_messages = self._build_openai_messages(messages)
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
                    model=selected_model,
                    messages=openai_messages,
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
                if has_images:
                    error = RuntimeError(
                        "Screenshot analysis failed in LM Studio. "
                        f"Model '{selected_model}' must support vision inputs. "
                        f"Original error: {error}"
                    )
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

    def _select_model(self, has_images: bool) -> str:
        if has_images and self.settings.llm_vision_model:
            return self.settings.llm_vision_model
        return self.settings.llm_model

    @staticmethod
    def _build_openai_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
        serialized_messages: list[dict[str, Any]] = []

        for message in messages:
            content_parts: list[dict[str, Any]] = []
            text_only = True

            for part in message.content_parts:
                if isinstance(part, ChatTextPart):
                    content_parts.append({"type": "text", "text": part.text})
                    continue

                if isinstance(part, ChatImagePart):
                    text_only = False
                    content_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": part.data_url},
                        }
                    )

            if text_only and len(content_parts) == 1:
                content: str | list[dict[str, Any]] = content_parts[0]["text"]
            else:
                content = content_parts

            serialized_messages.append({"role": message.role, "content": content})

        return serialized_messages

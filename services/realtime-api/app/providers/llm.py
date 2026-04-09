from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse, urlunparse

from app.core.config import AppSettings
from app.providers.base import ChatImagePart, ChatMessage, ChatTextPart, LLMProvider

logger = logging.getLogger(__name__)


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
        words = response.split(" ")
        for index, word in enumerate(words):
            suffix = " " if index < len(words) - 1 else ""
            await asyncio.sleep(0.02)
            yield word + suffix

    async def cancel(self, request_id: str) -> None:
        return None


class LMStudioLLMProvider(LLMProvider):
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._cancellations: dict[str, threading.Event] = {}
        # Cache OpenAI clients by api_base so connection pools are reused
        self._client_cache: dict[str, Any] = {}

    def _get_api_base(self) -> str:
        """Resolve the correct base URL, switching to /api/v0 for reasoning_effort."""
        if not self.settings.lmstudio_reasoning_effort:
            return self.settings.lmstudio_base_url
        # LM Studio extended endpoint required for reasoning_effort parameter.
        # Swap the trailing /v1 path segment for /api/v0.
        parsed = urlparse(self.settings.lmstudio_base_url)
        path = parsed.path.rstrip("/")
        new_path = path[: -len("/v1")] + "/api/v0" if path.endswith("/v1") else "/api/v0"
        return urlunparse(parsed._replace(path=new_path))

    def _get_client(self, api_base: str) -> Any:
        """Return a cached OpenAI client for the given base URL."""
        if api_base not in self._client_cache:
            try:
                from openai import OpenAI
            except ImportError as error:
                raise RuntimeError(
                    "openai is not installed. Install the realtime provider dependencies first."
                ) from error
            self._client_cache[api_base] = OpenAI(
                api_key=self.settings.lmstudio_api_key,
                base_url=api_base,
                timeout=self.settings.llm_timeout_seconds,
            )
            logger.info(
                "lmstudio client created",
                extra={
                    "event": "llm.client.created",
                    "api_base": api_base,
                    "timeout_s": self.settings.llm_timeout_seconds,
                },
            )
        return self._client_cache[api_base]

    async def stream(self, messages: list[ChatMessage], config: dict[str, Any]) -> AsyncIterator[str]:
        request_id = str(config.get("turn_id", "default"))
        has_images = bool(config.get("has_images"))
        selected_model = self._select_model(has_images)
        api_base = self._get_api_base()
        openai_messages = self._build_openai_messages(messages)
        cancellation = threading.Event()
        self._cancellations[request_id] = cancellation
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        reasoning_effort = self.settings.lmstudio_reasoning_effort

        logger.info(
            "lmstudio stream request",
            extra={
                "event": "llm.request.start",
                "turn_id": request_id,
                "model": selected_model,
                "has_images": has_images,
                "message_count": len(openai_messages),
                "api_base": api_base,
                "reasoning_effort": reasoning_effort,
            },
        )

        def run_stream() -> None:
            stream = None
            first_token_logged = False
            delta_count = 0
            try:
                client = self._get_client(api_base)
                extra = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
                stream = client.chat.completions.create(
                    model=selected_model,
                    messages=openai_messages,
                    temperature=self.settings.llm_temperature,
                    stream=True,
                    extra_body=extra,
                )

                for chunk in stream:
                    if cancellation.is_set():
                        logger.debug(
                            "lmstudio stream cancelled",
                            extra={"event": "llm.request.cancelled", "turn_id": request_id, "deltas": delta_count},
                        )
                        break
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta.content or ""
                    if delta:
                        if not first_token_logged:
                            logger.debug(
                                "lmstudio first token",
                                extra={"event": "llm.first_token.thread", "turn_id": request_id},
                            )
                            first_token_logged = True
                        delta_count += 1
                        loop.call_soon_threadsafe(queue.put_nowait, ("delta", delta))

                logger.debug(
                    "lmstudio stream finished",
                    extra={"event": "llm.request.end", "turn_id": request_id, "delta_count": delta_count},
                )
            except Exception as error:
                if has_images:
                    error = RuntimeError(
                        "Screenshot analysis failed in LM Studio. "
                        f"Model '{selected_model}' must support vision inputs. "
                        f"Original error: {error}"
                    )
                logger.error(
                    "lmstudio stream error",
                    extra={"event": "llm.request.error", "turn_id": request_id, "error": str(error)},
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
            logger.debug(
                "lmstudio request cancelled",
                extra={"event": "llm.cancel", "turn_id": request_id},
            )

    def _select_model(self, has_images: bool) -> str:
        # When a vision model is configured it becomes the sole active model
        # (one LM Studio instance can only serve one model at a time).
        # It handles both image turns (natively) and text turns (as fallback).
        if self.settings.llm_vision_model:
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

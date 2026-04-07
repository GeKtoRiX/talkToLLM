from __future__ import annotations

from typing import Callable

from app.core.config import AppSettings
from app.providers.base import LLMProvider, STTProvider, TTSProvider
from app.providers.llm import LMStudioLLMProvider, MockLLMProvider
from app.providers.stt import FasterWhisperSTTProvider, MockWhisperProvider, WhisperRocmSTTProvider
from app.providers.tts import KokoroTTSProvider, MockKokoroProvider


def create_stt_factory(settings: AppSettings) -> Callable[[], STTProvider]:
    if settings.stt_provider == "whisper_rocm":
        return lambda: WhisperRocmSTTProvider(settings)
    if settings.stt_provider == "faster_whisper":
        return lambda: FasterWhisperSTTProvider(settings)
    return MockWhisperProvider


def create_llm_provider(settings: AppSettings) -> LLMProvider:
    if settings.llm_provider == "lmstudio":
        return LMStudioLLMProvider(settings)
    return MockLLMProvider()


def create_tts_provider(settings: AppSettings) -> TTSProvider:
    if settings.tts_provider == "kokoro":
        return KokoroTTSProvider(settings)
    return MockKokoroProvider()

"""Unit tests for provider factory functions."""
from __future__ import annotations

from app.core.config import AppSettings
from app.providers.factory import create_llm_provider, create_stt_factory, create_tts_provider
from app.providers.llm import MockLLMProvider
from app.providers.stt import MockWhisperProvider
from app.providers.tts import MockKokoroProvider


# ── STT factory ───────────────────────────────────────────────────────────────


def test_stt_factory_mock_provider_returns_mock():
    settings = AppSettings(stt_provider="mock")
    factory = create_stt_factory(settings)
    assert isinstance(factory(), MockWhisperProvider)


def test_stt_factory_unknown_provider_falls_back_to_mock():
    settings = AppSettings(stt_provider="does_not_exist")
    factory = create_stt_factory(settings)
    assert isinstance(factory(), MockWhisperProvider)


def test_stt_factory_returns_callable():
    settings = AppSettings(stt_provider="mock")
    factory = create_stt_factory(settings)
    assert callable(factory)


def test_stt_factory_creates_new_instance_each_call():
    settings = AppSettings(stt_provider="mock")
    factory = create_stt_factory(settings)
    assert factory() is not factory()


# ── LLM factory ───────────────────────────────────────────────────────────────


def test_llm_mock_provider():
    settings = AppSettings(llm_provider="mock")
    provider = create_llm_provider(settings)
    assert isinstance(provider, MockLLMProvider)


def test_llm_unknown_provider_falls_back_to_mock():
    settings = AppSettings(llm_provider="unknown_llm")
    provider = create_llm_provider(settings)
    assert isinstance(provider, MockLLMProvider)


# ── TTS factory ───────────────────────────────────────────────────────────────


def test_tts_mock_provider():
    settings = AppSettings(tts_provider="mock")
    provider = create_tts_provider(settings)
    assert isinstance(provider, MockKokoroProvider)


def test_tts_unknown_provider_falls_back_to_mock():
    settings = AppSettings(tts_provider="unknown_tts")
    provider = create_tts_provider(settings)
    assert isinstance(provider, MockKokoroProvider)

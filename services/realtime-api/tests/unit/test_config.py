"""Unit tests for AppSettings configuration."""
from __future__ import annotations

import pytest

from app.core.config import AppSettings


def test_default_providers_are_mock():
    # Bypass the project .env so we see the class-level defaults
    s = AppSettings(_env_file=None)
    assert s.llm_provider == "mock"
    assert s.stt_provider == "mock"
    assert s.tts_provider == "mock"


def test_default_app_env():
    s = AppSettings(_env_file=None)
    assert s.app_env == "development"


def test_screenshot_mime_types_parsed_to_set():
    s = AppSettings(screenshot_allowed_mime_types="image/png,image/jpeg,image/webp")
    assert s.screenshot_allowed_mime_type_set == {"image/png", "image/jpeg", "image/webp"}


def test_screenshot_mime_types_single_value():
    s = AppSettings(screenshot_allowed_mime_types="image/png")
    assert s.screenshot_allowed_mime_type_set == {"image/png"}


def test_screenshot_mime_types_trims_whitespace():
    s = AppSettings(screenshot_allowed_mime_types="image/png , image/jpeg")
    assert "image/png" in s.screenshot_allowed_mime_type_set
    assert "image/jpeg" in s.screenshot_allowed_mime_type_set


def test_resolve_path_relative_is_absolute():
    s = AppSettings()
    resolved = s.resolve_path("models/whisper")
    assert resolved.is_absolute()


def test_resolve_path_relative_ends_with_given_suffix():
    s = AppSettings()
    resolved = s.resolve_path("models/whisper")
    assert str(resolved).endswith("models/whisper")


def test_resolve_path_absolute_is_returned_unchanged():
    s = AppSettings()
    resolved = s.resolve_path("/tmp/test_model")
    assert str(resolved) == "/tmp/test_model"


def test_project_root_is_absolute():
    s = AppSettings()
    assert s.project_root.is_absolute()


def test_llm_defaults():
    s = AppSettings()
    assert s.llm_model == "gemma-4-e4b-it"
    assert s.llm_timeout_seconds == 45.0
    assert 0 < s.llm_temperature <= 1.0


def test_stt_defaults():
    s = AppSettings()
    assert s.stt_model_size == "base.en"
    assert s.stt_beam_size == 1


def test_kokoro_defaults():
    s = AppSettings()
    assert s.kokoro_voice == "af_heart"
    assert s.kokoro_device == "cpu"


def test_ocr_defaults():
    s = AppSettings(_env_file=None)
    assert s.ocr_backend == "tesseract"
    assert s.ocr_model_root == "models/ocr"
    assert s.ocr_local_files_only is False


def test_ocr_backend_override_via_env(monkeypatch):
    monkeypatch.setenv("OCR_BACKEND", "tesseract")
    s = AppSettings(_env_file=None)
    assert s.ocr_backend == "tesseract"

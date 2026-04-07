"""Shared fixtures for the realtime-api test suite."""
from __future__ import annotations

import base64

import pytest

from app.core.config import AppSettings
from app.main import create_app


@pytest.fixture
def mock_settings():
    """AppSettings wired to all-mock providers."""
    return AppSettings(llm_provider="mock", stt_provider="mock", tts_provider="mock")


@pytest.fixture
def mock_app(mock_settings):
    """FastAPI app wired to all-mock providers."""
    return create_app(mock_settings)


def sample_attachment(mime_type: str = "image/png", byte_count: int = 8) -> dict:
    """Helper: build a minimal valid attachment payload for WebSocket tests."""
    return {
        "mimeType": mime_type,
        "dataBase64": base64.b64encode(b"x" * byte_count).decode("ascii"),
        "width": 800,
        "height": 600,
        "name": "worksheet.png",
    }

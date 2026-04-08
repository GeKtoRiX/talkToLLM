"""Unit tests for the multi-backend OCR module."""
from __future__ import annotations

import base64
import io
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import AppSettings
from app.core.ocr import _preprocess_image, extract_text_from_image


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_b64_png(w: int = 10, h: int = 10, mode: str = "RGB") -> str:
    """Return a base64-encoded white PNG of the given size and mode."""
    from PIL import Image

    colour: tuple[int, ...] = (255, 255, 255) if mode == "RGB" else (255, 255, 255, 255)
    img = Image.new(mode, (w, h), color=colour)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _settings(**overrides) -> AppSettings:
    return AppSettings(_env_file=None, **overrides)


# ---------------------------------------------------------------------------
# _preprocess_image
# ---------------------------------------------------------------------------

def test_preprocess_rgba_to_rgb():
    from PIL import Image

    rgba = Image.new("RGBA", (100, 100), color=(10, 20, 30, 128))
    result = _preprocess_image(rgba)
    assert result.mode == "RGB"


def test_preprocess_upscales_small_image():
    from PIL import Image

    small = Image.new("RGB", (200, 300), color=(255, 255, 255))
    result = _preprocess_image(small)
    assert min(result.size) >= 800


def test_preprocess_does_not_downscale_large_image():
    from PIL import Image

    large = Image.new("RGB", (2000, 3000), color=(255, 255, 255))
    result = _preprocess_image(large)
    # Should not shrink — only upscale rule applies
    assert result.size[0] >= 2000
    assert result.size[1] >= 3000


# ---------------------------------------------------------------------------
# extract_text_from_image — tesseract backend
# ---------------------------------------------------------------------------

def test_tesseract_backend_used():
    """ocr_backend='tesseract' must call pytesseract and skip GOT-OCR2."""
    s = _settings(ocr_backend="tesseract")
    b64 = _make_b64_png()

    with (
        patch("app.core.ocr._run_tesseract", return_value="hello tesseract") as mock_tess,
        patch("app.core.ocr._run_got_ocr2") as mock_got,
    ):
        result = extract_text_from_image(b64, settings=s)

    assert result == "hello tesseract"
    mock_tess.assert_called_once()
    mock_got.assert_not_called()


# ---------------------------------------------------------------------------
# extract_text_from_image — got_ocr2 backend (explicit)
# ---------------------------------------------------------------------------

def test_got_ocr2_backend_used():
    """ocr_backend='got_ocr2' must call GOT-OCR2 and skip Tesseract."""
    s = _settings(ocr_backend="got_ocr2")
    b64 = _make_b64_png()

    with (
        patch("app.core.ocr._run_got_ocr2", return_value="# Business Card\nWilliam Brown\nManager") as mock_got,
        patch("app.core.ocr._run_tesseract") as mock_tess,
    ):
        result = extract_text_from_image(b64, settings=s)

    assert "William Brown" in result
    mock_got.assert_called_once()
    mock_tess.assert_not_called()


def test_got_ocr2_explicit_does_not_fallback():
    """ocr_backend='got_ocr2' must propagate exceptions — no silent fallback."""
    s = _settings(ocr_backend="got_ocr2")
    b64 = _make_b64_png()

    with (
        patch("app.core.ocr._run_got_ocr2", side_effect=RuntimeError("GPU OOM")),
        patch("app.core.ocr._run_tesseract", return_value="fallback"),
    ):
        with pytest.raises(RuntimeError, match="GPU OOM"):
            extract_text_from_image(b64, settings=s)


# ---------------------------------------------------------------------------
# extract_text_from_image — auto backend (GOT-OCR2 with Tesseract fallback)
# ---------------------------------------------------------------------------

def test_auto_falls_back_on_import_error():
    """auto mode must transparently fall back to Tesseract if torch/transformers absent."""
    s = _settings(ocr_backend="auto")
    b64 = _make_b64_png()

    with (
        patch("app.core.ocr._run_got_ocr2", side_effect=ImportError("torch not found")),
        patch("app.core.ocr._run_tesseract", return_value="fallback text") as mock_tess,
    ):
        result = extract_text_from_image(b64, settings=s)

    assert result == "fallback text"
    mock_tess.assert_called_once()


def test_auto_falls_back_on_runtime_error():
    """auto mode must fall back to Tesseract on RuntimeError (e.g. GPU OOM)."""
    s = _settings(ocr_backend="auto")
    b64 = _make_b64_png()

    with (
        patch("app.core.ocr._run_got_ocr2", side_effect=RuntimeError("CUDA error")),
        patch("app.core.ocr._run_tesseract", return_value="fallback text") as mock_tess,
    ):
        result = extract_text_from_image(b64, settings=s)

    assert result == "fallback text"
    mock_tess.assert_called_once()


def test_auto_uses_got_ocr2_when_available():
    """auto mode must prefer GOT-OCR2 when it succeeds."""
    s = _settings(ocr_backend="auto")
    b64 = _make_b64_png()

    with (
        patch("app.core.ocr._run_got_ocr2", return_value="neural output") as mock_got,
        patch("app.core.ocr._run_tesseract") as mock_tess,
    ):
        result = extract_text_from_image(b64, settings=s)

    assert result == "neural output"
    mock_got.assert_called_once()
    mock_tess.assert_not_called()

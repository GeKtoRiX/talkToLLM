from __future__ import annotations

import base64
import io
import logging
from time import perf_counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.core.config import AppSettings

logger = logging.getLogger(__name__)

# Module-level singleton cache keyed by (source, device) to avoid reloading
# the GOT-OCR2 model on every request.
_got_model_cache: dict[tuple[str, str], tuple[Any, Any]] = {}


# ---------------------------------------------------------------------------
# Image preprocessing
# ---------------------------------------------------------------------------

def _preprocess_image(image: Any) -> Any:
    """Normalise image for neural OCR: RGB, upscale if small, sharpen, contrast.

    Args:
        image: PIL.Image.Image — any mode accepted.

    Returns:
        PIL.Image.Image in RGB mode, suitable for GOT-OCR2 (trained on ~1024px).
    """
    from PIL import Image, ImageEnhance, ImageFilter  # noqa: PLC0415

    if not isinstance(image, Image.Image):
        raise TypeError(f"Expected PIL.Image, got {type(image)}")

    # 1. Convert to RGB (handles RGBA, L, P, CMYK, …)
    if image.mode != "RGB":
        image = image.convert("RGB")

    # 2. Upscale if shortest side < 800px — bicubic for text sharpness.
    #    GOT-OCR2 performs best on ~1024px images; small inputs degrade accuracy.
    w, h = image.size
    min_side = min(w, h)
    if min_side < 800:
        scale = 800 / min_side
        image = image.resize((int(w * scale), int(h * scale)), Image.BICUBIC)
        logger.debug("[ocr.preprocess] upscaled %dx%d → %dx%d", w, h, *image.size)

    # 3. Mild unsharp mask to restore sharpness lost during upscaling.
    image = image.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=3))

    # 4. Slight contrast boost — helps with light textbook paper backgrounds.
    image = ImageEnhance.Contrast(image).enhance(1.15)

    return image


# ---------------------------------------------------------------------------
# GOT-OCR2 backend
# ---------------------------------------------------------------------------

def _load_got_ocr2(settings: AppSettings) -> tuple[Any, Any]:
    """Return (processor, model) from cache, loading from disk/HF if needed.

    Raises:
        ImportError: if transformers or torch is not installed.
        OSError: if local_files_only is True and weights are not cached.
    """
    import torch  # noqa: PLC0415
    from transformers import AutoProcessor, GotOcr2ForConditionalGeneration  # noqa: PLC0415

    device = "cuda" if torch.cuda.is_available() else "cpu"

    # Prefer a fully downloaded local copy; otherwise fall back to HF hub.
    local_dir = settings.resolve_path(settings.ocr_model_root) / "GOT-OCR-2.0-hf"
    source = (
        str(local_dir)
        if (local_dir / "config.json").exists()
        else "stepfun-ai/GOT-OCR-2.0-hf"
    )

    cache_key = (source, device)
    if cache_key in _got_model_cache:
        return _got_model_cache[cache_key]

    logger.info(
        "[ocr] loading GOT-OCR2 from %s on %s …", source, device,
        extra={"event": "ocr.model.loading", "source": source, "device": device},
    )

    cache_dir = str(settings.resolve_path(settings.ocr_model_root))

    processor = AutoProcessor.from_pretrained(
        source,
        local_files_only=settings.ocr_local_files_only,
        cache_dir=cache_dir,
    )

    # Try float16 first (faster on GPU); fall back to float32 on CPU / unsupported hw.
    dtype = torch.float16 if device == "cuda" else torch.float32
    try:
        model = GotOcr2ForConditionalGeneration.from_pretrained(
            source,
            torch_dtype=dtype,
            local_files_only=settings.ocr_local_files_only,
            cache_dir=cache_dir,
        ).to(device)
    except RuntimeError:
        logger.warning("[ocr] float16 failed, retrying with float32")
        dtype = torch.float32
        model = GotOcr2ForConditionalGeneration.from_pretrained(
            source,
            torch_dtype=dtype,
            local_files_only=settings.ocr_local_files_only,
            cache_dir=cache_dir,
        ).to(device)

    model.eval()
    _got_model_cache[cache_key] = (processor, model)
    logger.info(
        "[ocr] GOT-OCR2 ready (device=%s, dtype=%s)", device, dtype,
        extra={"event": "ocr.model.loaded", "source": source, "device": device},
    )
    return processor, model


def _run_got_ocr2(image: Any, settings: AppSettings) -> str:
    """Run GOT-OCR2 inference and return Markdown-formatted text.

    Uses `format=True` (structured Markdown output) and `crop_to_patches=True`
    (subdivides the image into sub-patches for dense multi-column layouts).
    """
    import torch  # noqa: PLC0415

    processor, model = _load_got_ocr2(settings)
    device = next(model.parameters()).device

    inputs = processor(
        image,
        return_tensors="pt",
        format=True,                        # emit Markdown (headings, bold, tables, columns)
        crop_to_patches=True,               # sub-patch strategy for dense/complex layouts
        max_patches=settings.ocr_max_patches,
    ).to(device)

    logger.debug("[ocr] got_ocr2 running inference (max_patches=%d, max_new_tokens=4096)…", settings.ocr_max_patches)
    t0 = perf_counter()
    with torch.inference_mode():
        generate_ids = model.generate(
            **inputs,
            do_sample=False,
            max_new_tokens=4096,
            stop_strings="<|im_end|>",
            tokenizer=processor.tokenizer,
        )
    logger.debug("[ocr] got_ocr2 inference done in %.3fs", perf_counter() - t0)

    # Strip the echoed prompt tokens; decode the generated suffix only.
    output_ids = generate_ids[:, inputs["input_ids"].shape[1]:]
    result: str = processor.decode(output_ids[0], skip_special_tokens=True)
    return result.strip()


# ---------------------------------------------------------------------------
# Tesseract fallback backend
# ---------------------------------------------------------------------------

def _run_tesseract(image: Any) -> str:
    """Tesseract PSM 3 — original behaviour, kept as a fallback."""
    import pytesseract  # noqa: PLC0415

    t0 = perf_counter()
    result = pytesseract.image_to_string(image.convert("RGB"), config="--psm 3").strip()
    logger.debug("[ocr] tesseract done in %.3fs — %d chars", perf_counter() - t0, len(result))
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_text_from_image(
    data_base64: str,
    settings: AppSettings | None = None,
) -> str:
    """Decode a base64 image and return OCR text with layout preserved.

    Backend selection is controlled by ``settings.ocr_backend``:

    * ``"auto"``       — try GOT-OCR2 first; fall back to Tesseract on any error.
    * ``"got_ocr2"``   — neural OCR only; raises on failure (no silent fallback).
    * ``"tesseract"``  — Tesseract PSM 3 only (original behaviour).

    When GOT-OCR2 is used the output is Markdown-formatted, preserving headings,
    lists, tables, columns, and reading order.

    Args:
        data_base64: Base64-encoded image (PNG / JPEG / WebP).
        settings:    AppSettings instance; defaults to a fresh AppSettings() if
                     not provided (keeps backward compatibility for callers that
                     omit the argument).

    Returns:
        Extracted text string (may be Markdown when GOT-OCR2 is active).

    Raises:
        Exception: if the selected backend fails and no fallback is configured.
    """
    from PIL import Image  # noqa: PLC0415

    if settings is None:
        from app.core.config import AppSettings as _AppSettings  # noqa: PLC0415
        settings = _AppSettings()

    img_bytes = base64.b64decode(data_base64)
    image = Image.open(io.BytesIO(img_bytes))
    image = _preprocess_image(image)

    backend = settings.ocr_backend.lower()

    if backend == "tesseract":
        logger.debug("[ocr] backend=tesseract")
        return _run_tesseract(image)

    if backend == "got_ocr2":
        logger.debug("[ocr] backend=got_ocr2 (explicit, no fallback)")
        text = _run_got_ocr2(image, settings)
        logger.debug("[ocr] got_ocr2 extracted %d chars", len(text))
        return text

    # "auto": neural first, Tesseract fallback
    try:
        logger.debug("[ocr] backend=auto, trying got_ocr2…")
        text = _run_got_ocr2(image, settings)
        logger.debug("[ocr] got_ocr2 extracted %d chars", len(text))
        return text
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[ocr] GOT-OCR2 failed (%s), falling back to Tesseract", exc,
            extra={"event": "ocr.fallback", "reason": str(exc)},
        )
        return _run_tesseract(image)

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import httpx
import soundfile as sf
import websockets


REPO_ROOT = Path(__file__).resolve().parents[2]
API_BASE_URL = os.environ.get("TALKTOLLM_API_BASE_URL", "http://127.0.0.1:8000")
WEB_BASE_URL = os.environ.get("TALKTOLLM_WEB_BASE_URL", "http://127.0.0.1:5173")
WS_URL = os.environ.get("TALKTOLLM_WS_URL", "ws://127.0.0.1:8000/ws")
LMSTUDIO_MODELS_URL = os.environ.get("TALKTOLLM_LMSTUDIO_MODELS_URL", "http://127.0.0.1:1234/v1/models")
ENV_PATH = REPO_ROOT / "services" / "realtime-api" / ".env"
VISION_FIXTURE_PATH = REPO_ROOT / "tmp" / "runtime" / "vision_e2e_42.png"
# Custom image for vision E2E: use TALKTOLLM_VISION_IMAGE env var, or test_img.png if present.
_env_image = os.environ.get("TALKTOLLM_VISION_IMAGE", "")
CUSTOM_VISION_IMAGE: Path | None = (
    Path(_env_image) if _env_image else (REPO_ROOT / "test_img.png") if (REPO_ROOT / "test_img.png").exists() else None
)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
_E2E_LOG_PATH = REPO_ROOT / "tmp" / "runtime" / "e2e.log"
_E2E_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-5s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_E2E_LOG_PATH, mode="a", encoding="utf-8"),
    ],
)
# Silence noisy third-party loggers
for _noisy in ("httpx", "httpcore", "websockets", "asyncio"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

log = logging.getLogger("e2e")


def _elapsed(start: float) -> str:
    return f"{time.perf_counter() - start:.3f}s"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def normalize_text(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum() or ch.isspace()).strip()


def should_run_vision_check() -> bool:
    mode = os.environ.get("TALKTOLLM_VISION_E2E", "").strip().lower()
    if mode in {"1", "true", "yes", "on"}:
        return True
    if mode in {"0", "false", "no", "off"}:
        return False

    dotenv_values = load_dotenv(ENV_PATH)
    return bool(dotenv_values.get("LLM_VISION_MODEL"))


def create_vision_fixture(path: Path) -> Path:
    log.debug("[fixture] generating synthetic vision fixture → %s", path)
    path.parent.mkdir(parents=True, exist_ok=True)

    script = f"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

output_path = Path({str(path)!r})
image = Image.new("RGB", (1024, 512), "white")
draw = ImageDraw.Draw(image)
font = None
for candidate in (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
):
    try:
        font = ImageFont.truetype(candidate, 240)
        break
    except Exception:
        font = None
if font is None:
    font = ImageFont.load_default()

text = "42"
bbox = draw.textbbox((0, 0), text, font=font)
text_w = bbox[2] - bbox[0]
text_h = bbox[3] - bbox[1]
position = ((image.width - text_w) // 2, (image.height - text_h) // 2 - 20)
draw.text(position, text, fill="black", font=font)
draw.rectangle((160, 120, 864, 392), outline="black", width=5)
image.save(output_path, format="PNG")
"""

    try:
        subprocess.run(["python3", "-c", script], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            "Failed to generate the live screenshot fixture for vision E2E. "
            f"stderr: {error.stderr.strip()}"
        ) from error

    log.debug("[fixture] fixture saved: %s (%.1f KB)", path, path.stat().st_size / 1024)
    return path


async def synthesize_pcm16(text: str) -> bytes:
    t0 = time.perf_counter()
    log.debug("[tts] synthesizing PCM16 for %d chars: %r", len(text), text[:60])

    dotenv_values = load_dotenv(ENV_PATH)
    for key, value in dotenv_values.items():
        os.environ.setdefault(key, value)

    sys.path.insert(0, str(REPO_ROOT / "services" / "realtime-api"))
    from app.core.config import AppSettings
    from app.providers.tts import KokoroTTSProvider

    settings = AppSettings(
        kokoro_local_files_only=True,
        kokoro_device="cpu",
    )
    provider = KokoroTTSProvider(settings)

    async def text_stream():
        yield (0, text)

    wav_parts: list[bytes] = []
    async for chunk in provider.stream_synthesize(text_stream(), voice="default", format="wav", job_id="e2e-live-check"):
        wav_parts.append(chunk.audio_bytes)

    audio, sample_rate = sf.read(io.BytesIO(b"".join(wav_parts)), dtype="float32")
    if getattr(audio, "ndim", 1) > 1:
        audio = audio.mean(axis=1)

    if sample_rate != 16000:
        import numpy as np

        duration = len(audio) / sample_rate
        old_times = np.linspace(0.0, duration, num=len(audio), endpoint=False)
        new_length = max(1, int(duration * 16000))
        new_times = np.linspace(0.0, duration, num=new_length, endpoint=False)
        audio = np.interp(new_times, old_times, audio).astype("float32")
        log.debug("[tts] resampled %d Hz → 16000 Hz, %d samples", sample_rate, new_length)

    import numpy as np

    pcm16 = np.clip(audio, -1.0, 1.0)
    result = (pcm16 * 32767.0).astype(np.int16).tobytes()
    duration_s = len(result) / 2 / 16000
    log.info("[tts] synthesis done in %s — %.2fs of audio (%d bytes PCM16)", _elapsed(t0), duration_s, len(result))
    return result


async def fetch_json(client: httpx.AsyncClient, url: str) -> Any:
    response = await client.get(url)
    response.raise_for_status()
    return response.json()


async def fetch_text(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url)
    response.raise_for_status()
    return response.text


async def receive_json(socket: websockets.ClientConnection, timeout: float = 60.0) -> dict[str, Any]:
    raw_message = await asyncio.wait_for(socket.recv(), timeout=timeout)
    if not isinstance(raw_message, str):
        raise RuntimeError(f"Expected text websocket frame, got {type(raw_message).__name__}")
    return json.loads(raw_message)


async def send_audio_chunks(socket: websockets.ClientConnection, pcm16: bytes, chunk_size: int = 6400) -> None:
    chunks = range(0, len(pcm16), chunk_size)
    log.debug("[ws] sending %d audio chunks (%d bytes total)", len(chunks), len(pcm16))
    for index in chunks:
        await socket.send(pcm16[index : index + chunk_size])


async def collect_until(
    socket: websockets.ClientConnection,
    *,
    expected: set[str],
    max_events: int = 80,
    timeout: float = 90.0,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    t0 = time.perf_counter()
    log.debug("[ws] waiting for events: %s", sorted(expected))

    for _ in range(max_events):
        event = await receive_json(socket, timeout=timeout)
        events.append(event)
        etype = event["type"]
        if etype not in seen:
            log.debug("[ws] ← %s (first occurrence, +%s)", etype, _elapsed(t0))
            seen.add(etype)
        if expected.issubset(seen):
            log.debug("[ws] all expected events received in %s (%d total)", _elapsed(t0), len(events))
            return events

    raise RuntimeError(f"Expected websocket events {sorted(expected)}, but saw {sorted(seen)}")


# ---------------------------------------------------------------------------
# Stage: endpoint checks
# ---------------------------------------------------------------------------

async def assert_live_endpoints() -> None:
    t0 = time.perf_counter()
    log.info("[endpoints] checking backend, metrics, frontend, LM Studio...")
    async with httpx.AsyncClient(timeout=10.0) as client:
        t1 = time.perf_counter()
        health = await fetch_json(client, f"{API_BASE_URL}/healthz")
        if health.get("status") != "ok":
            raise RuntimeError(f"/healthz returned unexpected payload: {health}")
        log.info("[endpoints] /healthz OK in %s — %s", _elapsed(t1), health)

        t1 = time.perf_counter()
        metrics = await fetch_text(client, f"{API_BASE_URL}/metrics")
        for expected_metric in (
            "talktollm_sessions_total",
            "talktollm_stage_latency_seconds",
            "talktollm_interruptions_total",
        ):
            if expected_metric not in metrics:
                raise RuntimeError(f"Metric '{expected_metric}' was not found in /metrics output.")
        log.info("[endpoints] /metrics OK in %s (%d bytes, 3 required metrics present)", _elapsed(t1), len(metrics))

        t1 = time.perf_counter()
        frontend_html = await fetch_text(client, WEB_BASE_URL)
        if "<div id=\"root\"></div>" not in frontend_html and "<div id=\"root\">" not in frontend_html:
            raise RuntimeError("Frontend root container was not found in the web app HTML.")
        log.info("[endpoints] frontend OK in %s (%d bytes)", _elapsed(t1), len(frontend_html))

        t1 = time.perf_counter()
        models_payload = await fetch_json(client, LMSTUDIO_MODELS_URL)
        _dcfg = load_dotenv(ENV_PATH)
        _vm = _dcfg.get("LLM_VISION_MODEL", "").strip()
        _bypass = _dcfg.get("LLM_VISION_BYPASS_OCR", "true").strip().lower() not in {"0", "false", "no", "off"}
        configured_model = (_vm if _vm and _bypass else None) or _dcfg.get("LLM_MODEL", "gemma-4-e4b-it")
        model_ids = {item.get("id") for item in models_payload.get("data", [])}
        if configured_model not in model_ids:
            raise RuntimeError(
                f"Configured LM Studio model '{configured_model}' was not found at {LMSTUDIO_MODELS_URL}. "
                f"Available models: {sorted(model_ids)}"
            )
        log.info(
            "[endpoints] LM Studio OK in %s — model=%r available (total: %d)",
            _elapsed(t1), configured_model, len(model_ids),
        )

    log.info("[endpoints] all endpoint checks passed in %s", _elapsed(t0))


# ---------------------------------------------------------------------------
# Stage: voice session (STT → LLM → TTS, interruption, second turn)
# ---------------------------------------------------------------------------

async def run_voice_session_check() -> None:
    suite_t0 = time.perf_counter()
    log.info("[voice] === starting voice session check ===")

    first_prompt = "Hello from the live end to end smoke test. Please answer briefly."
    second_prompt = "This is the second turn after interruption. Confirm the app is ready."

    log.info("[voice] synthesizing TTS for turn 1...")
    first_pcm = await synthesize_pcm16(first_prompt)
    log.info("[voice] synthesizing TTS for turn 2...")
    second_pcm = await synthesize_pcm16(second_prompt)

    log.info("[voice] connecting to WebSocket %s", WS_URL)
    async with websockets.connect(WS_URL, max_size=10_000_000) as socket:
        seq = 0
        session_id: str | None = None
        turn_id: str | None = None

        async def send_event(event_type: str, payload: dict[str, Any]) -> None:
            nonlocal seq, session_id, turn_id
            seq += 1
            log.debug("[ws] → %s (seq=%d)", event_type, seq)
            await socket.send(
                json.dumps(
                    {
                        "type": event_type,
                        "sessionId": session_id,
                        "turnId": turn_id,
                        "seq": seq,
                        "timestamp": "2026-04-07T00:00:00Z",
                        "payload": payload,
                    }
                )
            )

        # --- session handshake ---
        t1 = time.perf_counter()
        await send_event("session.start", {"sampleRate": 16000, "format": "pcm_s16le", "language": "en"})
        started = await receive_json(socket)
        if started["type"] != "session.started":
            raise RuntimeError(f"Expected session.started, got {started['type']}")
        session_id = started["sessionId"]
        log.info("[voice] session started in %s — session_id=%s", _elapsed(t1), session_id)

        # --- turn 1: speech → STT → LLM → TTS ---
        t1 = time.perf_counter()
        log.info("[voice] turn 1: sending %d bytes of audio (%d chunks)...", len(first_pcm), len(first_pcm) // 6400 + 1)
        await send_event("speech.start", {})
        await send_audio_chunks(socket, first_pcm)
        await send_event("speech.end", {})
        log.debug("[voice] audio sent in %s, waiting for pipeline events...", _elapsed(t1))

        first_turn_events = await collect_until(
            socket,
            expected={"transcript.final", "llm.thinking", "response.text.delta", "tts.chunk"},
        )

        transcript_event = next(event for event in first_turn_events if event["type"] == "transcript.final")
        transcript_text = str(transcript_event["payload"]["text"])
        normalized_transcript = normalize_text(transcript_text)
        if "hello" not in normalized_transcript or "smoke test" not in normalized_transcript:
            raise RuntimeError(f"Unexpected first transcript text: {transcript_text}")
        log.info("[voice] turn 1 transcript OK in %s: %r", _elapsed(t1), transcript_text)

        last_turn_ids = [event.get("turnId") for event in first_turn_events if event.get("turnId")]
        if not last_turn_ids:
            raise RuntimeError("Server never assigned a turnId during the first turn.")
        turn_id = last_turn_ids[-1]
        log.debug("[voice] turn_id assigned: %s", turn_id)

        # count event types for diagnostics
        event_counts = {}
        for ev in first_turn_events:
            event_counts[ev["type"]] = event_counts.get(ev["type"], 0) + 1
        log.info("[voice] turn 1 events: %s", event_counts)

        # --- interruption ---
        t1 = time.perf_counter()
        log.info("[voice] sending playback.interrupt...")
        await send_event("playback.interrupt", {})
        interrupt_events = await collect_until(socket, expected={"playback.stop"})
        if not any(event["type"] == "playback.stop" for event in interrupt_events):
            raise RuntimeError("playback.interrupt did not yield playback.stop")
        log.info("[voice] interruption confirmed (playback.stop) in %s", _elapsed(t1))

        # --- turn 2: post-interruption ---
        t1 = time.perf_counter()
        log.info("[voice] turn 2: sending %d bytes of audio after interruption...", len(second_pcm))
        await send_event("speech.start", {})
        await send_audio_chunks(socket, second_pcm)
        await send_event("speech.end", {})

        second_turn_events = await collect_until(
            socket,
            expected={"transcript.final", "response.text.delta", "response.text.final", "tts.chunk"},
        )
        second_transcript = next(event for event in second_turn_events if event["type"] == "transcript.final")
        normalized_second = normalize_text(str(second_transcript["payload"]["text"]))
        if "second" not in normalized_second or "app is ready" not in normalized_second:
            raise RuntimeError(f"Unexpected second transcript text: {second_transcript['payload']['text']}")
        log.info("[voice] turn 2 transcript OK: %r", second_transcript["payload"]["text"])

        response_final = next(event for event in second_turn_events if event["type"] == "response.text.final")
        response_text = str(response_final["payload"]["text"]).strip()
        if not response_text:
            raise RuntimeError("response.text.final payload was empty on the second turn.")
        log.info("[voice] turn 2 LLM response (%d chars) in %s: %r", len(response_text), _elapsed(t1), response_text[:120])

        event_counts2 = {}
        for ev in second_turn_events:
            event_counts2[ev["type"]] = event_counts2.get(ev["type"], 0) + 1
        log.info("[voice] turn 2 events: %s", event_counts2)

        # --- session teardown ---
        t1 = time.perf_counter()
        await send_event("session.stop", {})
        log.debug("[voice] session.stop sent, waiting for WS close...")
        try:
            while True:
                message = await asyncio.wait_for(socket.recv(), timeout=2.0)
                if isinstance(message, str):
                    event = json.loads(message)
                    if event.get("type") == "playback.stop":
                        log.debug("[voice] received trailing playback.stop")
                        continue
                raise RuntimeError(f"Unexpected websocket payload after session.stop: {message!r}")
        except websockets.ConnectionClosedOK:
            log.info("[voice] WebSocket closed cleanly in %s", _elapsed(t1))
        except TimeoutError as error:
            raise RuntimeError("Server did not close the websocket after session.stop") from error

    log.info("[voice] === voice session check PASSED in %s ===", _elapsed(suite_t0))


# ---------------------------------------------------------------------------
# Stage: screenshot / vision turn (OCR → LLM → TTS)
# ---------------------------------------------------------------------------

async def run_screenshot_turn_check() -> None:
    suite_t0 = time.perf_counter()
    dotenv_cfg = load_dotenv(ENV_PATH)
    vision_model = dotenv_cfg.get("LLM_VISION_MODEL", "").strip()
    bypass_ocr = dotenv_cfg.get("LLM_VISION_BYPASS_OCR", "true").strip().lower() not in {"0", "false", "no", "off"}
    if vision_model and bypass_ocr:
        log.info("[vision] === screenshot turn check — mode: vision model (%s, OCR bypassed) ===", vision_model)
    else:
        log.info("[vision] === screenshot turn check — mode: OCR → LLM ===")

    if CUSTOM_VISION_IMAGE is not None and CUSTOM_VISION_IMAGE.exists():
        image_path = CUSTOM_VISION_IMAGE
        # test_img.png is a textbook page about "Personal information" / vocabulary / greetings.
        # OCR reliably extracts several of these terms. Accept any of them in the LLM response.
        question = "What is the main topic or lesson title shown in the screenshot?"
        expected_tokens = {"personal", "vocabulary", "greetings", "email"}
        from PIL import Image as _PILImage  # noqa: PLC0415
        with _PILImage.open(image_path) as _img:
            _w, _h = _img.size
        img_width, img_height = _w, _h
        log.info("[vision] using custom image: %s (%dx%d, %.1f KB)", image_path, img_width, img_height, image_path.stat().st_size / 1024)
    else:
        image_path = create_vision_fixture(VISION_FIXTURE_PATH)
        question = "What number is shown in the screenshot? Reply with digits only."
        expected_tokens = {"42"}
        img_width, img_height = 1024, 512
        log.info("[vision] using generated fixture: %s (%dx%d)", image_path, img_width, img_height)

    log.info("[vision] question: %r", question)
    log.info("[vision] expected tokens (any): %s", sorted(expected_tokens))

    t_encode = time.perf_counter()
    raw_bytes = image_path.read_bytes()
    attachment = {
        "mimeType": "image/png",
        "dataBase64": base64.b64encode(raw_bytes).decode("ascii"),
        "width": img_width,
        "height": img_height,
        "name": image_path.name,
    }
    log.debug("[vision] image encoded to base64 in %s (%d raw bytes → %d b64 chars)", _elapsed(t_encode), len(raw_bytes), len(attachment["dataBase64"]))

    log.info("[vision] connecting to WebSocket %s", WS_URL)
    async with websockets.connect(WS_URL, max_size=20_000_000) as socket:
        seq = 0
        session_id: str | None = None
        turn_id: str | None = None

        async def send_event(event_type: str, payload: dict[str, Any]) -> None:
            nonlocal seq, session_id, turn_id
            seq += 1
            log.debug("[ws] → %s (seq=%d)", event_type, seq)
            await socket.send(
                json.dumps(
                    {
                        "type": event_type,
                        "sessionId": session_id,
                        "turnId": turn_id,
                        "seq": seq,
                        "timestamp": "2026-04-07T00:00:00Z",
                        "payload": payload,
                    }
                )
            )

        # --- session handshake ---
        t1 = time.perf_counter()
        await send_event("session.start", {"sampleRate": 16000, "format": "pcm_s16le", "language": "en"})
        started = await receive_json(socket)
        if started["type"] != "session.started":
            raise RuntimeError(f"Expected session.started, got {started['type']}")
        session_id = started["sessionId"]
        log.info("[vision] session started in %s — session_id=%s", _elapsed(t1), session_id)

        # --- text.submit with attachment ---
        t1 = time.perf_counter()
        log.info("[vision] sending text.submit with 1 attachment (%s)...", image_path.name)
        await send_event("text.submit", {"text": question, "attachments": [attachment]})

        screenshot_events = await collect_until(
            socket,
            expected={"transcript.final", "response.text.final", "tts.chunk"},
            timeout=150.0,
        )

        # --- validate transcript ---
        transcript_event = next(event for event in screenshot_events if event["type"] == "transcript.final")
        transcript_text = str(transcript_event["payload"]["text"]).strip()
        if transcript_text != question:
            raise RuntimeError(f"Unexpected screenshot transcript text: {transcript_text!r}")
        log.info("[vision] transcript echoed correctly: %r", transcript_text)

        # --- validate LLM response ---
        response_event = next(event for event in screenshot_events if event["type"] == "response.text.final")
        response_text = str(response_event["payload"]["text"]).strip()
        normalized_response = normalize_text(response_text)
        matched = next((tok for tok in expected_tokens if tok in normalized_response), None)
        if matched is None:
            raise RuntimeError(
                f"Vision screenshot turn returned an unexpected answer: {response_text!r}\n"
                f"Expected any of: {sorted(expected_tokens)}"
            )
        log.info(
            "[vision] LLM response OK in %s (%d chars, token %r matched): %r",
            _elapsed(t1), len(response_text), matched, response_text[:120],
        )

        event_counts = {}
        for ev in screenshot_events:
            event_counts[ev["type"]] = event_counts.get(ev["type"], 0) + 1
        log.info("[vision] screenshot turn events: %s", event_counts)

        # --- session teardown ---
        t1 = time.perf_counter()
        await send_event("session.stop", {})
        log.debug("[vision] session.stop sent, waiting for WS close...")
        try:
            while True:
                message = await asyncio.wait_for(socket.recv(), timeout=2.0)
                if isinstance(message, str):
                    event = json.loads(message)
                    if event.get("type") == "playback.stop":
                        log.debug("[vision] received trailing playback.stop")
                        continue
                raise RuntimeError(f"Unexpected websocket payload after session.stop: {message!r}")
        except websockets.ConnectionClosedOK:
            log.info("[vision] WebSocket closed cleanly in %s", _elapsed(t1))
        except TimeoutError as error:
            raise RuntimeError("Server did not close the websocket after vision session.stop") from error

    log.info("[vision] === screenshot turn check PASSED in %s ===", _elapsed(suite_t0))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    suite_t0 = time.perf_counter()
    env_summary = {
        "API": API_BASE_URL,
        "WS": WS_URL,
        "vision_image": str(CUSTOM_VISION_IMAGE) if CUSTOM_VISION_IMAGE else "fixture (generated)",
        "vision_e2e_env": os.environ.get("TALKTOLLM_VISION_E2E", "(not set)"),
    }
    log.info("=" * 60)
    log.info("talkToLLM E2E suite starting")
    for k, v in env_summary.items():
        log.info("  %-20s %s", k, v)
    log.info("=" * 60)

    log.info("[main] stage 1/3 — checking live endpoints")
    await assert_live_endpoints()

    log.info("[main] stage 2/3 — voice session (STT + LLM + TTS + interruption)")
    await run_voice_session_check()

    if should_run_vision_check():
        _dcfg = load_dotenv(ENV_PATH)
        _vm = _dcfg.get("LLM_VISION_MODEL", "").strip()
        _bypass = _dcfg.get("LLM_VISION_BYPASS_OCR", "true").strip().lower() not in {"0", "false", "no", "off"}
        if _vm and _bypass:
            log.info("[main] stage 3/3 — screenshot vision turn (vision model=%s, OCR bypassed)", _vm)
        else:
            log.info("[main] stage 3/3 — screenshot vision turn (OCR + LLM + TTS)")
        await run_screenshot_turn_check()
    else:
        log.info(
            "[main] stage 3/3 — SKIPPED (set TALKTOLLM_VISION_E2E=1 or configure LLM_VISION_MODEL to enable)"
        )

    log.info("=" * 60)
    log.info("E2E MVP check PASSED in %s", _elapsed(suite_t0))
    log.info("Log saved to: %s", _E2E_LOG_PATH)
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

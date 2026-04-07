from __future__ import annotations

import asyncio
import io
import json
import os
from pathlib import Path
import sys
from typing import Any

import httpx
import soundfile as sf
import websockets


REPO_ROOT = Path(__file__).resolve().parents[1]
API_BASE_URL = os.environ.get("TALKTOLLM_API_BASE_URL", "http://127.0.0.1:8000")
WEB_BASE_URL = os.environ.get("TALKTOLLM_WEB_BASE_URL", "http://127.0.0.1:5173")
WS_URL = os.environ.get("TALKTOLLM_WS_URL", "ws://127.0.0.1:8000/ws")
LMSTUDIO_MODELS_URL = os.environ.get("TALKTOLLM_LMSTUDIO_MODELS_URL", "http://127.0.0.1:1234/v1/models")
ENV_PATH = REPO_ROOT / "services" / "realtime-api" / ".env"


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


async def synthesize_pcm16(text: str) -> bytes:
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

    import numpy as np

    pcm16 = np.clip(audio, -1.0, 1.0)
    return (pcm16 * 32767.0).astype(np.int16).tobytes()


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
    for index in range(0, len(pcm16), chunk_size):
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

    for _ in range(max_events):
        event = await receive_json(socket, timeout=timeout)
        events.append(event)
        seen.add(event["type"])
        if expected.issubset(seen):
            return events

    raise RuntimeError(f"Expected websocket events {sorted(expected)}, but saw {sorted(seen)}")


async def assert_live_endpoints() -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        health = await fetch_json(client, f"{API_BASE_URL}/healthz")
        if health.get("status") != "ok":
            raise RuntimeError(f"/healthz returned unexpected payload: {health}")

        metrics = await fetch_text(client, f"{API_BASE_URL}/metrics")
        for expected_metric in (
            "talktollm_sessions_total",
            "talktollm_stage_latency_seconds",
            "talktollm_interruptions_total",
        ):
            if expected_metric not in metrics:
                raise RuntimeError(f"Metric '{expected_metric}' was not found in /metrics output.")

        frontend_html = await fetch_text(client, WEB_BASE_URL)
        if "<div id=\"root\"></div>" not in frontend_html and "<div id=\"root\">" not in frontend_html:
            raise RuntimeError("Frontend root container was not found in the web app HTML.")

        models_payload = await fetch_json(client, LMSTUDIO_MODELS_URL)
        configured_model = load_dotenv(ENV_PATH).get("LLM_MODEL", "gemma-4-e4b-it")
        model_ids = {item.get("id") for item in models_payload.get("data", [])}
        if configured_model not in model_ids:
            raise RuntimeError(
                f"Configured LM Studio model '{configured_model}' was not found at {LMSTUDIO_MODELS_URL}. "
                f"Available models: {sorted(model_ids)}"
            )


async def run_voice_session_check() -> None:
    first_prompt = "Hello from the live end to end smoke test. Please answer briefly."
    second_prompt = "This is the second turn after interruption. Confirm the app is ready."

    first_pcm = await synthesize_pcm16(first_prompt)
    second_pcm = await synthesize_pcm16(second_prompt)

    async with websockets.connect(WS_URL, max_size=10_000_000) as socket:
        seq = 0
        session_id: str | None = None
        turn_id: str | None = None

        async def send_event(event_type: str, payload: dict[str, Any]) -> None:
            nonlocal seq, session_id, turn_id
            seq += 1
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

        await send_event("session.start", {"sampleRate": 16000, "format": "pcm_s16le", "language": "en"})
        started = await receive_json(socket)
        if started["type"] != "session.started":
            raise RuntimeError(f"Expected session.started, got {started['type']}")
        session_id = started["sessionId"]

        await send_event("speech.start", {})
        await send_audio_chunks(socket, first_pcm)
        await send_event("speech.end", {})

        first_turn_events = await collect_until(
            socket,
            expected={"transcript.final", "llm.thinking", "response.text.delta", "tts.chunk"},
        )

        transcript_event = next(event for event in first_turn_events if event["type"] == "transcript.final")
        transcript_text = str(transcript_event["payload"]["text"])
        normalized_transcript = normalize_text(transcript_text)
        if "hello" not in normalized_transcript or "smoke test" not in normalized_transcript:
            raise RuntimeError(f"Unexpected first transcript text: {transcript_text}")

        last_turn_ids = [event.get("turnId") for event in first_turn_events if event.get("turnId")]
        if not last_turn_ids:
            raise RuntimeError("Server never assigned a turnId during the first turn.")
        turn_id = last_turn_ids[-1]

        await send_event("playback.interrupt", {})
        interrupt_events = await collect_until(socket, expected={"playback.stop"})
        if not any(event["type"] == "playback.stop" for event in interrupt_events):
            raise RuntimeError("playback.interrupt did not yield playback.stop")

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

        response_final = next(event for event in second_turn_events if event["type"] == "response.text.final")
        if not str(response_final["payload"]["text"]).strip():
            raise RuntimeError("response.text.final payload was empty on the second turn.")

        await send_event("session.stop", {})
        try:
            while True:
                message = await asyncio.wait_for(socket.recv(), timeout=2.0)
                if isinstance(message, str):
                    event = json.loads(message)
                    if event.get("type") == "playback.stop":
                        continue
                raise RuntimeError(f"Unexpected websocket payload after session.stop: {message!r}")
        except websockets.ConnectionClosedOK:
            return
        except TimeoutError as error:
            raise RuntimeError("Server did not close the websocket after session.stop") from error


async def main() -> None:
    print("Checking live endpoints...")
    await assert_live_endpoints()
    print("Checking websocket voice loop...")
    await run_voice_session_check()
    print("E2E MVP check passed.")


if __name__ == "__main__":
    asyncio.run(main())

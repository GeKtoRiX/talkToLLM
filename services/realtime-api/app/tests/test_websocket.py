import base64

from fastapi.testclient import TestClient

from app.core.config import AppSettings
from app.main import create_app


def create_mock_app(**overrides):
    return create_app(
        AppSettings(
            llm_provider="mock",
            stt_provider="mock",
            tts_provider="mock",
            **overrides,
        )
    )


def sample_attachment(mime_type: str = "image/png", byte_count: int = 8):
    return {
        "mimeType": mime_type,
        "dataBase64": base64.b64encode(b"x" * byte_count).decode("ascii"),
        "width": 800,
        "height": 600,
        "name": "worksheet.png",
    }


def collect_events(websocket, *, expected: set[str], limit: int = 200):
    events = []
    event_types = set()

    for _ in range(limit):
        event = websocket.receive_json()
        events.append(event)
        event_types.add(event["type"])
        if expected.issubset(event_types):
            return events

    raise AssertionError(f"Expected events {sorted(expected)}, but saw {sorted(event_types)}")


def test_websocket_flow_emits_transcript_and_response():
    app = create_mock_app()

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "session.start",
                    "sessionId": None,
                    "turnId": None,
                    "seq": 1,
                    "timestamp": "2026-04-06T00:00:00Z",
                    "payload": {"sampleRate": 16000, "format": "pcm_s16le", "language": "en"},
                }
            )
            started = websocket.receive_json()
            assert started["type"] == "session.started"

            websocket.send_json(
                {
                    "type": "speech.start",
                    "sessionId": started["sessionId"],
                    "turnId": None,
                    "seq": 2,
                    "timestamp": "2026-04-06T00:00:01Z",
                    "payload": {},
                }
            )
            websocket.send_bytes(b"\x00\x00" * 3200)
            websocket.send_json(
                {
                    "type": "speech.end",
                    "sessionId": started["sessionId"],
                    "turnId": None,
                    "seq": 3,
                    "timestamp": "2026-04-06T00:00:02Z",
                    "payload": {},
                }
            )

            events = collect_events(websocket, expected={"transcript.final", "response.text.delta", "response.text.final", "tts.chunk"})
            event_types = {event["type"] for event in events}

            assert "transcript.final" in event_types
            assert "response.text.delta" in event_types
            assert "response.text.final" in event_types
            assert "tts.chunk" in event_types


def test_text_submit_with_screenshot_emits_response_and_tts():
    app = create_mock_app()

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "session.start",
                    "sessionId": None,
                    "turnId": None,
                    "seq": 1,
                    "timestamp": "2026-04-07T00:00:00Z",
                    "payload": {"sampleRate": 16000, "format": "pcm_s16le", "language": "en"},
                }
            )
            started = websocket.receive_json()

            websocket.send_json(
                {
                    "type": "text.submit",
                    "sessionId": started["sessionId"],
                    "turnId": None,
                    "seq": 2,
                    "timestamp": "2026-04-07T00:00:01Z",
                    "payload": {"text": "Help me solve this worksheet.", "attachments": [sample_attachment()]},
                }
            )

            events = collect_events(websocket, expected={"transcript.final", "llm.thinking", "response.text.final", "tts.chunk"})
            response_final = next(event for event in events if event["type"] == "response.text.final")
            assert "screenshot" in response_final["payload"]["text"].lower()


def test_voice_turn_with_screenshot_reaches_mock_llm():
    app = create_mock_app()

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "session.start",
                    "sessionId": None,
                    "turnId": None,
                    "seq": 1,
                    "timestamp": "2026-04-07T00:00:00Z",
                    "payload": {"sampleRate": 16000, "format": "pcm_s16le", "language": "en"},
                }
            )
            started = websocket.receive_json()

            websocket.send_json(
                {
                    "type": "speech.start",
                    "sessionId": started["sessionId"],
                    "turnId": None,
                    "seq": 2,
                    "timestamp": "2026-04-07T00:00:01Z",
                    "payload": {"attachments": [sample_attachment()]},
                }
            )
            websocket.send_bytes(b"\x00\x00" * 3200)
            websocket.send_json(
                {
                    "type": "speech.end",
                    "sessionId": started["sessionId"],
                    "turnId": None,
                    "seq": 3,
                    "timestamp": "2026-04-07T00:00:02Z",
                    "payload": {},
                }
            )

            events = collect_events(websocket, expected={"response.text.final"})
            response_final = next(event for event in events if event["type"] == "response.text.final")
            assert "screenshot" in response_final["payload"]["text"].lower()


def test_invalid_screenshot_attachment_returns_error():
    app = create_mock_app(screenshot_allowed_mime_types="image/png", screenshot_max_bytes=4)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "session.start",
                    "sessionId": None,
                    "turnId": None,
                    "seq": 1,
                    "timestamp": "2026-04-07T00:00:00Z",
                    "payload": {"sampleRate": 16000, "format": "pcm_s16le", "language": "en"},
                }
            )
            started = websocket.receive_json()

            websocket.send_json(
                {
                    "type": "text.submit",
                    "sessionId": started["sessionId"],
                    "turnId": None,
                    "seq": 2,
                    "timestamp": "2026-04-07T00:00:01Z",
                    "payload": {"text": "Analyze this image", "attachments": [sample_attachment("image/gif", byte_count=16)]},
                }
            )

            error_event = websocket.receive_json()
            assert error_event["type"] == "error"
            assert "Unsupported screenshot format" in error_event["payload"]["message"]
            assert error_event["payload"]["code"] == "INVALID_ATTACHMENT"

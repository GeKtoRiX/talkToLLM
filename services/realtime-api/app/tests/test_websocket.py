from fastapi.testclient import TestClient

from app.main import create_app


def test_websocket_flow_emits_transcript_and_response():
    app = create_app()

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

            event_types = []
            for _ in range(20):
                event = websocket.receive_json()
                event_types.append(event["type"])
                if "transcript.final" in event_types and "response.text.delta" in event_types:
                    break

            assert "transcript.final" in event_types
            assert "response.text.delta" in event_types

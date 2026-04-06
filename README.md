# talkToLLM

Web-first prototype scaffold for a two-way voice conversation app with an LLM.

## Workspace Layout

- `apps/web`: React + Vite client with push-to-talk, websocket transport, audio capture, playback queue, and visible session state.
- `libs/contracts`: shared TypeScript contracts for session states and websocket events.
- `services/realtime-api`: FastAPI websocket service with session orchestration, provider abstractions, mock providers, and metrics.

## What Works Today

- English-only session UX scaffold
- Push-to-talk browser client
- 16 kHz mono PCM16 audio capture through an `AudioWorklet`
- WebSocket realtime loop
- Session state machine
- Transcript and assistant response rendering
- Sentence chunking and streamed TTS chunks
- Interruption and playback stop propagation
- Mock-by-default providers so the system runs without external credentials
- FastAPI `/healthz` and Prometheus `/metrics`

## Current Provider Strategy

The prototype is runnable out of the box with mock providers. The backend is already structured around:

- `STTProvider`
- `LLMProvider`
- `TTSProvider`

That lets you replace the defaults with real Whisper / managed LLM / Kokoro implementations without changing the session orchestration layer.

## Quick Start

### 1. Install web dependencies

```bash
npm install
```

### 2. Create a Python environment and install the API

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e "services/realtime-api[dev]"
```

### 3. Run the API

```bash
uvicorn app.main:app --reload --app-dir services/realtime-api
```

### 4. Run the web app

```bash
npm run dev:web
```

### 5. Open the UI

Visit `http://localhost:5173` and hold the `Hold to Talk` button.

## Environment

Backend settings live in `services/realtime-api/.env.example`.

Frontend settings live in `apps/web/.env.example`.

## Verification

- Web tests: `npm run test:web`
- Web build: `npm run build:web`
- API tests: `pytest services/realtime-api/app/tests`


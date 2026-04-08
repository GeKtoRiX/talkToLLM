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
- Screenshot-aware voice and typed turns for LM Studio vision models
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
You can also paste or upload one screenshot, then ask about it by voice or text.

## Environment

Backend settings live in `services/realtime-api/.env.example`.

Frontend settings live in `apps/web/.env.example`.

## Running With Real Providers

The default code path used by tests remains safe, but the sample backend environment is now configured for the local stack: `Whisper (PyTorch ROCm) + LM Studio + Kokoro`.

To enable the real provider path:

1. Install ROCm-enabled PyTorch for Whisper:

```bash
. .venv/bin/activate
pip install --index-url https://download.pytorch.org/whl/rocm6.4 torch==2.9.1+rocm6.4
```

2. Install the optional realtime dependencies:

```bash
pip install -e "services/realtime-api[dev,real]"
```

3. Make sure the host has `espeak-ng` available for Kokoro English voices.

4. Copy `services/realtime-api/.env.example` to `services/realtime-api/.env`.

```env
STT_PROVIDER=whisper_rocm
LLM_PROVIDER=lmstudio
TTS_PROVIDER=kokoro
LMSTUDIO_BASE_URL=http://localhost:1234/v1
LLM_MODEL=gemma-4-e4b-it
LLM_VISION_MODEL=gemma-3-12b-it
SCREENSHOT_MAX_BYTES=5242880
SCREENSHOT_ALLOWED_MIME_TYPES=image/png,image/jpeg,image/webp
OCR_ENABLED=true
OCR_BACKEND=tesseract
OCR_MODEL_ROOT=models/ocr
OCR_LOCAL_FILES_ONLY=false
STT_MODEL_ROOT=models/whisper
KOKORO_MODEL_ROOT=models/kokoro
KOKORO_DEVICE=cpu
```

5. Start the API and web app as usual.

Notes:

- `whisper_rocm` uses `openai-whisper` on top of a ROCm-enabled PyTorch runtime.
- The OpenAI Whisper checkpoint is stored under `models/whisper`, typically as `models/whisper/base.en.pt`.
- The realtime TTS path uses Kokoro and emits WAV chunks that are compatible with the existing browser playback queue.
- The local LLM path targets LM Studio's OpenAI-compatible `/v1/chat/completions` streaming endpoint and supports best-effort cancellation.
- Screenshot turns send the active browser-side image only with the current turn, so prior history stays text-only.
- When OCR succeeds, the backend injects the extracted screenshot text into the current turn and skips the raw image upload to LM Studio.
- Screenshot turns require a vision-capable LM Studio model. Set `LLM_VISION_MODEL` if your text model and vision model differ.
- `OCR_BACKEND=tesseract` is the safe local default; switch to `auto` or `got_ocr2` only after preloading GOT-OCR-2.0 or allowing hub downloads.
- `KOKORO_DEVICE=cpu` is the intended default for this stage; Kokoro remains on CPU even when Whisper uses ROCm.
- Turn logs now include `stt_latency_s`, `llm_first_token_latency_s`, `tts_first_audio_latency_s`, and `time_to_first_audio_s`.
- To pre-download local STT/TTS assets into the repo, run `python scripts/tools/prepare_local_models.py`.
- To pre-download GOT-OCR-2.0 into `models/ocr/GOT-OCR-2.0-hf`, run `python scripts/tools/prepare_local_models.py --include-ocr`.
- To verify that Whisper is actually running on the ROCm path, run `PYTHONPATH=services/realtime-api python scripts/tools/check_whisper_rocm.py`.

## Verification

- Web tests: `npm run test:web`
- Web build: `npm run build:web`
- API tests: `.venv/bin/pytest services/realtime-api/tests`

## MVP Workflow

To start the real local stack, run the desktop launcher:

```bash
npm run launch:desktop
```

To boot the stack if needed, run a live end-to-end check, and leave the app running so you can start working right away:

```bash
npm run mvp:e2e
```

That command verifies:

- backend `/healthz`
- backend `/metrics`
- frontend availability on `http://127.0.0.1:5173`
- LM Studio model availability
- websocket session start
- speech turn processing
- transcript generation
- LLM text streaming
- TTS chunk delivery
- interruption handling
- recovery on a second turn
- websocket session stop

If `LLM_VISION_MODEL` is configured, the MVP tooling also reports whether the stack is ready for screenshot turns.

To stop the local stack later:

```bash
npm run mvp:stop
```

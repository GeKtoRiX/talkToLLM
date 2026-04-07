# realtime-api

FastAPI websocket orchestration service for the voice app prototype.

## Features

- `/ws` websocket endpoint for realtime control events and binary audio chunks
- in-memory session management
- explicit interruption and task cancellation
- provider abstraction layer for STT, LLM, and TTS
- mock providers enabled by default so the system works without external services
- `/healthz` and `/metrics`

## Environment

Copy `.env.example` to `.env` if you want to override defaults.

## Real Provider Mode

Install ROCm-enabled PyTorch first:

```bash
pip install --index-url https://download.pytorch.org/whl/rocm6.4 torch==2.9.1+rocm6.4
```

Then install the heavier optional dependencies with:

```bash
pip install -e ".[dev,real]"
```

Then configure:

```env
STT_PROVIDER=whisper_rocm
LLM_PROVIDER=lmstudio
TTS_PROVIDER=kokoro
LMSTUDIO_BASE_URL=http://localhost:1234/v1
LMSTUDIO_API_KEY=lm-studio
LLM_MODEL=gemma-4-e4b-it
STT_MODEL_ROOT=models/whisper
KOKORO_MODEL_ROOT=models/kokoro
KOKORO_DEVICE=cpu
```

Recommended first pass:

```env
STT_MODEL_SIZE=base.en
STT_DEVICE=auto
STT_ALLOW_CPU_FALLBACK=false
KOKORO_LANG_CODE=a
KOKORO_VOICE=af_heart
KOKORO_REPO_ID=hexgrad/Kokoro-82M
KOKORO_DEVICE=cpu
```

The API logs turn-level latency fields for:

- STT completion
- LLM first token
- TTS first audio
- end-to-end time to first audio

To materialize local STT/TTS assets directly into the repository, run:

```bash
. ../../.venv/bin/activate
python ../../scripts/prepare_local_models.py
```

This prepares both:

- `models/whisper/base.en.pt` for the ROCm Whisper backend
- `models/kokoro/*` assets for CPU Kokoro

To verify the ROCm path end-to-end, run:

```bash
. ../../.venv/bin/activate
PYTHONPATH=. python ../../scripts/check_whisper_rocm.py
```

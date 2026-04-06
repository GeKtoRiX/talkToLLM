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


# talkToLLM — Claude Code context

## What this project is

Real-time two-way voice conversation web app with a local LLM stack.
Monorepo: React + Vite frontend, FastAPI + Uvicorn backend, shared TypeScript contracts.

## Stack

| Layer    | Tech                                       | Port  |
|----------|--------------------------------------------|-------|
| Frontend | React 18 + Vite 6 + TypeScript 5.7         | 5173  |
| Backend  | FastAPI + Uvicorn (Python 3.12+)           | 8000  |
| STT      | Whisper (ROCm) — `whisper_rocm` provider   | —     |
| LLM      | LM Studio local server — `lmstudio` provider | 1234  |
| TTS      | Kokoro 82M — `kokoro` provider             | —     |

## Directory layout

```
apps/web/                        React + Vite frontend
  src/
    components/                  StatusPill, TranscriptPanel (+ *.test.tsx co-located)
    hooks/                       useVoiceSession.ts (session state, conversationHistory, playback)
    lib/                         playbackController, audioCapture, imageAttachments,
                                 sessionMachine (+ *.test.ts co-located)
    test/                        Integration tests: App.multimodal.test.tsx, setup.ts
libs/contracts/                  Shared TypeScript protocol (EventEnvelope, enums)
services/realtime-api/           FastAPI backend
  app/main.py                    Entry point, routes: /healthz /metrics /ws
  app/core/                      orchestrator, session_manager, state_machine, config
  app/providers/                 stt.py  llm.py  tts.py  factory.py
  tests/
    conftest.py                  Shared fixtures
    unit/                        test_state_machine, test_interruption, test_text,
                                 test_session_manager, test_config
    integration/                 test_websocket, test_orchestrator
    providers/                   test_llm_provider, test_mock_providers, test_factory
  .env                           Active config (real providers)
  .env.example                   Template with all options
scripts/
  stack/
    launch_desktop.sh            Main launcher — starts backend + frontend, live dashboard
    stop_stack.sh                Gracefully stops all managed processes + port fallback
  e2e/
    run_mvp_e2e.sh               E2E smoke test (starts stack if needed)
    e2e_live_check.py            Python E2E verifier (httpx + websockets)
  tools/
    check_whisper_rocm.py        ROCm + Whisper diagnostic
    prepare_local_models.py      Download Whisper + Kokoro model assets
desktop/
  talkToLLM.desktop              Linux .desktop shortcut (installed to ~/.local/share/applications/)
models/
  whisper/                       Whisper checkpoint (base.en.pt)
  kokoro/                        Kokoro weights + voice files
tmp/runtime/                     PID files + logs (created at launch, gitignored)
```

## Launch / stop

```bash
# Full real-stack launch (opens terminal dashboard)
npm run launch:desktop          # or: ./scripts/stack/launch_desktop.sh

# Stop everything (port-based fallback if PID files are missing)
npm run mvp:stop                # or: ./scripts/stack/stop_stack.sh

# E2E smoke test
npm run mvp:e2e

# Frontend only (dev)
npm run dev:web
```

The launcher auto-kills stale processes on ports 8000 / 5173 at startup (stage 0).

## Backend .env — active providers

```
LLM_PROVIDER=lmstudio        LLM_MODEL=gemma-4-e4b-it
STT_PROVIDER=whisper_rocm    STT_MODEL_SIZE=base.en
TTS_PROVIDER=kokoro          KOKORO_VOICE=af_heart
LMSTUDIO_BASE_URL=http://localhost:1234/v1
```

## WebSocket protocol

All messages are `EventEnvelope` JSON: `{ type: string, payload: object }`.
Types defined in `libs/contracts/src/index.ts` — `ClientEventType` / `ServerEventType`.
Binary frames carry raw PCM audio chunks from the browser AudioWorklet.

## Testing

```bash
# Frontend unit + integration tests (Vitest)  — 47 tests
npm run test:web

# Backend tests (pytest, all three tiers)     — 70 tests
cd services/realtime-api && ../../.venv/bin/pytest tests/ -v

# Full live E2E (requires live stack)
npm run mvp:e2e
```

Backend test tiers:
- `tests/unit/`        — state machine, interruption, text, session manager, config
- `tests/integration/` — WebSocket flows, orchestrator pipeline
- `tests/providers/`   — mock providers, factory, LM Studio message serialization

Frontend test layout:
- `src/lib/*.test.ts`          — sessionMachine, playbackController, imageAttachments
- `src/components/*.test.tsx`  — StatusPill, TranscriptPanel
- `src/test/`                  — App integration (multimodal screenshot flow)

## MCP server

`mcp_server.py` exposes project tools to Claude Code via `.claude/settings.json`.
Registered as server `talkToLLM` with 14 tools:

| Tool | Description |
|------|-------------|
| `stack_status` | Port + health check for backend & frontend |
| `start_stack` | Launch full stack in background |
| `stop_stack` | Kill all services (PID + port fallback) |
| `get_log` | Tail backend / frontend / launcher log |
| `get_env` | Read `.env` as key→value dict |
| `set_env` | Update a single key in `.env` |
| `list_lmstudio_models` | List models loaded in LM Studio |
| `backend_health` | Parse /healthz JSON |
| `run_backend_tests` | Run pytest (services/realtime-api) |
| `run_frontend_tests` | Run Vitest (apps/web) |
| `run_all_tests` | Run backend + frontend suites in sequence |
| `build_frontend` | tsc + vite build → apps/web/dist/ |
| `reinstall_desktop_shortcut` | Copy .desktop → ~/.local/share/applications/ |
| `run_e2e` | Execute e2e_live_check.py |

Dependencies: `mcp` installed via `.venv/bin/pip install mcp`.

## Key constraints

- Python venv lives at `.venv/` in the repo root; always use `.venv/bin/python` / `.venv/bin/uvicorn`.
- Backend must be started from repo root (`--app-dir services/realtime-api`).
- `set -Eeuo pipefail` in all shell scripts — every new script must follow this.
- The `.desktop` shortcut in `desktop/` must be re-installed to `~/.local/share/applications/` after edits.

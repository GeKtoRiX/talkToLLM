# talkToLLM — Claude Code context

## What this project is

Real-time two-way voice conversation web app with a local LLM stack.
Monorepo: React + Vite frontend, FastAPI + Uvicorn backend, shared TypeScript contracts.

## Stack

| Layer    | Tech                                         | Port |
| -------- | -------------------------------------------- | ---- |
| Frontend | React 18 + Vite 6 + TypeScript 5.7           | 5173 |
| Backend  | FastAPI + Uvicorn (Python 3.12+)             | 8000 |
| STT      | Whisper (ROCm) — `whisper_rocm` provider     | —    |
| LLM      | LM Studio local server — `lmstudio` provider | 1234 |
| TTS      | Kokoro 82M — `kokoro` provider               | —    |

## Directory layout

```
apps/web/                        React + Vite frontend
  src/
    components/                  StatusPill, TranscriptPanel, StudyPanel (+ *.test.tsx co-located)
      study/                     Training module components (types, api, exercises, session, results)
    hooks/                       useVoiceSession.ts (session state, conversationHistory, playback)
    lib/                         playbackController, audioCapture, imageAttachments,
                                 sessionMachine (+ *.test.ts co-located)
    test/                        Integration tests: App.multimodal.test.tsx, setup.ts
libs/contracts/                  Shared TypeScript protocol (EventEnvelope, enums)
services/realtime-api/           FastAPI backend
  app/main.py                    Entry point, routes: /healthz /metrics /ws /api/study/* /api/training/*
  app/core/                      orchestrator, session_manager, state_machine, config, logging, ocr
  app/providers/                 stt.py  llm.py  tts.py  factory.py
  app/study/                     Vocabulary SRS subsystem (Review + All Items tabs)
    db.py                        SQLite schema + get_db context manager (WAL mode)
    service.py                   StudyService: add_items, get_due, review_item, stats; apply_srs
    router.py                    FastAPI router: POST/GET /api/study/items|due|review|stats
  app/training/                  Active-recall training module (Training tab)
    db.py                        migrate_db(): extends study_items + creates 3 new tables
    models.py                    Pydantic schemas for sessions, questions, progress, stats
    progress.py                  Pure functions: normalize, check_answer, levenshtein,
                                 compute_srs_rating, check_mastery, compute_priority
    distractors.py               DistractorSelector — 4-tier pool selection
    service.py                   TrainingService: create_session, submit_answer, results
    router.py                    FastAPI router: /api/training/sessions|progress|stats|items
  tests/
    conftest.py                  Shared fixtures
    unit/                        test_state_machine, test_interruption, test_text,
                                 test_session_manager, test_config, test_logging,
                                 test_study_service, test_training_db, test_answer_checking,
                                 test_progress, test_distractors, test_training_service
    integration/                 test_websocket, test_orchestrator, test_study_endpoints,
                                 test_training_endpoints
    providers/                   test_llm_provider, test_mock_providers, test_factory
  .env                           Active config (real providers)
  .env.example                   Template with all options
data/
  study.sqlite                   Vocabulary SRS database (created at first run, gitignored)
scripts/
  stack/
    launch_desktop.sh            Main launcher — starts backend + frontend, live dashboard
    stop_stack.sh                Gracefully stops all managed processes + port fallback
  e2e/
    run_mvp_e2e.sh               E2E smoke test (starts stack if needed)
    e2e_live_check.py            Python E2E verifier (httpx + websockets)
  tools/
    check_whisper_rocm.py        ROCm + Whisper diagnostic
    prepare_local_models.py      Download Whisper + Kokoro assets (+ optional GOT-OCR-2.0)
desktop/
  talkToLLM.desktop              Linux .desktop shortcut (installed to ~/.local/share/applications/)
models/
  whisper/                       Whisper checkpoint (medium.en.pt)
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
STT_PROVIDER=whisper_rocm    STT_MODEL_SIZE=medium.en
TTS_PROVIDER=kokoro          KOKORO_VOICE=af_heart
LMSTUDIO_BASE_URL=http://localhost:1234/v1
OCR_BACKEND=tesseract        # "tesseract" | "auto" | "got_ocr2"
OCR_MAX_PATCHES=12           # GOT-OCR2 sub-patch count (higher = slower but denser)
OCR_MODEL_ROOT=models/ocr    # local GOT-OCR-2.0-hf weights cache
STT_TIMEOUT_SECONDS=30       # hard timeout on finalize_utterance(); raises TURN_FAILED on breach
AUDIO_BUFFER_MAX_BYTES=10000000  # 10 MB cap per turn; excess chunks are dropped
STUDY_DB_PATH=data/study.sqlite  # SQLite vocabulary database (relative to repo root)
```

## WebSocket protocol

All messages are `EventEnvelope` JSON: `{ type: string, payload: object }`.
Types defined in `libs/contracts/src/index.ts` — `ClientEventType` / `ServerEventType`.
Binary frames carry raw PCM audio chunks from the browser AudioWorklet.

## Testing

```bash
# Frontend unit + integration tests (Vitest)  — 107 tests
npm run test:web

# Backend tests (pytest, all three tiers)     — 362 tests
cd services/realtime-api && ../../.venv/bin/pytest tests/ -v

# Full live E2E (requires live stack)
npm run mvp:e2e
```

Backend test tiers:

- `tests/unit/` — state machine, interruption, text, session manager, config, ocr, logging, study service + SRS, **training DB migration, answer checking, progress logic, distractors, training service**
- `tests/integration/` — WebSocket flows, orchestrator pipeline (incl. STT timeout, OCR fallback), study REST endpoints, **training REST endpoints (full session flow)**
- `tests/providers/` — mock providers, factory, LM Studio message serialization

Frontend test layout:

- `src/lib/*.test.ts` — sessionMachine, playbackController, imageAttachments
- `src/components/*.test.tsx` — StatusPill, TranscriptPanel, StudyPanel
- `src/components/study/*.test.tsx` — **ExerciseMultipleChoice, ExerciseInput, SessionView, SessionResults, TrainingTab**
- `src/test/` — App integration (multimodal screenshot flow)

## MCP server

`mcp_server.py` exposes project tools to Claude Code via `.claude/settings.json`.
Registered as server `talkToLLM` with 23 tools:

### Stack tools

| Tool                         | Description                                               |
| ---------------------------- | --------------------------------------------------------- |
| `stack_status`               | Port + health check for backend & frontend                |
| `start_stack`                | Launch full stack in background                           |
| `stop_stack`                 | Kill all services (PID + port fallback)                   |
| `get_log`                    | Tail backend / frontend / launcher log                    |
| `get_env`                    | Read `.env` as key→value dict                             |
| `set_env`                    | Update a single key in `.env`                             |
| `list_lmstudio_models`       | List models loaded in LM Studio                           |
| `backend_health`             | Parse /healthz JSON                                       |
| `run_backend_tests`          | Run pytest (services/realtime-api)                        |
| `run_frontend_tests`         | Run Vitest (apps/web)                                     |
| `run_all_tests`              | Run backend + frontend suites in sequence                 |
| `build_frontend`             | tsc + vite build → apps/web/dist/                         |
| `reinstall_desktop_shortcut` | Copy .desktop → ~/.local/share/applications/              |
| `run_e2e`                    | Execute e2e_live_check.py (vision=True включает OCR-тест) |
| `ocr_check`                  | Smoke-тест OCR без запуска стека                          |

### Study tools (vocabulary SRS — Review/All Items tabs)

All study tools call `POST/GET http://127.0.0.1:8000/api/study/*` — the backend must be running.
Primary write path for saving vocabulary: use these tools from Claude Code during or after a session.

| Tool                    | Description                                                                            |
| ----------------------- | -------------------------------------------------------------------------------------- |
| `study_add_items`       | Save word/phrase/phrasal_verb/idiom/collocation items to the study DB                  |
| `study_extract_and_save`| Extract vocabulary from a conversation exchange via LM Studio structured output + save |
| `study_list_due`        | List items currently due for SRS review                                                |
| `study_review_item`     | Submit a rating (again/hard/good/easy) for one item                                    |
| `study_stats`           | Return per-status counts, due queue size, total reviews                                |

#### `study_extract_and_save` details

Takes `user_text` + `assistant_text`, calls LM Studio in structured-output mode to extract
candidate vocabulary items (words, phrases, phrasal verbs, idioms, collocations), then saves
non-duplicate entries. Extraction is **explicit-save only** — it is never called automatically
during live turns.

Dependencies: `mcp` installed via `.venv/bin/pip install mcp`.

### Training tools (active-recall Training tab)

All training tools call `POST/GET http://127.0.0.1:8000/api/training/*`.

| Tool                    | Description                                                    |
| ----------------------- | -------------------------------------------------------------- |
| `training_create_session` | Start a training session (mode, filters, target_count)       |
| `training_get_results`    | Get results for a completed session by ID                    |
| `training_user_stats`     | Global mastery/progress statistics across all vocabulary     |

## Backend logging system

All backend logs are emitted as single-line JSON via `app/core/logging.py`.

Key primitives:

- **`JsonFormatter`** — every record includes `timestamp`, `level`, `logger`, `source` (file:line),
  `message`, and any extra fields. Exceptions are serialised as `exc_type` / `exc_message` / `traceback`.
- **`BoundLogger`** — wraps `logging.Logger` with pre-bound context (`session_id`, `turn_id`).
  Use `log.bind(pipeline_step="stt")` to create a child without mutating the parent.
- **`log_stage(log, step, **extra)`** — context manager; logs `step.start` / `step.end` with
  `elapsed_ms` and yields a `meta` dict that is populated with `elapsed_ms` after the block.

Pipeline event taxonomy (searchable via `event` field):

```
session.created / session.closed
ws.connected / ws.disconnected / ws.event.received
turn.start / turn.completed / turn.cancelled / turn.failed / turn.cleanup
stt.start / stt.end / stt.timeout / stt.skip
ocr.start / ocr.end / ocr.attachment.ok / ocr.attachment.failed / ocr.fallback
vision.bypass_ocr
llm.stream.start / llm.first_token / llm.delta / llm.stream.end / llm.stream.interrupted
llm.request.start / llm.request.end / llm.cancel / llm.client.created
tts.start / tts.first_audio / tts.chunk.sent / tts.end / tts.interrupted
playback.interrupt
audio.chunk.appended / audio.buffer.overflow / audio.buffer.partial_overflow
```

## Vocabulary study subsystem

The study subsystem is a parallel, non-realtime system that shares the same process as the voice
backend but does not touch the WebSocket turn pipeline.

### Architecture

```
MCP tools (mcp_server.py)
    │  HTTP POST/GET
    ▼
FastAPI /api/study/*  ──► StudyService  ──► data/study.sqlite
FastAPI /api/training/* ─► TrainingService ─► (same DB, new tables)
    ▲
    │  fetch()
StudyPanel (React) — 3 tabs: Review | All Items | Training
```

### UI capabilities

- `Review` tab — SRS due queue, answer flip, Again / Hard / Good / Easy ratings
- `All Items` tab — full list with inline edit/delete controls, bulk add form
- `Training` tab — active-recall sessions with 4 exercise types (see below)

### REST API — SRS (backend port 8000)

| Method | Path                        | Description                              |
| ------ | --------------------------- | ---------------------------------------- |
| POST   | `/api/study/items`          | Bulk-insert items; silently skips dupes  |
| GET    | `/api/study/items`          | List items (filters: status, item_type, lexical_type, topic, difficulty_min/max) |
| PATCH  | `/api/study/items/{id}`     | Update a single item's fields or status  |
| DELETE | `/api/study/items/{id}`     | Delete an item                           |
| GET    | `/api/study/due`            | Due queue ordered new→learning→review    |
| POST   | `/api/study/review/{id}`    | Submit rating; returns updated item      |
| GET    | `/api/study/stats`          | Counts per status + due + total reviews  |

### REST API — Training (backend port 8000)

| Method | Path                                   | Description                                    |
| ------ | -------------------------------------- | ---------------------------------------------- |
| POST   | `/api/training/sessions`               | Create session → `{session, question\|null}`   |
| GET    | `/api/training/sessions/{id}`          | Get session state + current question           |
| POST   | `/api/training/sessions/{id}/answer`   | Submit answer → `AnswerResult`                 |
| POST   | `/api/training/sessions/{id}/complete` | Force-complete → `SessionResults`              |
| GET    | `/api/training/sessions/{id}/results`  | Fetch results for completed session            |
| GET    | `/api/training/progress/{item_id}`     | Per-item detailed progress                     |
| GET    | `/api/training/stats/user`             | Global mastery stats                           |
| GET    | `/api/training/items`                  | Filtered item list for training                |

### Database tables (`data/study.sqlite`)

- **`study_items`** — one row per memorisation unit. SRS fields: `ease`, `interval_days`,
  `repetitions`, `lapses`, `next_review_at`. Status: `new|learning|review|mastered|difficult|suspended`.
  Item type: `word|phrase|phrasal_verb|idiom|collocation`. Extended fields added by training migration:
  `lexical_type`, `alternative_translations` (JSON), `topic`, `difficulty_level`, `tags` (JSON),
  `example_sentence_native`.
- **`review_events`** — immutable log of every review answer with before/after SRS values.
- **`study_sessions`** — optional grouping rows (legacy, not used by the training module).
- **`item_progress`** — per-item training statistics: streaks, active_recall_successes, weighted_score,
  mastery flag + timestamp, difficulty flag.
- **`training_sessions`** — one row per training session: mode, filters, status, correct/wrong counts,
  newly mastered/difficult/error item ID lists.
- **`session_questions`** — ordered question queue for each session: exercise_type, direction,
  correct_answer, distractors_json, prompt_text, answer_given, is_correct.

Deduplication key: `normalize(target_text) + item_type + language_target + language_native`.

### Training module — key algorithms

**4 exercise types** (all dispatched through `SessionView`):

| Type      | Prompt               | Input       | Direction |
| --------- | -------------------- | ----------- | --------- |
| `mc`      | EN word/phrase       | 4 buttons   | en→ru     |
| `input`   | RU translation       | text field  | ru→en     |
| `context` | sentence + 4 options | button      | en in ctx |
| `fill`    | sentence with ___    | text field  | en        |

**Answer checking** (3-tier, `progress.py::check_answer`):
1. Exact match after NFKC-casefold normalisation + all `alternative_translations`
2. Levenshtein ≤ 2 for strings longer than 5 chars → correct with `"spelling"` error_type
3. All key words present → correct with `"partial"` error_type

**Mastery criteria** (`progress.py::check_mastery`):
- `times_shown ≥ 5`, accuracy ≥ 85%, `current_correct_streak ≥ 3`, `active_recall_successes ≥ 2`

**Exercise weights**: `mc=1.0`, `input=1.5`, `context=1.3`, `fill=1.7`

**Distractor selection** — 4 tiers: same lexical_type+item_type → same lexical_type →
same item_type → anything; padded to 3 with `["—", "not applicable", "none of these"]`.

### SRS algorithm (SM-2 variant)

| Rating | Ease delta | Interval rule                               | Status after      |
| ------ | ---------- | ------------------------------------------- | ----------------- |
| again  | −0.20      | reset to 1 day; repetitions → 0; lapse +1  | learning          |
| hard   | −0.15      | × 1.2                                       | learning / review |
| good   | —          | 1 → 4 → × ease                             | learning / review |
| easy   | +0.15      | 4 → 7 → × ease × 1.3                       | review            |

Minimum ease: 1.3.  Transitions to `review` once repetitions ≥ 3.

### Config

`STUDY_DB_PATH=data/study.sqlite` in `.env` (relative to repo root, resolved via `AppSettings.study_db_path_resolved`).
The training module uses the same DB path; `migrate_db()` is called at startup and is idempotent.

## Key constraints

- Python venv lives at `.venv/` in the repo root; always use `.venv/bin/python` / `.venv/bin/uvicorn`.
- Backend must be started from repo root (`--app-dir services/realtime-api`).
- `set -Eeuo pipefail` in all shell scripts — every new script must follow this.
- The `.desktop` shortcut in `desktop/` must be re-installed to `~/.local/share/applications/` after edits.
- `item_type='sentence'` was removed from the schema in the training migration; all legacy rows were migrated to `item_type='phrase'`.

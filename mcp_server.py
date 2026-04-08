#!/usr/bin/env python3
"""
talkToLLM MCP server — exposes project tools to Claude Code.

Tools:
  stack_status             Check if backend + frontend are running
  start_stack              Launch the full real stack (background)
  stop_stack               Stop all managed services
  get_log                  Tail a log file (backend / frontend / launcher)
  get_env                  Read current backend .env configuration
  set_env                  Update a single key in backend .env
  list_lmstudio_models     List models loaded in LM Studio
  backend_health           Call /healthz on the backend
  run_backend_tests        Run pytest for the FastAPI service
  run_frontend_tests       Run Vitest for the React app
  run_all_tests            Run backend + frontend tests in sequence
  build_frontend           Build the React frontend production bundle
  reinstall_desktop_shortcut  Copy .desktop file to ~/.local/share/applications/
  run_e2e                  Run the live E2E verification suite
  ocr_check                Smoke-test the OCR pipeline with a generated fixture image
"""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.resolve()
RUNTIME_DIR = REPO_ROOT / "tmp" / "runtime"
ENV_FILE = REPO_ROOT / "services" / "realtime-api" / ".env"
LAUNCHER_SCRIPT = REPO_ROOT / "scripts" / "stack" / "launch_desktop.sh"
STOP_SCRIPT = REPO_ROOT / "scripts" / "stack" / "stop_stack.sh"
E2E_SCRIPT = REPO_ROOT / "scripts" / "e2e" / "e2e_live_check.py"
PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
UVICORN = REPO_ROOT / ".venv" / "bin" / "uvicorn"
NPM = "npm"

BACKEND_HEALTH_URL = "http://127.0.0.1:8000/healthz"
BACKEND_METRICS_URL = "http://127.0.0.1:8000/metrics"
FRONTEND_URL = "http://127.0.0.1:5173"

LOG_FILES = {
    "backend": RUNTIME_DIR / "backend.log",
    "frontend": RUNTIME_DIR / "frontend.log",
    "launcher": RUNTIME_DIR / "launcher.log",
}

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "talkToLLM",
    instructions=textwrap.dedent("""\
        Tools for managing and inspecting the talkToLLM voice-chat stack:
        backend (FastAPI/Uvicorn on :8000), frontend (Vite/React on :5173),
        and local providers: LM Studio (LLM), Whisper ROCm (STT), Kokoro (TTS).
    """),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _http_get(url: str, timeout: float = 4.0) -> tuple[bool, str]:
    """Returns (ok, text_or_error)."""
    try:
        r = httpx.get(url, timeout=timeout)
        r.raise_for_status()
        return True, r.text
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _is_port_listening(port: int) -> bool:
    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return bool(result.stdout.strip())
    except Exception:  # noqa: BLE001
        return False


def _read_env() -> dict[str, str]:
    """Parse .env into an ordered dict, preserving comments as-is internally."""
    result: dict[str, str] = {}
    if not ENV_FILE.exists():
        return result
    for line in ENV_FILE.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        result[key.strip()] = value.strip().strip("\"'")
    return result


def _write_env_key(key: str, value: str) -> None:
    """Update or append a single KEY=VALUE pair in .env."""
    text = ENV_FILE.read_text() if ENV_FILE.exists() else ""
    pattern = re.compile(rf"^({re.escape(key)}\s*=).*$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(rf"\g<1>{value}", text)
    else:
        text = text.rstrip("\n") + f"\n{key}={value}\n"
    ENV_FILE.write_text(text)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def stack_status() -> dict:
    """
    Check whether backend and frontend are currently running.

    Returns a dict with:
      backend_port   — True if port 8000 is listening
      frontend_port  — True if port 5173 is listening
      backend_health — JSON body from /healthz, or an error string
      lmstudio       — True/False: LM Studio models endpoint reachable
    """
    env = _read_env()
    lmstudio_url = env.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1").rstrip("/")
    lmstudio_ok, _ = _http_get(f"{lmstudio_url}/models")

    backend_up, health_body = _http_get(BACKEND_HEALTH_URL)

    return {
        "backend_port": _is_port_listening(8000),
        "frontend_port": _is_port_listening(5173),
        "backend_health": health_body if backend_up else f"DOWN: {health_body}",
        "lmstudio": lmstudio_ok,
    }


@mcp.tool()
def start_stack() -> str:
    """
    Launch the full talkToLLM stack in the background (non-blocking).

    Uses TALKTOLLM_NO_CLEAR=1 TALKTOLLM_DASHBOARD=0 TALKTOLLM_NOTIFY=0
    so the launcher runs in automation mode without a terminal dashboard.

    Logs go to tmp/runtime/launcher.log, backend.log, frontend.log.
    Returns the launcher PID.
    """
    if not LAUNCHER_SCRIPT.exists():
        return f"ERROR: launcher not found at {LAUNCHER_SCRIPT}"

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    log_path = RUNTIME_DIR / "launcher.log"

    env = {
        **os.environ,
        "TALKTOLLM_NO_CLEAR": "1",
        "TALKTOLLM_DASHBOARD": "0",
        "TALKTOLLM_NOTIFY": "0",
    }
    with log_path.open("ab") as log_fh:
        proc = subprocess.Popen(
            ["bash", str(LAUNCHER_SCRIPT)],
            stdout=log_fh,
            stderr=log_fh,
            env=env,
            cwd=str(REPO_ROOT),
            start_new_session=True,
        )
    return f"Launcher started with PID {proc.pid}. Follow: tail -f {log_path}"


@mcp.tool()
def stop_stack() -> str:
    """
    Stop all managed services (backend + frontend).

    Kills by PID file first, then falls back to killing by port.
    Returns the combined stdout/stderr of stop_stack.sh.
    """
    result = subprocess.run(
        ["bash", str(STOP_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=15,
    )
    output = (result.stdout + result.stderr).strip()
    return output or "(no output)"


@mcp.tool()
def get_log(service: str = "backend", lines: int = 50) -> str:
    """
    Return the last N lines from a service log file.

    Args:
      service: one of "backend", "frontend", "launcher"  (default: "backend")
      lines:   number of tail lines to return             (default: 50, max: 500)
    """
    service = service.lower()
    if service not in LOG_FILES:
        return f"Unknown service '{service}'. Choose from: {', '.join(LOG_FILES)}"

    lines = max(1, min(lines, 500))
    log_path = LOG_FILES[service]

    if not log_path.exists():
        return f"(log file not found: {log_path})"
    if log_path.stat().st_size == 0:
        return "(log file is empty)"

    result = subprocess.run(
        ["tail", "-n", str(lines), str(log_path)],
        capture_output=True,
        text=True,
    )
    return result.stdout or "(empty output)"


@mcp.tool()
def get_env() -> dict[str, str]:
    """
    Read the backend .env configuration and return it as a key→value dict.

    Sensitive tokens (API keys) are shown as-is since this is a local dev tool.
    """
    if not ENV_FILE.exists():
        return {"error": f"{ENV_FILE} not found"}
    return _read_env()


@mcp.tool()
def set_env(key: str, value: str) -> str:
    """
    Set a single KEY=VALUE pair in the backend .env file.

    Creates the key if it doesn't exist; updates it in-place if it does.
    The stack must be restarted for changes to take effect.

    Args:
      key:   environment variable name (e.g. "LLM_MODEL")
      value: new value (unquoted; will be stored as-is)
    """
    if not key or not re.match(r"^[A-Z_][A-Z0-9_]*$", key):
        return f"ERROR: invalid key '{key}'. Must be uppercase letters/digits/underscores."
    _write_env_key(key, value)
    return f"Updated {ENV_FILE.name}: {key}={value}"


@mcp.tool()
def list_lmstudio_models() -> dict:
    """
    Query the LM Studio local server for loaded models.

    Returns a dict with:
      ok:     bool
      models: list of model IDs currently loaded
      error:  error string if the call failed
    """
    env = _read_env()
    base_url = env.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1").rstrip("/")
    ok, body = _http_get(f"{base_url}/models", timeout=5)
    if not ok:
        return {"ok": False, "models": [], "error": body}
    try:
        import json
        data = json.loads(body)
        ids = [m.get("id", "?") for m in data.get("data", [])]
        return {"ok": True, "models": ids}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "models": [], "error": str(exc)}


@mcp.tool()
def backend_health() -> dict:
    """
    Call the backend /healthz endpoint and return the parsed JSON response.
    """
    ok, body = _http_get(BACKEND_HEALTH_URL, timeout=5)
    if not ok:
        return {"status": "down", "error": body}
    try:
        import json
        return json.loads(body)
    except Exception:  # noqa: BLE001
        return {"status": "unknown", "raw": body}


@mcp.tool()
def run_backend_tests(extra_args: str = "") -> str:
    """
    Run the pytest suite for the FastAPI service.

    Args:
      extra_args: optional extra flags for pytest
                  (e.g. "-k test_state_machine -v")

    Returns the combined stdout + stderr of the test run.
    """
    cmd = [str(PYTHON), "-m", "pytest", "tests/"]
    if extra_args:
        cmd += extra_args.split()

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT / "services" / "realtime-api"),
        timeout=120,
    )
    return (result.stdout + result.stderr).strip() or "(no output)"


@mcp.tool()
def run_frontend_tests(extra_args: str = "") -> str:
    """
    Run the Vitest unit-test suite for the React frontend.

    Args:
      extra_args: optional extra flags (e.g. "--reporter=verbose")

    Returns combined stdout + stderr.
    """
    cmd = [NPM, "run", "test:web", "--"]
    if extra_args:
        cmd += extra_args.split()

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=120,
        env={**os.environ, "CI": "true"},
    )
    return (result.stdout + result.stderr).strip() or "(no output)"


@mcp.tool()
def run_all_tests(backend_args: str = "", frontend_args: str = "") -> str:
    """
    Run the full test suite: backend pytest (84 tests) then frontend Vitest (47 tests).

    Args:
      backend_args:  extra flags forwarded to pytest  (e.g. "-k test_config -v")
      frontend_args: extra flags forwarded to vitest  (e.g. "--reporter=verbose")

    Returns a combined report with pass/fail counts for each suite.
    """
    sections: list[str] = []

    be_cmd = [str(PYTHON), "-m", "pytest", "tests/"]
    if backend_args:
        be_cmd += backend_args.split()
    be = subprocess.run(
        be_cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT / "services" / "realtime-api"),
        timeout=180,
    )
    sections.append("── Backend (pytest) ──")
    sections.append((be.stdout + be.stderr).strip() or "(no output)")

    fe_cmd = [NPM, "run", "test:web", "--"]
    if frontend_args:
        fe_cmd += frontend_args.split()
    fe = subprocess.run(
        fe_cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=120,
        env={**os.environ, "CI": "true"},
    )
    sections.append("\n── Frontend (vitest) ──")
    sections.append((fe.stdout + fe.stderr).strip() or "(no output)")

    overall = "ALL PASSED" if be.returncode == 0 and fe.returncode == 0 else "FAILURES DETECTED"
    sections.insert(0, f"=== {overall} ===\n")
    return "\n".join(sections)


@mcp.tool()
def build_frontend() -> str:
    """
    Build the React frontend production bundle (tsc + vite build → apps/web/dist/).

    Returns combined stdout + stderr of the build.
    """
    result = subprocess.run(
        [NPM, "run", "build:web"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=120,
    )
    return (result.stdout + result.stderr).strip() or "(no output)"


@mcp.tool()
def reinstall_desktop_shortcut() -> str:
    """
    Copy desktop/talkToLLM.desktop → ~/.local/share/applications/ and
    refresh the desktop database so the launcher appears in app menus.

    Call this after editing the .desktop file or scripts/stack/launch_desktop.sh path.
    """
    src = REPO_ROOT / "desktop" / "talkToLLM.desktop"
    dst_dir = Path.home() / ".local" / "share" / "applications"

    if not src.exists():
        return f"ERROR: {src} not found"

    dst_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(src, dst_dir / src.name)

    result = subprocess.run(
        ["update-desktop-database", str(dst_dir)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return f"Copied to {dst_dir} but update-desktop-database failed: {result.stderr.strip()}"
    return f"Installed to {dst_dir / src.name}"


@mcp.tool()
def run_e2e(vision: bool = False) -> str:
    """
    Execute the live end-to-end verification script (e2e_live_check.py).

    Requires the stack to already be running (use start_stack first).

    Args:
      vision: if True, also runs the screenshot/OCR turn check
              (sets TALKTOLLM_VISION_E2E=1).  Default: False.

    Returns combined stdout + stderr of the E2E run.
    """
    env = {**os.environ}
    if vision:
        env["TALKTOLLM_VISION_E2E"] = "1"

    result = subprocess.run(
        [str(PYTHON), str(E2E_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=300,
    )
    return (result.stdout + result.stderr).strip() or "(no output)"


@mcp.tool()
def ocr_check(image_path: str = "") -> str:
    """
    Smoke-test the OCR pipeline without requiring the full stack.

    Args:
      image_path: optional path to an existing image file to run OCR on.
                  Defaults to test_img.png in the repo root if it exists,
                  otherwise generates a synthetic 640×320 "HELLO OCR" fixture.

    Returns the extracted text. Useful to confirm Tesseract + Pillow work
    correctly before running a full E2E.
    """
    resolved = Path(image_path) if image_path else (REPO_ROOT / "test_img.png")

    if resolved.exists():
        # Run OCR directly on the provided image file
        script = textwrap.dedent(f"""
            import sys, base64
            sys.path.insert(0, "services/realtime-api")
            from app.core.ocr import extract_text_from_image
            data_b64 = base64.b64encode(open({str(resolved)!r}, "rb").read()).decode()
            result = extract_text_from_image(data_b64)
            print(repr(result))
        """)
    else:
        # Fallback: generate a synthetic "HELLO OCR" fixture
        script = textwrap.dedent("""
            import sys, base64, io
            sys.path.insert(0, "services/realtime-api")

            from PIL import Image, ImageDraw, ImageFont
            from app.core.ocr import extract_text_from_image

            img = Image.new("RGB", (640, 320), "white")
            draw = ImageDraw.Draw(img)
            font = None
            for candidate in (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
            ):
                try:
                    font = ImageFont.truetype(candidate, 96)
                    break
                except Exception:
                    pass
            if font is None:
                font = ImageFont.load_default()

            text = "HELLO OCR"
            bbox = draw.textbbox((0, 0), text, font=font)
            x = (640 - (bbox[2] - bbox[0])) // 2
            y = (320 - (bbox[3] - bbox[1])) // 2
            draw.text((x, y), text, fill="black", font=font)

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            data_b64 = base64.b64encode(buf.getvalue()).decode()

            result = extract_text_from_image(data_b64)
            print(repr(result))
        """)

    result = subprocess.run(
        [str(PYTHON), "-c", script],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
    )
    if result.returncode != 0:
        return f"FAILED\nstdout: {result.stdout}\nstderr: {result.stderr}"
    extracted = result.stdout.strip()
    if resolved.exists() and not image_path:
        # test_img.png is a textbook page — OCR reliably extracts "personal information"
        ok = "personal" in extracted.lower() or "vocabulary" in extracted.lower() or "greetings" in extracted.lower()
    else:
        ok = "hello" in extracted.lower() or "ocr" in extracted.lower()
    status = "PASS" if ok else "WARN — unexpected output"
    return f"{status}\nImage: {resolved}\nExtracted text: {extracted}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run()

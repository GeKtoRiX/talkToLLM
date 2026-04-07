#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_DIR="${REPO_ROOT}/tmp/runtime"
ENV_FILE="${REPO_ROOT}/services/realtime-api/.env"
ENV_EXAMPLE="${REPO_ROOT}/services/realtime-api/.env.example"
LAUNCHER_SCRIPT="${REPO_ROOT}/scripts/launch_desktop.sh"
E2E_SCRIPT="${REPO_ROOT}/scripts/e2e_live_check.py"
START_LOG="${RUNTIME_DIR}/mvp-e2e-start.log"

LAUNCHER_PID=""
STARTED_BY_SCRIPT=0

log() {
  printf '[mvp-e2e] %s\n' "$1"
}

is_http_ready() {
  local url="$1"
  curl -fsS --max-time 2 "${url}" >/dev/null 2>&1
}

process_is_running() {
  local pid="$1"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

read_pid_file() {
  local pid_file="$1"
  if [[ -f "${pid_file}" ]]; then
    tr -d '[:space:]' <"${pid_file}"
  fi
}

stop_launcher() {
  local pid="$1"
  if process_is_running "${pid}"; then
    log "Stopping failed launcher process group ${pid}"
    kill -- "-${pid}" 2>/dev/null || kill "${pid}" 2>/dev/null || true
  fi
}

cleanup_on_failure() {
  local exit_code="$1"
  if [[ "${exit_code}" -ne 0 && "${STARTED_BY_SCRIPT}" -eq 1 && -n "${LAUNCHER_PID}" ]]; then
    stop_launcher "${LAUNCHER_PID}"
  fi
}

trap 'cleanup_on_failure $?' EXIT

mkdir -p "${RUNTIME_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
  log "No local backend .env found; creating one from .env.example"
  cp "${ENV_EXAMPLE}" "${ENV_FILE}"
fi

if is_http_ready "http://127.0.0.1:8000/healthz" && is_http_ready "http://127.0.0.1:5173"; then
  log "Existing stack detected; reusing the running backend/frontend"
else
  log "Starting launcher in automation mode"
  TALKTOLLM_NO_CLEAR=1 TALKTOLLM_DASHBOARD=0 TALKTOLLM_NOTIFY=0 "${LAUNCHER_SCRIPT}" >"${START_LOG}" 2>&1 &
  LAUNCHER_PID="$!"
  STARTED_BY_SCRIPT=1
  log "Launcher started with process group ${LAUNCHER_PID}"

  for _ in $(seq 1 90); do
    if is_http_ready "http://127.0.0.1:8000/healthz" && is_http_ready "http://127.0.0.1:5173"; then
      break
    fi
    if ! process_is_running "${LAUNCHER_PID}"; then
      log "Launcher exited early. Recent output:"
      sed -n '1,200p' "${START_LOG}" || true
      exit 1
    fi
    sleep 1
  done

  if ! is_http_ready "http://127.0.0.1:8000/healthz" || ! is_http_ready "http://127.0.0.1:5173"; then
    log "Stack did not become ready in time. Recent launcher output:"
    sed -n '1,200p' "${START_LOG}" || true
    exit 1
  fi
fi

log "Running live E2E verification"
"${REPO_ROOT}/.venv/bin/python" "${E2E_SCRIPT}"

if [[ "${STARTED_BY_SCRIPT}" -eq 1 ]]; then
  LAUNCHER_PID="$(read_pid_file "${RUNTIME_DIR}/launcher.pid")"
  log "E2E passed. Stack is still running."
  log "Launcher PID: ${LAUNCHER_PID:-unknown}"
else
  log "E2E passed against the already running stack."
fi

log "Web UI: http://127.0.0.1:5173"
log "Backend health: http://127.0.0.1:8000/healthz"
log "Metrics: http://127.0.0.1:8000/metrics"
log "To stop the stack later: ${REPO_ROOT}/scripts/stop_stack.sh"

#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RUNTIME_DIR="${REPO_ROOT}/tmp/runtime"

read_pid_file() {
  local pid_file="$1"
  if [[ -f "${pid_file}" ]]; then
    tr -d '[:space:]' <"${pid_file}"
  fi
}

process_is_running() {
  local pid="$1"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

stop_pid_group() {
  local label="$1"
  local pid="$2"
  if [[ -z "${pid}" ]]; then
    return
  fi

  if process_is_running "${pid}"; then
    printf '[stop-stack] stopping %s process group %s\n' "${label}" "${pid}"
    kill -- "-${pid}" 2>/dev/null || kill "${pid}" 2>/dev/null || true
  fi
}

LAUNCHER_PID="$(read_pid_file "${RUNTIME_DIR}/launcher.pid")"
BACKEND_PID="$(read_pid_file "${RUNTIME_DIR}/backend.pid")"
FRONTEND_PID="$(read_pid_file "${RUNTIME_DIR}/frontend.pid")"

stop_pid_group "launcher" "${LAUNCHER_PID}"
sleep 1
stop_pid_group "frontend" "${FRONTEND_PID}"
stop_pid_group "backend" "${BACKEND_PID}"

# Fallback: kill by port in case PID files were absent or stale
kill_port_processes() {
  local label="$1"
  local port="$2"
  local pids
  pids="$(lsof -nP -iTCP:"${port}" -sTCP:LISTEN -t 2>/dev/null || true)"
  [[ -z "${pids}" ]] && return
  printf '[stop-stack] killing stale %s process(es) on port %s: %s\n' "${label}" "${port}" "${pids//$'\n'/ }"
  while IFS= read -r pid; do
    [[ -z "${pid}" ]] && continue
    kill -- "-${pid}" 2>/dev/null || kill "${pid}" 2>/dev/null || true
  done <<<"${pids}"
}

kill_port_processes "backend" 8000
kill_port_processes "frontend" 5173

rm -f "${RUNTIME_DIR}/launcher.pid" "${RUNTIME_DIR}/backend.pid" "${RUNTIME_DIR}/frontend.pid"
printf '[stop-stack] done\n'

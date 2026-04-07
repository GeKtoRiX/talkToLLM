#!/usr/bin/env bash

set -Eeuo pipefail

CURRENT_STAGE="startup"
FAILURE_REASON=""
SHUTDOWN_REASON=""
REPO_ROOT=""
SCRIPT_DIR=""
RUNTIME_DIR=""
LAUNCHER_LOG=""
BACKEND_LOG=""
FRONTEND_LOG=""
BACKEND_PID_FILE=""
FRONTEND_PID_FILE=""
BACKEND_PID=""
FRONTEND_PID=""
STOP_REQUESTED=0
CLEANUP_DONE=0
SHUTDOWN_REASON_LOGGED=0
LMSTUDIO_MODELS_URL=""
LMSTUDIO_PORT=""
API_PORT=8000
WEB_PORT=5173
WEB_URL="http://127.0.0.1:${WEB_PORT}"
BACKEND_HEALTH_URL="http://127.0.0.1:${API_PORT}/healthz"
BACKEND_METRICS_URL="http://127.0.0.1:${API_PORT}/metrics"
MONITOR_INTERVAL="${TALKTOLLM_MONITOR_INTERVAL:-2}"
MAX_MONITOR_TICKS="${TALKTOLLM_MAX_MONITOR_TICKS:-0}"
NO_CLEAR="${TALKTOLLM_NO_CLEAR:-0}"
DASHBOARD_ENABLED="${TALKTOLLM_DASHBOARD:-1}"
NOTIFY_ENABLED="${TALKTOLLM_NOTIFY:-1}"
LAUNCHER_PID_FILE=""

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

strip_wrapping_quotes() {
  local value="$1"
  if [[ ${#value} -ge 2 ]]; then
    if [[ ${value:0:1} == "\"" && ${value: -1} == "\"" ]]; then
      printf '%s' "${value:1:${#value}-2}"
      return
    fi
    if [[ ${value:0:1} == "'" && ${value: -1} == "'" ]]; then
      printf '%s' "${value:1:${#value}-2}"
      return
    fi
  fi
  printf '%s' "$value"
}

log_line() {
  local message="$1"
  local timestamp
  timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
  printf '[%s] %s\n' "$timestamp" "$message"
  if [[ -n "${LAUNCHER_LOG}" ]]; then
    printf '[%s] %s\n' "$timestamp" "$message" >>"$LAUNCHER_LOG"
  fi
}

set_stage() {
  CURRENT_STAGE="$1"
  log_line "Stage: ${CURRENT_STAGE}"
}

notify_user() {
  local message="$1"
  if [[ "${NOTIFY_ENABLED}" == "0" ]]; then
    return
  fi
  if command -v notify-send >/dev/null 2>&1; then
    notify-send "talkToLLM launcher" "$message" >/dev/null 2>&1 || true
  fi
}

handle_error() {
  local exit_code="$1"
  local line_no="$2"
  local command="$3"

  if [[ "${STOP_REQUESTED}" -eq 1 ]]; then
    return
  fi

  if [[ -z "${FAILURE_REASON}" ]]; then
    FAILURE_REASON="Stage '${CURRENT_STAGE}' failed at line ${line_no} while running: ${command}"
  fi

  log_line "ERROR: ${FAILURE_REASON}"
  notify_user "Launch failed: ${FAILURE_REASON}"
  exit "${exit_code}"
}

handle_signal() {
  local signal_name="$1"
  STOP_REQUESTED=1
  SHUTDOWN_REASON="Received ${signal_name}; stopping managed services."
  log_line "${SHUTDOWN_REASON}"
  SHUTDOWN_REASON_LOGGED=1
  exit 130
}

cleanup() {
  if [[ "${CLEANUP_DONE}" -eq 1 ]]; then
    return
  fi
  CLEANUP_DONE=1

  stop_managed_process "frontend" "${FRONTEND_PID_FILE:-}" "${FRONTEND_PID:-}"
  stop_managed_process "backend" "${BACKEND_PID_FILE:-}" "${BACKEND_PID:-}"
  [[ -n "${LAUNCHER_PID_FILE}" ]] && rm -f "${LAUNCHER_PID_FILE}"

  if [[ -n "${SHUTDOWN_REASON}" && "${SHUTDOWN_REASON_LOGGED}" -eq 0 ]]; then
    log_line "${SHUTDOWN_REASON}"
  fi
}

trap 'handle_error $? ${LINENO} "${BASH_COMMAND}"' ERR
trap 'handle_signal INT' INT
trap 'handle_signal TERM' TERM
trap cleanup EXIT

resolve_repo_root() {
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
}

initialize_runtime_paths() {
  RUNTIME_DIR="${REPO_ROOT}/tmp/runtime"
  mkdir -p "${RUNTIME_DIR}"

  LAUNCHER_LOG="${RUNTIME_DIR}/launcher.log"
  BACKEND_LOG="${RUNTIME_DIR}/backend.log"
  FRONTEND_LOG="${RUNTIME_DIR}/frontend.log"
  LAUNCHER_PID_FILE="${RUNTIME_DIR}/launcher.pid"
  BACKEND_PID_FILE="${RUNTIME_DIR}/backend.pid"
  FRONTEND_PID_FILE="${RUNTIME_DIR}/frontend.pid"

  : >"${LAUNCHER_LOG}"
  : >"${BACKEND_LOG}"
  : >"${FRONTEND_LOG}"
  printf '%s\n' "$$" >"${LAUNCHER_PID_FILE}"
  rm -f "${BACKEND_PID_FILE}" "${FRONTEND_PID_FILE}"
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

stop_managed_process() {
  local label="$1"
  local pid_file="$2"
  local known_pid="$3"
  local pid="${known_pid}"

  if [[ -z "${pid}" && -n "${pid_file}" ]]; then
    pid="$(read_pid_file "${pid_file}")"
  fi

  if [[ -z "${pid}" ]]; then
    [[ -n "${pid_file}" ]] && rm -f "${pid_file}"
    return
  fi

  if process_is_running "${pid}"; then
    log_line "Stopping ${label} process group ${pid}"
    kill -- "-${pid}" 2>/dev/null || kill "${pid}" 2>/dev/null || true
    for _ in $(seq 1 20); do
      if ! process_is_running "${pid}"; then
        break
      fi
      sleep 0.25
    done
    if process_is_running "${pid}"; then
      log_line "Force stopping ${label} process group ${pid}"
      kill -9 -- "-${pid}" 2>/dev/null || kill -9 "${pid}" 2>/dev/null || true
    fi
  fi

  [[ -n "${pid_file}" ]] && rm -f "${pid_file}"
}

require_command() {
  local command_name="$1"
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    FAILURE_REASON="Required command '${command_name}' is not installed or not on PATH."
    return 1
  fi
}

describe_port_owner() {
  local port="$1"
  local output

  if ! output="$(lsof -nP -iTCP:"${port}" -sTCP:LISTEN 2>/dev/null)"; then
    return 0
  fi

  printf '%s\n' "${output}" | awk 'NR>1 {printf "%s(pid=%s,user=%s,fd=%s,name=%s)\n", $1, $2, $3, $4, $9}'
}

ensure_port_free() {
  local port="$1"
  local label="$2"
  local owner_lines

  owner_lines="$(describe_port_owner "${port}")"
  if [[ -n "${owner_lines}" ]]; then
    FAILURE_REASON="${label} port ${port} is already occupied before launch: ${owner_lines//$'\n'/; }"
    return 1
  fi
}

extract_port_from_url() {
  local url="$1"
  local scheme host_part

  scheme="${url%%://*}"
  host_part="${url#*://}"
  host_part="${host_part%%/*}"
  host_part="${host_part%%\?*}"
  if [[ "${host_part}" == *:* ]]; then
    printf '%s' "${host_part##*:}"
    return
  fi

  if [[ "${scheme}" == "https" ]]; then
    printf '443'
  else
    printf '80'
  fi
}

is_truthy() {
  local value
  value="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  [[ "${value}" == "1" || "${value}" == "true" || "${value}" == "yes" || "${value}" == "on" ]]
}

base_name_without_pt() {
  local value="$1"
  value="$(basename "${value}")"
  if [[ "${value}" == *.pt ]]; then
    value="${value%.pt}"
  fi
  printf '%s' "${value}"
}

load_backend_env() {
  local env_file line raw_line key value

  env_file="${REPO_ROOT}/services/realtime-api/.env"
  if [[ ! -f "${env_file}" ]]; then
    FAILURE_REASON="Missing ${env_file}. Copy services/realtime-api/.env.example to services/realtime-api/.env before launching."
    return 1
  fi

  while IFS= read -r raw_line || [[ -n "${raw_line}" ]]; do
    line="${raw_line%$'\r'}"
    line="$(trim "${line}")"
    if [[ -z "${line}" || "${line:0:1}" == "#" ]]; then
      continue
    fi
    if [[ "${line}" != *"="* ]]; then
      FAILURE_REASON="Invalid .env entry: '${line}'. Expected KEY=VALUE format."
      return 1
    fi

    key="$(trim "${line%%=*}")"
    value="${line#*=}"
    value="$(trim "${value}")"
    value="$(strip_wrapping_quotes "${value}")"

    if [[ -z "${key}" ]]; then
      FAILURE_REASON="Encountered an empty key while parsing ${env_file}."
      return 1
    fi

    export "${key}=${value}"
  done <"${env_file}"

  APP_ENV="${APP_ENV:-development}"
  LOG_LEVEL="${LOG_LEVEL:-INFO}"
  LLM_PROVIDER="${LLM_PROVIDER:-mock}"
  STT_PROVIDER="${STT_PROVIDER:-mock}"
  TTS_PROVIDER="${TTS_PROVIDER:-mock}"
  LLM_MODEL="${LLM_MODEL:-gemma-4-e4b-it}"
  LMSTUDIO_BASE_URL="${LMSTUDIO_BASE_URL:-http://localhost:1234/v1}"
  STT_MODEL_ROOT="${STT_MODEL_ROOT:-models/whisper}"
  STT_MODEL_SIZE="${STT_MODEL_SIZE:-base.en}"
  STT_LOCAL_FILES_ONLY="${STT_LOCAL_FILES_ONLY:-false}"
  KOKORO_MODEL_ROOT="${KOKORO_MODEL_ROOT:-models/kokoro}"
  KOKORO_VOICE="${KOKORO_VOICE:-af_heart}"
  KOKORO_LOCAL_FILES_ONLY="${KOKORO_LOCAL_FILES_ONLY:-false}"

  LMSTUDIO_MODELS_URL="${LMSTUDIO_BASE_URL%/}/models"
  LMSTUDIO_PORT="$(extract_port_from_url "${LMSTUDIO_BASE_URL}")"
}

assert_file_exists() {
  local path="$1"
  local help_message="$2"
  if [[ ! -f "${path}" ]]; then
    FAILURE_REASON="${help_message} Missing file: ${path}"
    return 1
  fi
}

verify_python_modules() {
  "${REPO_ROOT}/.venv/bin/python" - <<'PY'
import importlib
import sys

modules = [
    "fastapi",
    "uvicorn",
    "openai",
    "whisper",
    "numpy",
    "soundfile",
    "huggingface_hub",
    "kokoro",
]

missing = [name for name in modules if importlib.util.find_spec(name) is None]
if missing:
    sys.stderr.write("missing python modules: " + ", ".join(missing) + "\n")
    sys.exit(1)
PY
}

verify_preflight() {
  require_command "bash"
  require_command "curl"
  require_command "jq"
  require_command "lsof"
  require_command "ss"
  require_command "setsid"
  require_command "npm"
  require_command "espeak-ng"

  assert_file_exists "${REPO_ROOT}/.venv/bin/python" "Python virtual environment is incomplete."
  assert_file_exists "${REPO_ROOT}/.venv/bin/uvicorn" "Python virtual environment is incomplete."
  assert_file_exists "${REPO_ROOT}/package.json" "Project root looks incomplete."
  assert_file_exists "${REPO_ROOT}/apps/web/package.json" "Web workspace is missing."
  assert_file_exists "${REPO_ROOT}/services/realtime-api/pyproject.toml" "Realtime API package is missing."

  ensure_port_free "${API_PORT}" "Backend"
  ensure_port_free "${WEB_PORT}" "Frontend"
}

verify_environment() {
  load_backend_env

  if [[ "${LLM_PROVIDER}" != "lmstudio" ]]; then
    FAILURE_REASON="Strict real mode requires LLM_PROVIDER=lmstudio, but found '${LLM_PROVIDER}'."
    return 1
  fi
  if [[ "${STT_PROVIDER}" != "whisper_rocm" ]]; then
    FAILURE_REASON="Strict real mode requires STT_PROVIDER=whisper_rocm, but found '${STT_PROVIDER}'."
    return 1
  fi
  if [[ "${TTS_PROVIDER}" != "kokoro" ]]; then
    FAILURE_REASON="Strict real mode requires TTS_PROVIDER=kokoro, but found '${TTS_PROVIDER}'."
    return 1
  fi

  verify_python_modules
}

verify_local_model_requirements() {
  local whisper_checkpoint kokoro_root voice_name

  whisper_checkpoint="${REPO_ROOT}/${STT_MODEL_ROOT}/${STT_MODEL_SIZE}.pt"
  if is_truthy "${STT_LOCAL_FILES_ONLY}"; then
    assert_file_exists "${whisper_checkpoint}" "STT_LOCAL_FILES_ONLY=true requires a local Whisper checkpoint."
  fi

  if is_truthy "${KOKORO_LOCAL_FILES_ONLY}"; then
    kokoro_root="${REPO_ROOT}/${KOKORO_MODEL_ROOT}"
    voice_name="$(base_name_without_pt "${KOKORO_VOICE}")"
    assert_file_exists "${kokoro_root}/config.json" "KOKORO_LOCAL_FILES_ONLY=true requires local Kokoro assets."
    assert_file_exists "${kokoro_root}/kokoro-v1_0.pth" "KOKORO_LOCAL_FILES_ONLY=true requires local Kokoro assets."
    assert_file_exists "${kokoro_root}/voices/${voice_name}.pt" "KOKORO_LOCAL_FILES_ONLY=true requires the configured Kokoro voice."
  fi
}

verify_lmstudio() {
  local models_response available_models owner_lines

  if ! models_response="$(curl -fsS --max-time 5 "${LMSTUDIO_MODELS_URL}")"; then
    owner_lines="$(describe_port_owner "${LMSTUDIO_PORT}")"
    if [[ -n "${owner_lines}" ]]; then
      FAILURE_REASON="LM Studio endpoint ${LMSTUDIO_MODELS_URL} did not answer as expected. Port ${LMSTUDIO_PORT} is occupied by: ${owner_lines//$'\n'/; }"
    else
      FAILURE_REASON="LM Studio endpoint ${LMSTUDIO_MODELS_URL} is unreachable. Start LM Studio local server before launching."
    fi
    return 1
  fi

  if ! printf '%s' "${models_response}" | jq -e --arg model "${LLM_MODEL}" 'any(.data[]?; .id == $model)' >/dev/null; then
    available_models="$(printf '%s' "${models_response}" | jq -r '.data[]?.id' | paste -sd ', ' -)"
    FAILURE_REASON="Configured model '${LLM_MODEL}' was not found at ${LMSTUDIO_MODELS_URL}. Available models: ${available_models:-none}."
    return 1
  fi
}

verify_real_dependencies() {
  verify_local_model_requirements
  verify_lmstudio
}

start_backend() {
  setsid bash -lc '
    cd "'"${REPO_ROOT}"'"
    exec "'"${REPO_ROOT}"'"/.venv/bin/uvicorn app.main:app --reload --app-dir services/realtime-api
  ' >>"${BACKEND_LOG}" 2>&1 &
  BACKEND_PID="$!"
  printf '%s\n' "${BACKEND_PID}" >"${BACKEND_PID_FILE}"
  log_line "Started backend process group=${BACKEND_PID}"
}

start_frontend() {
  setsid bash -lc '
    cd "'"${REPO_ROOT}"'"
    exec npm run dev:web
  ' >>"${FRONTEND_LOG}" 2>&1 &
  FRONTEND_PID="$!"
  printf '%s\n' "${FRONTEND_PID}" >"${FRONTEND_PID_FILE}"
  log_line "Started frontend process group=${FRONTEND_PID}"
}

wait_for_url() {
  local url="$1"
  local label="$2"
  local timeout_seconds="$3"
  local related_pid="${4:-}"
  local deadline

  deadline=$((SECONDS + timeout_seconds))
  while (( SECONDS < deadline )); do
    if curl -fsS --max-time 2 "${url}" >/dev/null 2>&1; then
      log_line "${label} is reachable at ${url}"
      return 0
    fi

    if [[ -n "${related_pid}" ]] && ! process_is_running "${related_pid}"; then
      FAILURE_REASON="${label} process ${related_pid} exited before ${url} became reachable. Check ${label} logs in ${RUNTIME_DIR}."
      return 1
    fi

    sleep 1
  done

  FAILURE_REASON="${label} did not become reachable at ${url} within ${timeout_seconds}s."
  return 1
}

http_status_text() {
  local url="$1"
  if curl -fsS --max-time 2 "${url}" >/dev/null 2>&1; then
    printf 'OK'
  else
    printf 'DOWN'
  fi
}

backend_health_text() {
  local response
  if response="$(curl -fsS --max-time 2 "${BACKEND_HEALTH_URL}" 2>/dev/null)"; then
    printf '%s' "${response}" | jq -r '.status // "unknown"' 2>/dev/null || printf 'unknown'
  else
    printf 'down'
  fi
}

lmstudio_model_status_text() {
  local response
  if response="$(curl -fsS --max-time 2 "${LMSTUDIO_MODELS_URL}" 2>/dev/null)"; then
    if printf '%s' "${response}" | jq -e --arg model "${LLM_MODEL}" 'any(.data[]?; .id == $model)' >/dev/null 2>&1; then
      printf 'OK'
    else
      printf 'MODEL_MISSING'
    fi
  else
    printf 'DOWN'
  fi
}

status_for_pid() {
  local pid="$1"
  if process_is_running "${pid}"; then
    printf 'alive (pid %s)' "${pid}"
  else
    printf 'dead'
  fi
}

print_section_header() {
  printf '\n%s\n' "$1"
  printf '%s\n' "$(printf '%.0s-' $(seq 1 ${#1}))"
}

print_kv() {
  printf '%-28s %s\n' "$1" "$2"
}

render_log_tail() {
  local title="$1"
  local file_path="$2"

  print_section_header "${title}"
  if [[ -s "${file_path}" ]]; then
    tail -n 8 "${file_path}"
  else
    printf '(no log output yet)\n'
  fi
}

render_dashboard() {
  local overall_state="RUNNING"
  local backend_proc_status frontend_proc_status backend_health metrics_status web_status lmstudio_status

  backend_proc_status="$(status_for_pid "${BACKEND_PID}")"
  frontend_proc_status="$(status_for_pid "${FRONTEND_PID}")"
  backend_health="$(backend_health_text)"
  metrics_status="$(http_status_text "${BACKEND_METRICS_URL}")"
  web_status="$(http_status_text "${WEB_URL}")"
  lmstudio_status="$(lmstudio_model_status_text)"

  if [[ "${backend_proc_status}" == dead* || "${frontend_proc_status}" == dead* ]]; then
    overall_state="FAILED"
  elif [[ "${backend_health}" != "ok" || "${metrics_status}" != "OK" || "${web_status}" != "OK" || "${lmstudio_status}" != "OK" ]]; then
    overall_state="DEGRADED"
  fi

  if [[ -t 1 && -n "${TERM:-}" ]]; then
    if [[ "${NO_CLEAR}" != "1" ]]; then
      clear
    fi
  else
    printf '\n==== talkToLLM launcher dashboard ====\n'
  fi

  printf 'talkToLLM Desktop Launcher\n'
  printf 'Generated at: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')"
  printf 'Current stage: %s\n' "${CURRENT_STAGE}"
  printf 'Overall state: %s\n' "${overall_state}"
  printf 'Repo root: %s\n' "${REPO_ROOT}"
  printf 'Runtime dir: %s\n' "${RUNTIME_DIR}"

  print_section_header "Managed processes"
  print_kv "Backend process" "${backend_proc_status}"
  print_kv "Frontend process" "${frontend_proc_status}"

  print_section_header "Live health"
  print_kv "Backend /healthz" "${backend_health}"
  print_kv "Backend /metrics" "${metrics_status}"
  print_kv "Frontend ${WEB_URL}" "${web_status}"
  print_kv "LM Studio ${LMSTUDIO_MODELS_URL}" "${lmstudio_status}"

  print_section_header "Configured providers"
  print_kv "LLM_PROVIDER" "${LLM_PROVIDER}"
  print_kv "STT_PROVIDER" "${STT_PROVIDER}"
  print_kv "TTS_PROVIDER" "${TTS_PROVIDER}"
  print_kv "LLM_MODEL" "${LLM_MODEL}"
  print_kv "LMSTUDIO_BASE_URL" "${LMSTUDIO_BASE_URL}"
  print_kv "STT_MODEL_ROOT" "${STT_MODEL_ROOT}"
  print_kv "KOKORO_MODEL_ROOT" "${KOKORO_MODEL_ROOT}"

  print_section_header "Useful URLs"
  print_kv "Web UI" "${WEB_URL}"
  print_kv "Backend health" "${BACKEND_HEALTH_URL}"
  print_kv "Backend metrics" "${BACKEND_METRICS_URL}"
  print_kv "LM Studio models" "${LMSTUDIO_MODELS_URL}"

  render_log_tail "Backend log tail" "${BACKEND_LOG}"
  render_log_tail "Frontend log tail" "${FRONTEND_LOG}"

  printf '\nPress Ctrl+C to stop the launcher and managed services.\n'
}

monitor_services() {
  local tick_count=0

  while true; do
    if [[ "${DASHBOARD_ENABLED}" == "1" ]]; then
      render_dashboard
    fi

    if ! process_is_running "${BACKEND_PID}"; then
      FAILURE_REASON="Backend process ${BACKEND_PID} exited unexpectedly. Inspect ${BACKEND_LOG}."
      return 1
    fi

    if ! process_is_running "${FRONTEND_PID}"; then
      FAILURE_REASON="Frontend process ${FRONTEND_PID} exited unexpectedly. Inspect ${FRONTEND_LOG}."
      return 1
    fi

    tick_count=$((tick_count + 1))
    if [[ "${MAX_MONITOR_TICKS}" =~ ^[0-9]+$ ]] && (( MAX_MONITOR_TICKS > 0 )) && (( tick_count >= MAX_MONITOR_TICKS )); then
      SHUTDOWN_REASON="Reached TALKTOLLM_MAX_MONITOR_TICKS=${MAX_MONITOR_TICKS}; stopping managed services."
      log_line "${SHUTDOWN_REASON}"
      SHUTDOWN_REASON_LOGGED=1
      return 0
    fi

    sleep "${MONITOR_INTERVAL}"
  done
}

main() {
  resolve_repo_root
  initialize_runtime_paths
  log_line "Launcher starting from ${REPO_ROOT}"

  set_stage "1. Preflight checks"
  verify_preflight

  set_stage "2. Environment/bootstrap checks"
  verify_environment

  set_stage "3. Strict real-provider dependency checks"
  verify_real_dependencies

  set_stage "4. Backend start"
  start_backend

  set_stage "5. Backend health wait"
  wait_for_url "${BACKEND_HEALTH_URL}" "Backend health endpoint" 30 "${BACKEND_PID}"
  wait_for_url "${BACKEND_METRICS_URL}" "Backend metrics endpoint" 30 "${BACKEND_PID}"

  set_stage "6. Frontend start"
  start_frontend

  set_stage "7. Frontend reachability wait"
  wait_for_url "${WEB_URL}" "Frontend dev server" 45 "${FRONTEND_PID}"

  set_stage "8. Continuous live monitoring"
  notify_user "talkToLLM is running with live health monitoring."
  monitor_services
}

main "$@"

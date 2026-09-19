#!/usr/bin/env bash
# Keep AutoRecon gateway (19001) running. One instance via flock.
# Stop: SIGTERM this process (see .runtime/gateway/supervisor.pid). Do not only kill python.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="/opt/miniconda3/bin:/home/huangwei/.local/bin:/usr/bin:/bin:${PATH:-}"
export PYTHONUNBUFFERED=1
# Health checks must hit the local server, not an HTTP proxy.
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY ftp_proxy FTP_PROXY no_proxy NO_PROXY

CONFIG_FILE="${AUTORECON_GATEWAY_CONFIG:-${PROJECT_ROOT}/config/service.env}"
if [[ -f "${CONFIG_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${CONFIG_FILE}"
  set +a
  export AUTORECON_GATEWAY_CONFIG="${CONFIG_FILE}"
fi

PORT="${AUTORECON_GATEWAY_PORT:-19001}"
DATA_ROOT="${AUTORECON_GATEWAY_DATA:-${PROJECT_ROOT}/.runtime/gateway}"
if [[ "${DATA_ROOT}" != /* ]]; then
  DATA_ROOT="${PROJECT_ROOT}/${DATA_ROOT}"
fi
mkdir -p "${DATA_ROOT}/alerts"

LOCK="${DATA_ROOT}/supervisor.lock"
SUP_PIDFILE="${DATA_ROOT}/supervisor.pid"
GW_PIDFILE="${DATA_ROOT}/gateway.pid"
GW_LOG="${DATA_ROOT}/gateway.log"
SUP_LOG="${DATA_ROOT}/supervisor.log"
COOLDOWN_FILE="${DATA_ROOT}/last_alert_ts"
ALERTS_DIR="${DATA_ROOT}/alerts"
SEND_EMAIL="${HOME}/.cursor/skills/send-qq-email/scripts/send_email.py"
HEALTH_URL="http://127.0.0.1:${PORT}/"
COOLDOWN_SECONDS=900
HEALTH_INTERVAL=30
HEALTH_FAILS_NEEDED=3
MAX_BACKOFF=60

exec 9>"${LOCK}"
if ! flock -n 9; then
  echo "$(date -Iseconds) supervisor already running" >&2
  exit 0
fi

echo "$$" > "${SUP_PIDFILE}"
CHILD=""
STOPPING=0
SKIP_CRASH_ALERT=0
BACKOFF=2

log() {
  printf '%s %s\n' "$(date -Iseconds)" "$*" | tee -a "${SUP_LOG}" >&2
}

health_ok() {
  curl --noproxy '*' -fsS -m 5 -o /dev/null "${HEALTH_URL}" 2>/dev/null
}

kill_child() {
  local pid="${1:-}"
  [[ -n "${pid}" ]] || return 0
  if kill -0 "${pid}" 2>/dev/null; then
    kill -TERM "${pid}" 2>/dev/null || true
    local i
    for i in 1 2 3 4 5 6 7 8 9 10; do
      if ! kill -0 "${pid}" 2>/dev/null; then
        break
      fi
      sleep 1
    done
    if kill -0 "${pid}" 2>/dev/null; then
      kill -KILL "${pid}" 2>/dev/null || true
    fi
  fi
  wait "${pid}" 2>/dev/null || true
  CHILD=""
  rm -f "${GW_PIDFILE}"
}

on_stop() {
  STOPPING=1
  log "supervisor stopping (signal)"
  if [[ -n "${CHILD}" ]]; then
    kill_child "${CHILD}"
  fi
  rm -f "${SUP_PIDFILE}"
  exit 0
}

trap on_stop SIGTERM SIGINT SIGHUP

notify() {
  local reason="$1"
  local extra="${2:-}"
  local now last body dest
  now="$(date +%s)"
  if [[ -f "${COOLDOWN_FILE}" ]]; then
    last="$(tr -dc '0-9' < "${COOLDOWN_FILE}" || true)"
    last="${last:-0}"
    if (( now - last < COOLDOWN_SECONDS )); then
      log "alert suppressed (${reason}), cooldown ${COOLDOWN_SECONDS}s"
      return 0
    fi
  fi

  body="$(mktemp "${ALERTS_DIR}/body.XXXXXX")"
  {
    echo "host: $(hostname -f 2>/dev/null || hostname)"
    echo "time: $(date -Iseconds)"
    echo "reason: ${reason}"
    echo "health_url: ${HEALTH_URL}"
    echo "supervisor_pid: $$"
    echo "gateway_pid: ${CHILD:-none}"
    echo "${extra}"
    echo
    echo "---- gateway.log (tail) ----"
    if [[ -f "${GW_LOG}" ]]; then
      tail -n 80 "${GW_LOG}" || true
    else
      echo "(missing ${GW_LOG})"
    fi
  } > "${body}"

  dest="${ALERTS_DIR}/alert-$(date +%Y%m%dT%H%M%S)-${reason}.txt"
  cp "${body}" "${dest}"
  chmod 600 "${body}" "${dest}" 2>/dev/null || true

  if [[ ! -f "${SEND_EMAIL}" ]]; then
    log "alert mail skipped (${reason}): missing ${SEND_EMAIL}; kept ${dest}"
    rm -f "${body}"
    return 0
  fi
  if python "${SEND_EMAIL}" --subject "[AutoRecon] gateway ${PORT} 重启: ${reason}" --body-file "${body}"; then
    echo "${now}" > "${COOLDOWN_FILE}"
    log "alert mailed (${reason})"
  else
    log "alert mail failed (${reason}), kept ${dest}"
  fi
  rm -f "${body}"
}

start_child() {
  log "starting gateway bind ${AUTORECON_GATEWAY_HOST:-0.0.0.0}:${PORT}"
  # stdout/stderr append to gateway.log; python is exec'd by run_gateway.sh
  bash "${PROJECT_ROOT}/scripts/run_gateway.sh" >> "${GW_LOG}" 2>&1 &
  CHILD=$!
  echo "${CHILD}" > "${GW_PIDFILE}"
  log "gateway pid ${CHILD}"
}

wait_child_or_hung() {
  local fails=0
  local ticks=0
  SKIP_CRASH_ALERT=0
  while kill -0 "${CHILD}" 2>/dev/null; do
    sleep 1
    ticks=$((ticks + 1))
    if (( ticks % HEALTH_INTERVAL != 0 )); then
      continue
    fi
    if health_ok; then
      if (( fails > 0 )); then
        log "health recovered after ${fails} failure(s)"
      fi
      fails=0
      BACKOFF=2
    else
      fails=$((fails + 1))
      log "health check failed (${fails}/${HEALTH_FAILS_NEEDED}) pid=${CHILD}"
      if (( fails >= HEALTH_FAILS_NEEDED )); then
        log "gateway hung, killing pid ${CHILD}"
        SKIP_CRASH_ALERT=1
        notify "hung" "consecutive_health_failures: ${fails}"
        kill_child "${CHILD}"
        return 0
      fi
    fi
  done
  if [[ -z "${CHILD}" ]] || (( STOPPING == 1 )); then
    return 0
  fi
  local code=0
  wait "${CHILD}" || code=$?
  CHILD=""
  rm -f "${GW_PIDFILE}"
  if (( SKIP_CRASH_ALERT == 1 )); then
    return 0
  fi
  log "gateway exited code=${code}"
  if (( code == 143 || code == 130 )); then
    log "planned stop (SIGTERM/SIGINT), skip mail"
    return 0
  fi
  notify "crash" "exit_code: ${code}"
}

log "supervisor start pid=$$ data=${DATA_ROOT}"
while (( STOPPING == 0 )); do
  start_child
  wait_child_or_hung
  if (( STOPPING == 1 )); then
    break
  fi
  log "restart in ${BACKOFF}s"
  sleep "${BACKOFF}"
  BACKOFF=$((BACKOFF * 2))
  if (( BACKOFF > MAX_BACKOFF )); then
    BACKOFF=${MAX_BACKOFF}
  fi
done

rm -f "${SUP_PIDFILE}"
log "supervisor exit"

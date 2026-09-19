#!/usr/bin/env bash
# Idempotent entry for cron: start supervise_gateway.sh if it is not holding the lock.
#   scripts/ensure_gateway.sh              # start if needed
#   scripts/ensure_gateway.sh --install-cron
#   scripts/ensure_gateway.sh --stop       # SIGTERM supervisor (cron will revive within 5 min)
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="/opt/miniconda3/bin:/home/huangwei/.local/bin:/usr/bin:/bin:${PATH:-}"

CONFIG_FILE="${AUTORECON_GATEWAY_CONFIG:-${PROJECT_ROOT}/config/service.env}"
if [[ -f "${CONFIG_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${CONFIG_FILE}"
  set +a
fi

DATA_ROOT="${AUTORECON_GATEWAY_DATA:-${PROJECT_ROOT}/.runtime/gateway}"
if [[ "${DATA_ROOT}" != /* ]]; then
  DATA_ROOT="${PROJECT_ROOT}/${DATA_ROOT}"
fi
mkdir -p "${DATA_ROOT}"

LOCK="${DATA_ROOT}/supervisor.lock"
SUP_PIDFILE="${DATA_ROOT}/supervisor.pid"
SUP_LOG="${DATA_ROOT}/supervisor.log"
SUPERVISE="${PROJECT_ROOT}/scripts/supervise_gateway.sh"
ENSURE="${PROJECT_ROOT}/scripts/ensure_gateway.sh"

supervisor_alive() {
  if [[ -f "${SUP_PIDFILE}" ]]; then
    local pid
    pid="$(tr -dc '0-9' < "${SUP_PIDFILE}" || true)"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      return 0
    fi
  fi
  if ! flock -n "${LOCK}" true; then
    return 0
  fi
  return 1
}

install_cron() {
  local existing tmp
  existing="$(crontab -l 2>/dev/null || true)"
  if printf '%s\n' "${existing}" | grep -F "${ENSURE}" >/dev/null 2>&1; then
    echo "cron already contains ${ENSURE}"
    return 0
  fi
  tmp="$(mktemp)"
  {
    if [[ -n "${existing}" ]]; then
      printf '%s\n' "${existing}"
    fi
    echo "PATH=/opt/miniconda3/bin:/usr/bin:/bin"
    echo "SHELL=/bin/bash"
    echo "@reboot ${ENSURE}"
    echo "*/5 * * * * ${ENSURE}"
  } > "${tmp}"
  crontab "${tmp}"
  rm -f "${tmp}"
  echo "installed user crontab:"
  crontab -l
}

stop_supervisor() {
  if [[ -f "${SUP_PIDFILE}" ]]; then
    local pid
    pid="$(tr -dc '0-9' < "${SUP_PIDFILE}" || true)"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      kill -TERM "${pid}"
      echo "sent SIGTERM to supervisor ${pid}"
      return 0
    fi
  fi
  echo "supervisor not running"
  return 0
}

start_supervisor() {
  if supervisor_alive; then
    echo "supervisor already running"
    return 0
  fi
  chmod +x "${SUPERVISE}" "${ENSURE}" 2>/dev/null || true
  setsid --fork -- "${SUPERVISE}" </dev/null >/dev/null 2>&1
  sleep 0.2
  if [[ -f "${SUP_PIDFILE}" ]]; then
    echo "started supervisor pid $(tr -dc '0-9' < "${SUP_PIDFILE}")"
  else
    echo "started supervisor"
  fi
}

case "${1:-}" in
  --install-cron)
    install_cron
    ;;
  --stop)
    stop_supervisor
    ;;
  ""|--start)
    start_supervisor
    ;;
  *)
    echo "usage: $0 [--start|--stop|--install-cron]" >&2
    exit 2
    ;;
esac

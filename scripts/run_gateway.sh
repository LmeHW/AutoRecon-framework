#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="${AUTORECON_GATEWAY_CONFIG:-${PROJECT_ROOT}/config/service.env}"

if [[ -f "${CONFIG_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${CONFIG_FILE}"
  set +a
  export AUTORECON_GATEWAY_CONFIG="${CONFIG_FILE}"
fi

cd "${PROJECT_ROOT}"
export PYTHONUNBUFFERED=1
exec python -m service serve "$@"

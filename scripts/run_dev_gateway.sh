#!/usr/bin/env bash
# Local development gateway: port 19002, data .runtime/gateway-dev.
# Does not touch the production supervisor on 19001.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="${AUTORECON_GATEWAY_CONFIG:-${PROJECT_ROOT}/config/service.dev.env}"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Create ${CONFIG_FILE} from config/service.dev.env.example first." >&2
  exit 2
fi

export AUTORECON_GATEWAY_CONFIG="${CONFIG_FILE}"
exec bash "${PROJECT_ROOT}/scripts/run_gateway.sh" "$@"

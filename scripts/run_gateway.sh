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
# Clinic LLM calls must reach the provider directly. A leftover `proxy=` from the
# login environment can send BigModel/OpenAI traffic into a local Clash port.
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY ftp_proxy FTP_PROXY no_proxy NO_PROXY proxy PROXY
exec python -m service serve "$@"

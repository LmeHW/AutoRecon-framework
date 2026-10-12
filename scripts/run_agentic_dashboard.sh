#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRET_FILE="${AUTORECON_SECRET_FILE:-${PROJECT_ROOT}/.secrets/glm.env}"
CONFIG_FILE="${AUTORECON_CONFIG_FILE:-${PROJECT_ROOT}/.env}"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Config file not found: ${CONFIG_FILE}" >&2
  exit 2
fi

if [[ ! -f "${SECRET_FILE}" ]]; then
  echo "Secret file not found: ${SECRET_FILE}" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "${SECRET_FILE}"
set +a

export AUTORECON_CONFIG_FILE="${CONFIG_FILE}"

if [[ -z "${AUTORECON_LLM_API_KEY:-}" ]]; then
  echo "AUTORECON_LLM_API_KEY is not exported by ${SECRET_FILE}" >&2
  exit 2
fi

cd "${PROJECT_ROOT}"
exec python -m agentic.dashboard_cn "$@"

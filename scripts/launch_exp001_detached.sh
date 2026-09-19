#!/usr/bin/env bash
# Detach an EXP-001 development/pilot run so it survives the chat session.
# Plan-only. No GPU. Not the locked FlowBench test.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-/opt/miniconda3/bin/python3}"
STAMP="${EXP001_STAMP:-$(date -u +%Y%m%dT%H%MZ)}"
RUN_DIR="${EXP001_OUTPUT:-${ROOT}/validation_runs/exp001_${STAMP}}"
mkdir -p "${RUN_DIR}"

export AUTORECON_CONFIG_FILE="${AUTORECON_CONFIG_FILE:-${ROOT}/config/glm.env}"
export AUTORECON_SECRET_FILE="${AUTORECON_SECRET_FILE:-${ROOT}/.secrets/glm.env}"
export PYTHONUNBUFFERED=1
export CUDA_VISIBLE_DEVICES=""
cd "${ROOT}"

CURRENT="${ROOT}/validation_runs/exp001_current"
ln -sfn "$(basename "${RUN_DIR}")" "${CURRENT}"

if [[ -f "${RUN_DIR}/runner.pid" ]]; then
  old_pid="$(tr -d '[:space:]' < "${RUN_DIR}/runner.pid" || true)"
  if [[ -n "${old_pid}" ]] && kill -0 "${old_pid}" 2>/dev/null; then
    echo "already running pid=${old_pid} dir=${RUN_DIR}"
    exit 0
  fi
fi

WRAP="${RUN_DIR}/wrap.sh"
cat > "${WRAP}" <<EOF
#!/usr/bin/env bash
set -uo pipefail
trap '' HUP
echo \$\$ > "${RUN_DIR}/runner.pid"
cd "${ROOT}"
export AUTORECON_CONFIG_FILE="${AUTORECON_CONFIG_FILE}"
export AUTORECON_SECRET_FILE="${AUTORECON_SECRET_FILE}"
export PYTHONUNBUFFERED=1
export CUDA_VISIBLE_DEVICES=""
"${PYTHON}" "${ROOT}/scripts/run_exp001_flowbench.py" \\
  --output "${RUN_DIR}" \\
  --config "${AUTORECON_CONFIG_FILE}" \\
  --repeats 3 \\
  --workers 2 \\
  --skip-qwen \\
  --notify
code=\$?
echo "\${code}" > "${RUN_DIR}/exit_code"
if [[ ! -f "${RUN_DIR}/EMAIL_SENT" ]]; then
  body="${RUN_DIR}/email_body.txt"
  {
    echo "EXP-001 wrapper exit=\${code}"
    echo "dir=${RUN_DIR}"
    echo "log=${RUN_DIR}/runner.log"
    echo "这不是 locked test，数字不得写入 CLAIM/RES。"
    echo
    tail -n 80 "${RUN_DIR}/runner.log" 2>/dev/null || true
  } > "\${body}"
  "${PYTHON}" "${HOME}/.cursor/skills/send-qq-email/scripts/send_email.py" \\
    --subject "[AutoRecon] EXP-001 wrapper exit=\${code}" \\
    --body-file "\${body}" && date -u +"sent %Y-%m-%dT%H:%MZ" > "${RUN_DIR}/EMAIL_SENT" || true
fi
exit "\${code}"
EOF
chmod +x "${WRAP}"

# New session so a later SIGHUP on the chat process group cannot stop the run.
setsid -f bash "${WRAP}" </dev/null >>"${RUN_DIR}/runner.log" 2>&1
sleep 0.8
pid="$(tr -d '[:space:]' < "${RUN_DIR}/runner.pid" 2>/dev/null || true)"
if [[ -z "${pid}" ]]; then
  pid="$(pgrep -f "run_exp001_flowbench.py --output ${RUN_DIR}" | head -n 1 || true)"
  printf '%s\n' "${pid}" > "${RUN_DIR}/runner.pid"
fi
{
  echo "started_at=$(date -u +%Y-%m-%dT%H:%MZ)"
  echo "run_dir=${RUN_DIR}"
  echo "current=${CURRENT}"
  echo "pid=${pid}"
  echo "log=${RUN_DIR}/runner.log"
} | tee "${RUN_DIR}/LAUNCH.txt"
echo "${RUN_DIR}"

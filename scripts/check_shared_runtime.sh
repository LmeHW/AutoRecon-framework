#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="${AUTORECON_RUNTIME_ROOT:-${PROJECT_ROOT}/.runtime}"
APPTAINER_DEFAULT="/mnt/sda/huangwei/conda_envs/apptainer/bin/apptainer"

find_apptainer() {
  if [[ -n "${APPTAINER_BIN:-}" && -x "${APPTAINER_BIN}" ]]; then
    printf '%s\n' "${APPTAINER_BIN}"
  elif command -v apptainer >/dev/null 2>&1; then
    command -v apptainer
  elif [[ -x "${APPTAINER_DEFAULT}" ]]; then
    printf '%s\n' "${APPTAINER_DEFAULT}"
  else
    return 1
  fi
}

required_dirs=(containers model_cache weights atlas manifests tmp)
for name in "${required_dirs[@]}"; do
  path="${RUNTIME_ROOT}/${name}"
  if [[ ! -d "${path}" ]]; then
    echo "MISSING runtime directory: ${path}" >&2
    exit 1
  fi
  if [[ ! -r "${path}" || ! -x "${path}" ]]; then
    echo "Runtime directory is not readable/traversable: ${path}" >&2
    exit 1
  fi
done

apptainer_bin="$(find_apptainer)" || {
  echo "Apptainer is unavailable. Set APPTAINER_BIN or install it on PATH." >&2
  exit 1
}

mkdir -p "${RUNTIME_ROOT}/model_cache/apptainer" "${RUNTIME_ROOT}/tmp/apptainer"
export APPTAINER_CACHEDIR="${APPTAINER_CACHEDIR:-${RUNTIME_ROOT}/model_cache/apptainer}"
export APPTAINER_TMPDIR="${APPTAINER_TMPDIR:-${RUNTIME_ROOT}/tmp/apptainer}"

echo "Runtime root: ${RUNTIME_ROOT}"
echo "Runtime permissions: $(stat -c '%A %a %U:%G' "${RUNTIME_ROOT}")"
echo "Apptainer: ${apptainer_bin}"
"${apptainer_bin}" version

manifest="${RUNTIME_ROOT}/manifests/containers.json"
if [[ -f "${manifest}" ]]; then
  python -m json.tool "${manifest}" >/dev/null
  echo "Container manifest: valid"
else
  echo "Container manifest: missing" >&2
  exit 1
fi

RUNTIME_ROOT="${RUNTIME_ROOT}" python - <<'PY'
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ["RUNTIME_ROOT"])
manifest = json.loads((root / "manifests/containers.json").read_text())
errors = []
for name, record in manifest.get("containers", {}).items():
    if record.get("status") != "installed":
        continue
    path = root / record["file"]
    if not path.is_file():
        errors.append(f"{name}: missing {path}")
        continue
    actual_size = path.stat().st_size
    if actual_size != record.get("size_bytes"):
        errors.append(f"{name}: size {actual_size} != manifest {record.get('size_bytes')}")
        continue
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    actual_hash = digest.hexdigest()
    if actual_hash != record.get("sha256"):
        errors.append(f"{name}: sha256 {actual_hash} != manifest {record.get('sha256')}")
    else:
        print(f"Manifest artifact verified: {name} ({actual_size} bytes, sha256={actual_hash})")
if errors:
    raise SystemExit("\n".join(errors))
PY

shopt -s nullglob
sifs=("${RUNTIME_ROOT}/containers/"*.sif)
if [[ "${#sifs[@]}" -eq 0 ]]; then
  echo "Containers: none installed yet"
else
  for sif in "${sifs[@]}"; do
    if [[ ! -r "${sif}" ]]; then
      echo "Container is not readable: ${sif}" >&2
      exit 1
    fi
    echo "Container: $(basename "${sif}") ($(stat -c '%s bytes, %A' "${sif}"))"
  done
fi

echo "Shared runtime check passed."

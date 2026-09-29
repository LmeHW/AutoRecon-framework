#!/usr/bin/env bash
set -euo pipefail

# Unified single-case pipeline:
#   extraction -> reconstruction -> registration -> tissue -> ROI -> surface
# Run `bash run_single_case_pipeline.sh --help` for the full argument list and examples.

usage() {
  cat <<'EOF'
Usage:
  bash run_single_case_pipeline.sh \
    --subject-dir /path/to/subject_dir \
    --work-root /path/to/work_root \
    [--atlas /path/to/atlas.nii.gz] \
    [--ants-dir /path/to/ants/bin] \
    [--registration-preset full|fast] \
    [--orientation-jobs 48] \
    [--itk-threads 4] \
    [--roi-warp-env /path/to/conda/env] \
    [--reconstruction-tool frost|nesvor|autosvrtk|niftymic] \
    [--compare-reconstruction-tools all|frost,nesvor,autosvrtk,niftymic] \
    [--roi-mode segresnet|warp|skip] \
    [--surface auto|on|off] \
    [--surface-subjects-dir /path/to/surface_subjects] \
    [--surface-python /path/to/python] \
    [--freesurfer-home /path/to/freesurfer] \
    [--ga 28.4] \
    [--dashboard auto|on|off] \
    [--dashboard-host 127.0.0.1] \
    [--dashboard-port 8765] \
    [--dashboard-python /path/to/python]
    [--steps extraction,reconstruction,registration,tissue,roi,surface] \
    [--resume]

What this does:
  1. Creates a staging copy of one subject under work_root/staging
  2. Runs 2D extraction into staging/subject/seg
  3. Runs 3D reconstruction into work_root/outputs/recon
  4. Optionally runs rigid atlas registration into work_root/outputs/registration
  5. Runs tissue segmentation into work_root/outputs/Tissue
  6. Optionally runs ROI segmentation or atlas ROI warp into work_root/outputs/ROI
  7. Optionally runs surface reconstruction into work_root/outputs/surface_subjects
  8. Writes a lightweight dashboard under work_root/dashboard for remote visualization

Notes:
  - Source files are not modified.
  - The subject directory must contain top-level *.nii.gz stacks for extraction/reconstruction.
  - reconstruction-tool defaults to frost. External backends use SIF images under AUTORECON_RUNTIME_ROOT.
  - NeSVoR and NiftyMIC reuse the extraction masks. AutoSVRTK applies a 10 mm dilation to those masks, then zeros tissue outside the dilated region before the official script.
  - roi-mode=segresnet requires the external ROI model dependencies referenced by 02_seg_roi_patch.sh.
  - roi-mode=warp requires both --atlas and --ga if you use registration output; if --atlas is omitted, roi_warp.py uses its internal atlas root.
  - surface=auto runs only when recon+tissue+ROI outputs are available; surface=on makes missing prerequisites a hard error.
  - FreeSurfer is required only when the surface step actually runs.
  - For VSCode SSH, forward the dashboard port to your local machine and open the printed URL.

Examples:
  1. Full pipeline with atlas ROI warp and surface reconstruction:
     bash run_single_case_pipeline.sh \
       --subject-dir /path/to/subject \
       --work-root /path/to/run01 \
       --atlas /path/to/31w.nii.gz \
       --ants-dir /path/to/ants/bin \
       --roi-warp-env /path/to/ants_env \
       --roi-mode warp \
       --ga 31 \
       --surface auto

  2. Unknown GA, use SegResNet ROI and still build surfaces:
     bash run_single_case_pipeline.sh \
       --subject-dir /path/to/subject \
       --work-root /path/to/run01 \
       --roi-mode segresnet \
       --surface auto
EOF
}

SUBJECT_DIR=""
WORK_ROOT=""
ATLAS_PATH=""
ANTS_DIR=""
REGISTRATION_PRESET="full"
REGISTRATION_ORIENTATION_JOBS="${AUTORECON_ORIENTATION_JOBS:-48}"
REGISTRATION_ITK_THREADS="${AUTORECON_ITK_THREADS:-4}"
REGISTRATION_CASE_JOBS="${AUTORECON_REG_CASE_JOBS:-1}"
ROI_WARP_ENV="${ROI_WARP_ENV:-}"
RECONSTRUCTION_TOOL="frost"
COMPARE_RECONSTRUCTION_TOOLS=""
RECON_RUNNER_PYTHON="${RECON_RUNNER_PYTHON:-python}"
TISSUE_WARP_FALLBACK_ENV="${TISSUE_NUNET_ENV:-}"
ROI_SEG_WARP_FALLBACK_ENV="${ROI_SEG_ENV:-}"
ROI_MODE="skip"
SURFACE_MODE="auto"
GA_VALUE=""
SURFACE_SUBJECTS_DIR=""
SURFACE_PYTHON="${SURFACE_PYTHON:-/home/zhaojunyang/.conda/envs/zjy/bin/python}"
FREESURFER_HOME="${FREESURFER_HOME:-/mnt/sda/lx/00_Software/freesurfer}"
DASHBOARD_MODE="auto"
DASHBOARD_HOST="127.0.0.1"
DASHBOARD_PORT="8765"
DASHBOARD_PYTHON_OVERRIDE="${PIPELINE_DASHBOARD_PYTHON:-}"
REQUESTED_STEPS="extraction,reconstruction,registration,tissue,roi,surface"
RESUME_MODE="0"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${REPO_ROOT}")"
PIPELINE_ARGV=("$@")
CURRENT_STEP_ID=""
PIPELINE_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RUNTIME_ROOT="${AUTORECON_RUNTIME_ROOT:-${PROJECT_ROOT}/.runtime}"
PIPELINE_USE_CONTAINERS="${PIPELINE_USE_CONTAINERS:-1}"
APPTAINER_BIN="${APPTAINER_BIN:-}"
CONTAINER_EXTRA_BINDS=()
TISSUE_NNUNET_CODE="${TISSUE_NNUNET_CODE:-$(dirname "${PROJECT_ROOT}")/nnUNet}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --subject-dir)
      SUBJECT_DIR="${2:-}"
      shift 2
      ;;
    --work-root)
      WORK_ROOT="${2:-}"
      shift 2
      ;;
    --atlas)
      ATLAS_PATH="${2:-}"
      shift 2
      ;;
    --ants-dir)
      ANTS_DIR="${2:-}"
      shift 2
      ;;
    --registration-preset)
      REGISTRATION_PRESET="${2:-}"
      shift 2
      ;;
    --orientation-jobs)
      REGISTRATION_ORIENTATION_JOBS="${2:-}"
      shift 2
      ;;
    --itk-threads)
      REGISTRATION_ITK_THREADS="${2:-}"
      shift 2
      ;;
    --registration-case-jobs)
      REGISTRATION_CASE_JOBS="${2:-}"
      shift 2
      ;;
    --roi-warp-env)
      ROI_WARP_ENV="${2:-}"
      shift 2
      ;;
    --reconstruction-tool)
      RECONSTRUCTION_TOOL="${2:-}"
      shift 2
      ;;
    --compare-reconstruction-tools)
      COMPARE_RECONSTRUCTION_TOOLS="${2:-}"
      shift 2
      ;;
    --roi-mode)
      ROI_MODE="${2:-}"
      shift 2
      ;;
    --surface)
      SURFACE_MODE="${2:-}"
      shift 2
      ;;
    --surface-subjects-dir)
      SURFACE_SUBJECTS_DIR="${2:-}"
      shift 2
      ;;
    --surface-python)
      SURFACE_PYTHON="${2:-}"
      shift 2
      ;;
    --freesurfer-home)
      FREESURFER_HOME="${2:-}"
      shift 2
      ;;
    --ga)
      GA_VALUE="${2:-}"
      shift 2
      ;;
    --dashboard)
      DASHBOARD_MODE="${2:-}"
      shift 2
      ;;
    --dashboard-host)
      DASHBOARD_HOST="${2:-}"
      shift 2
      ;;
    --dashboard-port)
      DASHBOARD_PORT="${2:-}"
      shift 2
      ;;
    --dashboard-python)
      DASHBOARD_PYTHON_OVERRIDE="${2:-}"
      shift 2
      ;;
    --steps)
      REQUESTED_STEPS="${2:-}"
      shift 2
      ;;
    --resume)
      RESUME_MODE="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "${SUBJECT_DIR}" || -z "${WORK_ROOT}" ]]; then
  usage >&2
  exit 1
fi

if [[ "${ROI_MODE}" != "skip" && "${ROI_MODE}" != "segresnet" && "${ROI_MODE}" != "warp" ]]; then
  echo "Invalid --roi-mode: ${ROI_MODE}" >&2
  exit 1
fi

case "${RECONSTRUCTION_TOOL}" in
  frost|nesvor|autosvrtk|niftymic) ;;
  *) echo "Invalid --reconstruction-tool: ${RECONSTRUCTION_TOOL}" >&2; exit 1 ;;
esac

if [[ -n "${COMPARE_RECONSTRUCTION_TOOLS}" && "${COMPARE_RECONSTRUCTION_TOOLS}" != "all" ]]; then
  for comparison_tool in ${COMPARE_RECONSTRUCTION_TOOLS//,/ }; do
    case "${comparison_tool}" in
      frost|nesvor|autosvrtk|niftymic) ;;
      *) echo "Invalid --compare-reconstruction-tools entry: ${comparison_tool}" >&2; exit 1 ;;
    esac
  done
fi

if [[ "${SURFACE_MODE}" != "auto" && "${SURFACE_MODE}" != "on" && "${SURFACE_MODE}" != "off" ]]; then
  echo "Invalid --surface: ${SURFACE_MODE}" >&2
  exit 1
fi
if [[ "${REGISTRATION_PRESET}" != "full" && "${REGISTRATION_PRESET}" != "fast" ]]; then
  echo "Invalid --registration-preset: ${REGISTRATION_PRESET}" >&2
  exit 1
fi
if ! [[ "${REGISTRATION_ORIENTATION_JOBS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Invalid --orientation-jobs: ${REGISTRATION_ORIENTATION_JOBS}" >&2
  exit 1
fi
if ! [[ "${REGISTRATION_ITK_THREADS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Invalid --itk-threads: ${REGISTRATION_ITK_THREADS}" >&2
  exit 1
fi
if ! [[ "${REGISTRATION_CASE_JOBS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Invalid --registration-case-jobs: ${REGISTRATION_CASE_JOBS}" >&2
  exit 1
fi

step_enabled() {
  [[ ",${REQUESTED_STEPS}," == *",$1,"* ]]
}

for requested_step in ${REQUESTED_STEPS//,/ }; do
  case "${requested_step}" in extraction|reconstruction|registration|tissue|roi|surface) ;;
    *) echo "Invalid --steps entry: ${requested_step}" >&2; exit 2 ;;
  esac
done

if [[ "${DASHBOARD_MODE}" != "auto" && "${DASHBOARD_MODE}" != "on" && "${DASHBOARD_MODE}" != "off" ]]; then
  echo "Invalid --dashboard: ${DASHBOARD_MODE}" >&2
  exit 1
fi

if [[ ! -d "${SUBJECT_DIR}" ]]; then
  echo "Subject directory not found: ${SUBJECT_DIR}" >&2
  exit 1
fi

if ! find "${SUBJECT_DIR}" -maxdepth 1 -type f -name '*.nii.gz' | read -r _; then
  echo "No .nii.gz files found in ${SUBJECT_DIR}" >&2
  exit 1
fi

SUBJECT_DIR="$(realpath "${SUBJECT_DIR}")"
WORK_ROOT="$(realpath -m "${WORK_ROOT}")"
SUBJECT_NAME="$(basename "${SUBJECT_DIR}")"
SCRATCH_ROOT="${PIPELINE_SCRATCH_ROOT:-${WORK_ROOT}/scratch}"
EXTRACT_NNUNET_DATA_ROOT="${SCRATCH_ROOT}/extraction"
EXTRACT_NNUNET_RESULTS="${EXTRACT_NNUNET_RESULTS:-${REPO_ROOT}/Unet/nnUNet/nnUNet-master/nnUNetFrame/DATASET/nnUNet_results}"
TISSUE_MODEL_ROOT="${TISSUE_MODEL_ROOT:-${REPO_ROOT}/models/tissue_bs5_resenc_nnunet}"
TISSUE_WORK_ROOT="${SCRATCH_ROOT}/tissue"
ROI_WORK_ROOT="${SCRATCH_ROOT}/roi"

if [[ -n "${ROI_WARP_ENV}" ]]; then
  ROI_WARP_ENV="$(realpath -m "${ROI_WARP_ENV}")"
elif [[ -n "${TISSUE_WARP_FALLBACK_ENV}" ]]; then
  ROI_WARP_ENV="$(realpath -m "${TISSUE_WARP_FALLBACK_ENV}")"
elif [[ -n "${ROI_SEG_WARP_FALLBACK_ENV}" ]]; then
  ROI_WARP_ENV="$(realpath -m "${ROI_SEG_WARP_FALLBACK_ENV}")"
elif [[ -n "${ANTS_DIR}" ]]; then
  ants_dir_resolved="$(realpath -m "${ANTS_DIR}")"
  ants_env_candidate="$(dirname "${ants_dir_resolved}")"
  if [[ -x "${ants_env_candidate}/python" ]]; then
    ROI_WARP_ENV="${ants_env_candidate}"
  fi
fi

if step_enabled registration && [[ -n "${ANTS_DIR}" && ! -x "${ANTS_DIR}/antsRegistration" ]]; then
  echo "ANTs preflight failed: ${ANTS_DIR}/antsRegistration is not executable" >&2
  exit 2
fi
if step_enabled roi && [[ "${ROI_MODE}" == "warp" ]]; then
  if [[ -z "${ROI_WARP_ENV}" || ! -x "${ROI_WARP_ENV}/bin/python" ]]; then
    echo "ROI warp preflight failed: ROI_WARP_ENV/bin/python is unavailable" >&2
    exit 2
  fi
  if ! "${ROI_WARP_ENV}/bin/python" -c "import ants" >/dev/null 2>&1; then
    echo "ROI warp preflight failed: ${ROI_WARP_ENV}/bin/python cannot import ants" >&2
    exit 2
  fi
fi

STAGING_ROOT="${WORK_ROOT}/staging"
STAGING_SUBJECT_DIR="${STAGING_ROOT}/${SUBJECT_NAME}"
OUTPUT_ROOT="${WORK_ROOT}/outputs"
RECON_DIR="${OUTPUT_ROOT}/recon"
REG_DIR="${OUTPUT_ROOT}/registration"
REGISTERED_INPUT_DIR="${OUTPUT_ROOT}/registered_input"
TISSUE_DIR="${OUTPUT_ROOT}/Tissue"
ROI_DIR="${OUTPUT_ROOT}/ROI"
if [[ -n "${SURFACE_SUBJECTS_DIR}" ]]; then
  SURFACE_SUBJECTS_DIR="$(realpath -m "${SURFACE_SUBJECTS_DIR}")"
else
  SURFACE_SUBJECTS_DIR="${OUTPUT_ROOT}/surface_subjects"
fi
SURFACE_SUBJECT_DIR="${SURFACE_SUBJECTS_DIR}/${SUBJECT_NAME}"

DASHBOARD_ENABLED=0
DASHBOARD_PREVIEW_ENABLED=0
DASHBOARD_RUN_DIR=""
DASHBOARD_LOG_DIR="${WORK_ROOT}/logs"
DASHBOARD_PREVIEW_DIR=""
DASHBOARD_URL=""
DASHBOARD_PYTHON=""

mkdir -p "${STAGING_SUBJECT_DIR}" "${RECON_DIR}" "${REG_DIR}" "${REGISTERED_INPUT_DIR}" "${TISSUE_DIR}" "${ROI_DIR}" "${SURFACE_SUBJECTS_DIR}"
mkdir -p "${DASHBOARD_LOG_DIR}"

# One writer per work root. Hold the lock in flock(1) with --close so children
# (Dashboard, reconstruction workers) do not inherit the lock fd. Inherited fd 9
# used to keep --resume from starting (exit 75) after a finished run.
if [[ "${AUTORECON_PIPELINE_LOCKED:-}" != "1" ]]; then
  if flock --help 2>&1 | grep -q -- '--close'; then
    export AUTORECON_PIPELINE_LOCKED=1
    set +e
    flock -n -o -E 75 "${WORK_ROOT}/.pipeline.lock" bash "${BASH_SOURCE[0]}" "${PIPELINE_ARGV[@]}"
    rc=$?
    set -e
    if [[ "${rc}" -eq 75 ]]; then
      echo "Another pipeline process is already using work root: ${WORK_ROOT}" >&2
      echo "If a previous run finished, stop leftover processes still holding ${WORK_ROOT}/.pipeline.lock." >&2
    fi
    exit "${rc}"
  fi
  exec 9>"${WORK_ROOT}/.pipeline.lock"
  if ! flock -n 9; then
    echo "Another pipeline process is already using work root: ${WORK_ROOT}" >&2
    echo "If a previous run finished, stop leftover processes still holding ${WORK_ROOT}/.pipeline.lock." >&2
    exit 75
  fi
fi

if step_enabled registration && [[ -z "${ATLAS_PATH}" ]]; then
  echo "Registration was selected but --atlas was not provided." >&2
  exit 2
fi
if (step_enabled tissue || step_enabled roi || step_enabled surface) && ! step_enabled registration \
  && [[ ! -f "${REGISTERED_INPUT_DIR}/${SUBJECT_NAME}.nii.gz" ]]; then
  echo "Tissue/ROI/surface require a registered MRI; select registration or resume from registered_input." >&2
  exit 2
fi

python_has_preview_deps() {
  local py="$1"
  "${py}" - <<'PY' >/dev/null 2>&1
import SimpleITK  # noqa: F401
import matplotlib  # noqa: F401
import numpy  # noqa: F401
import PIL  # noqa: F401
PY
}

select_dashboard_python() {
  local -a candidates=()
  local candidate=""

  if [[ -n "${DASHBOARD_PYTHON_OVERRIDE}" ]]; then
    candidates+=("${DASHBOARD_PYTHON_OVERRIDE}")
  fi
  if [[ -n "${ROI_WARP_ENV}" ]]; then
    candidates+=("${ROI_WARP_ENV}/bin/python")
  fi
  if [[ -n "${TISSUE_WARP_FALLBACK_ENV}" ]]; then
    candidates+=("${TISSUE_WARP_FALLBACK_ENV}/bin/python")
  fi
  if [[ -n "${ROI_SEG_WARP_FALLBACK_ENV}" ]]; then
    candidates+=("${ROI_SEG_WARP_FALLBACK_ENV}/bin/python")
  fi
  candidates+=(
    "/home/zhaojunyang/.conda/envs/zjy/bin/python"
    "/home/wangxiao/.conda/envs/frost/bin/python"
    "/home/wangxiao/.conda/envs/nunet/bin/python"
  )
  if command -v python3 >/dev/null 2>&1; then
    candidates+=("$(command -v python3)")
  fi
  if command -v python >/dev/null 2>&1; then
    candidates+=("$(command -v python)")
  fi

  for candidate in "${candidates[@]}"; do
    [[ -n "${candidate}" && -x "${candidate}" ]] || continue
    if python_has_preview_deps "${candidate}"; then
      DASHBOARD_PYTHON="${candidate}"
      DASHBOARD_PREVIEW_ENABLED=1
      return 0
    fi
  done

  for candidate in "${candidates[@]}"; do
    [[ -n "${candidate}" && -x "${candidate}" ]] || continue
    DASHBOARD_PYTHON="${candidate}"
    DASHBOARD_PREVIEW_ENABLED=0
    return 0
  done

  return 1
}

monitor_cmd() {
  if [[ "${DASHBOARD_ENABLED}" != "1" ]]; then
    return 0
  fi
  "${DASHBOARD_PYTHON}" "${REPO_ROOT}/vis/pipeline_dashboard.py" "$@"
}

step_index_for() {
  case "$1" in
    extraction) echo 1 ;;
    reconstruction) echo 2 ;;
    registration) echo 3 ;;
    tissue) echo 4 ;;
    roi) echo 5 ;;
    surface) echo 6 ;;
    *)
      echo "Unknown step id: $1" >&2
      return 1
      ;;
  esac
}

step_log_path() {
  local step_id="$1"
  local step_index
  step_index="$(step_index_for "${step_id}")"
  printf '%s/%02d_%s.log\n' "${DASHBOARD_LOG_DIR}" "${step_index}" "${step_id}"
}

step_preview_path() {
  local step_id="$1"
  local step_index
  step_index="$(step_index_for "${step_id}")"
  printf '%s/%02d_%s.png\n' "${DASHBOARD_PREVIEW_DIR}" "${step_index}" "${step_id}"
}

dashboard_update_step() {
  local step_id="$1"
  local status="$2"
  local message="$3"
  local preview_path="${4:-}"
  shift 4 || true

  if [[ "${DASHBOARD_ENABLED}" != "1" ]]; then
    return 0
  fi

  local log_path
  log_path="$(step_log_path "${step_id}")"

  local -a cmd=(
    update-step
    --run-dir "${DASHBOARD_RUN_DIR}"
    --step-id "${step_id}"
    --status "${status}"
    --log-path "${log_path}"
    --message "${message}"
  )

  if [[ -n "${preview_path}" ]]; then
    cmd+=(--preview "${preview_path}")
  fi

  local artifact
  for artifact in "$@"; do
    [[ -n "${artifact}" ]] || continue
    cmd+=(--artifact "${artifact}")
  done

  monitor_cmd "${cmd[@]}"
}

dashboard_step_start() {
  local step_id="$1"
  local message="$2"

  CURRENT_STEP_ID="${step_id}"

  if [[ "${DASHBOARD_ENABLED}" != "1" ]]; then
    return 0
  fi

  local log_path
  log_path="$(step_log_path "${step_id}")"
  mkdir -p "$(dirname "${log_path}")"
  : > "${log_path}"
  dashboard_update_step "${step_id}" "running" "${message}" ""
}

dashboard_step_finish() {
  local step_id="$1"
  local message="$2"
  local preview_path="${3:-}"
  shift 3 || true

  dashboard_update_step "${step_id}" "completed" "${message}" "${preview_path}" "$@"
  if [[ "${DASHBOARD_ENABLED}" == "1" ]]; then
    python "${PROJECT_ROOT}/agentic/qc.py" \
      --work-root "${WORK_ROOT}" \
      --subject "${SUBJECT_NAME}" \
      --steps "${REQUESTED_STEPS}" \
      --output "${DASHBOARD_RUN_DIR}/qc_summary.json" >/dev/null 2>&1 || true
  fi
  CURRENT_STEP_ID=""
}

dashboard_step_fail() {
  local step_id="$1"
  local message="$2"

  dashboard_update_step "${step_id}" "failed" "${message}" ""
  CURRENT_STEP_ID=""
}

dashboard_step_skip() {
  local step_id="$1"
  local message="$2"

  dashboard_update_step "${step_id}" "skipped" "${message}" ""
}

PIPELINE_STEP_ORDER=(extraction reconstruction registration tissue roi surface)
QC_GATE_MESSAGE=""

qc_summary_path() {
  mkdir -p "${WORK_ROOT}/dashboard"
  printf '%s\n' "${WORK_ROOT}/dashboard/qc_summary.json"
}

run_qc_gate() {
  local gate_json code
  gate_json="$(mktemp "${TMPDIR:-/tmp}/autorecon-l0.XXXXXX")"
  set +e
  python "${PROJECT_ROOT}/agentic/qc.py" \
    --work-root "${WORK_ROOT}" \
    --subject "${SUBJECT_NAME}" \
    --steps "${REQUESTED_STEPS}" \
    --output "$(qc_summary_path)" \
    --gate-output "${gate_json}" \
    "$@"
  code=$?
  set -e
  QC_GATE_MESSAGE=""
  if [[ -f "${gate_json}" ]]; then
    QC_GATE_MESSAGE="$(python -c 'import json,sys; from pathlib import Path; raw=Path(sys.argv[1]).read_text(encoding="utf-8"); data=json.loads(raw) if raw.strip() else {}; print(data.get("message") or "")' "${gate_json}" 2>/dev/null || true)"
    rm -f "${gate_json}"
  fi
  return "${code}"
}

skip_downstream_from() {
  local failed_step="$1"
  local message="$2"
  local seen=0
  local step
  for step in "${PIPELINE_STEP_ORDER[@]}"; do
    if [[ "${step}" == "${failed_step}" ]]; then
      seen=1
      continue
    fi
    [[ "${seen}" == 1 ]] || continue
    if step_enabled "${step}"; then
      dashboard_step_skip "${step}" "未启动：上游 ${failed_step} L0 合同失败。${message}"
    fi
  done
}

enforce_step_l0() {
  local step_id="$1"
  if run_qc_gate --enforce-step "${step_id}"; then
    return 0
  fi
  local message="${QC_GATE_MESSAGE:-${step_id} L0 合同失败，下游不启动。}"
  dashboard_step_fail "${step_id}" "${message}"
  skip_downstream_from "${step_id}" "${message}"
  echo "${message}" >&2
  exit 1
}

gate_next_l0() {
  local next_step="$1"
  if run_qc_gate --gate-next "${next_step}"; then
    return 0
  fi
  local message="${QC_GATE_MESSAGE:-上游 L0 合同失败，不启动 ${next_step}。}"
  dashboard_step_skip "${next_step}" "未启动：${message}"
  skip_downstream_from "${next_step}" "${message}"
  echo "${message}" >&2
  exit 1
}

dashboard_finalize() {
  local message="$1"
  local status="${2:-}"
  local exit_code="${3:-}"

  if [[ "${DASHBOARD_ENABLED}" != "1" ]]; then
    return 0
  fi

  local -a cmd=(finalize --run-dir "${DASHBOARD_RUN_DIR}" --message "${message}")
  if [[ -n "${status}" ]]; then
    cmd+=(--status "${status}")
  fi
  if [[ -n "${exit_code}" ]]; then
    cmd+=(--exit-code "${exit_code}")
  fi
  monitor_cmd "${cmd[@]}"
}

run_logged_command() {
  local log_path="$1"
  shift

  set +e
  "$@" 2>&1 | tee "${log_path}"
  local cmd_status="${PIPESTATUS[0]}"
  set -e
  return "${cmd_status}"
}

find_apptainer() {
  if [[ -n "${APPTAINER_BIN}" && -x "${APPTAINER_BIN}" ]]; then
    printf '%s\n' "${APPTAINER_BIN}"
  elif command -v apptainer >/dev/null 2>&1; then
    command -v apptainer
  elif [[ -x /mnt/sda/huangwei/conda_envs/apptainer/bin/apptainer ]]; then
    printf '%s\n' /mnt/sda/huangwei/conda_envs/apptainer/bin/apptainer
  else
    return 1
  fi
}

run_pipeline_container() {
  local image_name="$1"
  shift
  local apptainer
  apptainer="$(find_apptainer)" || {
    echo "Apptainer is unavailable; set APPTAINER_BIN." >&2
    return 127
  }
  local image="${RUNTIME_ROOT}/containers/${image_name}"
  if [[ ! -r "${image}" ]]; then
    echo "Container image is unavailable: ${image}" >&2
    return 2
  fi
  local -a command=("${apptainer}" exec --cleanenv --nv)
  command+=(--env "MPLCONFIGDIR=/tmp/matplotlib-${UID}")
  if [[ -n "${CUDA_VISIBLE_DEVICES:-}" ]]; then
    command+=(--env "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}")
  fi
  command+=(--bind "${PROJECT_ROOT}:${PROJECT_ROOT}:rw")
  if [[ "${WORK_ROOT}" != "${PROJECT_ROOT}" && "${WORK_ROOT}" != "${PROJECT_ROOT}/"* ]]; then
    command+=(--bind "${WORK_ROOT}:${WORK_ROOT}:rw")
  fi
  local extra_bind
  for extra_bind in "${CONTAINER_EXTRA_BINDS[@]+"${CONTAINER_EXTRA_BINDS[@]}"}"; do
    [[ -n "${extra_bind}" ]] || continue
    command+=(--bind "${extra_bind}")
  done
  command+=("${image}" "$@")
  "${command[@]}"
}

run_extraction_step() {
  local -a inner=(env
    ROOT_DIR="${STAGING_ROOT}"
    NNUNET_DATA_ROOT="${EXTRACT_NNUNET_DATA_ROOT}"
    EXTRACT_NNUNET_RAW="${EXTRACT_NNUNET_DATA_ROOT}/nnUNet_raw"
    EXTRACT_NNUNET_PREPROCESSED="${EXTRACT_NNUNET_DATA_ROOT}/nnUNet_preprocessed"
    EXTRACT_NNUNET_RESULTS="${EXTRACT_NNUNET_RESULTS}"
    bash "${REPO_ROOT}/00_extraction_patch.sh")
  if [[ "${PIPELINE_USE_CONTAINERS}" == "1" ]]; then
    run_pipeline_container extraction_nnunet.sif "${inner[@]}"
  else
    "${inner[@]}"
  fi
}

run_tissue_step() {
  local tissue_code="${TISSUE_NNUNET_CODE}"
  if [[ ! -d "${tissue_code}" ]]; then
    echo "Tissue nnU-Net source not found: ${tissue_code}" >&2
    echo "Set TISSUE_NNUNET_CODE to the tree that contains nnUNetTrainer_BS5." >&2
    return 1
  fi
  if [[ ! -f "${tissue_code}/nnunetv2/training/nnUNetTrainer/variants/nnUNetTrainer_BS5.py" ]]; then
    echo "Missing nnUNetTrainer_BS5 in ${tissue_code}" >&2
    return 1
  fi
  local -a inner=(env
    SRC_DIR="${ANALYSIS_INPUT_DIR}"
    TISSUE_DIR="${TISSUE_DIR}"
    MODEL_ROOT="${TISSUE_MODEL_ROOT}"
    INPUT_DIR="${TISSUE_WORK_ROOT}/imagesTs"
    OUTPUT_DIR="${TISSUE_WORK_ROOT}/labelsTs"
    TISSUE_NNUNET_CODE="${tissue_code}"
    bash "${REPO_ROOT}/02_seg_patch.sh")
  local -a saved_binds=("${CONTAINER_EXTRA_BINDS[@]+"${CONTAINER_EXTRA_BINDS[@]}"}")
  CONTAINER_EXTRA_BINDS+=("${tissue_code}:${tissue_code}:ro")
  local status=0
  set +e
  if [[ "${PIPELINE_USE_CONTAINERS}" == "1" ]]; then
    run_pipeline_container tissue_nnunet.sif "${inner[@]}"
  else
    "${inner[@]}"
  fi
  status=$?
  set -e
  CONTAINER_EXTRA_BINDS=("${saved_binds[@]+"${saved_binds[@]}"}")
  return "${status}"
}

run_surface_reconstruction() {
  local img_nii="$1"
  local seg_nii="$2"
  local roi_nii="$3"
  local subject_id="$4"
  local subjects_dir="$5"

  local setup_script="${FREESURFER_HOME}/SetUpFreeSurfer.sh"
  if [[ ! -f "${setup_script}" ]]; then
    echo "Missing FreeSurfer setup script: ${setup_script}" >&2
    return 1
  fi
  if [[ ! -x "${SURFACE_PYTHON}" ]]; then
    echo "Missing SURFACE_PYTHON executable: ${SURFACE_PYTHON}" >&2
    return 1
  fi
  if ! "${SURFACE_PYTHON}" -c "import SimpleITK" >/dev/null 2>&1; then
    echo "SURFACE_PYTHON cannot import SimpleITK: ${SURFACE_PYTHON}" >&2
    return 1
  fi

  local path=""
  for path in "${img_nii}" "${seg_nii}" "${roi_nii}"; do
    if [[ ! -f "${path}" ]]; then
      echo "Missing input file: ${path}" >&2
      return 1
    fi
  done

  export SUBJECTS_DIR="$(realpath -m "${subjects_dir}")"
  local surface_subject_id
  surface_subject_id="$(basename "${subject_id}")"
  local surface_subject_path="${SUBJECTS_DIR}/${surface_subject_id}"

  # FreeSurfer setup script mutates shell state broadly, so contain it in a subshell.
  (
    set +u
    # shellcheck disable=SC1090
    source "${setup_script}"
    set -u

    local cmd=""
    for cmd in \
      mri_convert mri_binarize mri_mask mri_morphology mri_tessellate \
      mris_extract_main_component mris_smooth mris_remove_intersection \
      mris_curvature mris_inflate mris_place_surface mri_distance_transform \
      mri_segstats mri_vol2surf
    do
      if ! command -v "${cmd}" >/dev/null 2>&1; then
        echo "Missing required FreeSurfer command on PATH: ${cmd}" >&2
        exit 1
      fi
    done

    mkdir -p "${surface_subject_path}"/{mri,surf,label,stats,tmp}
    echo "Building surface subject under ${surface_subject_path}"

    mri_convert "${img_nii}" "${surface_subject_path}/mri/orig.mgz"
    mri_convert "${seg_nii}" "${surface_subject_path}/mri/seg4.mgz"
    mri_convert "${roi_nii}" "${surface_subject_path}/mri/roi86.mgz"

    mri_binarize --i "${surface_subject_path}/mri/seg4.mgz" --min 1 --o "${surface_subject_path}/mri/brainmask.mgz"
    mri_mask "${surface_subject_path}/mri/orig.mgz" "${surface_subject_path}/mri/brainmask.mgz" "${surface_subject_path}/mri/brain.mgz"

    "${SURFACE_PYTHON}" - <<'PY' "${seg_nii}" "${surface_subject_path}/tmp"
import sys
from pathlib import Path
import numpy as np
import SimpleITK as sitk

seg_path = Path(sys.argv[1])
tmp_dir = Path(sys.argv[2])
tmp_dir.mkdir(parents=True, exist_ok=True)

seg = sitk.ReadImage(str(seg_path))
arr = sitk.GetArrayFromImage(seg)

def write_mask(mask, out_name):
    out = sitk.GetImageFromArray(mask.astype(np.uint8))
    out.CopyInformation(seg)
    sitk.WriteImage(out, str(tmp_dir / out_name))

has_label2 = np.any(arr == 2)
if has_label2:
    l_white = (arr == 1)
    r_white = (arr == 2)
    l_outer = np.isin(arr, [1, 3])
    r_outer = np.isin(arr, [2, 4])
    mode = "native_1_2_3_4"
else:
    if not np.any(arr == 1):
        raise RuntimeError("Fallback split requires label 1 white matter, but none was found.")
    if not np.any(arr == 3) or not np.any(arr == 4):
        raise RuntimeError("Fallback split requires cortex labels 3 and 4, but one is missing.")

    wm = (arr == 1)
    c3 = np.argwhere(arr == 3).mean(axis=0)
    c4 = np.argwhere(arr == 4).mean(axis=0)
    lr_axis = int(np.argmax(np.abs(c3 - c4)))

    axis_coords = np.indices(arr.shape, dtype=np.float32)[lr_axis]
    dist3 = np.abs(axis_coords - c3[lr_axis])
    dist4 = np.abs(axis_coords - c4[lr_axis])
    l_white = wm & (dist3 <= dist4)
    r_white = wm & ~l_white
    l_outer = l_white | (arr == 3)
    r_outer = r_white | (arr == 4)
    mode = f"split_label1_by_cortex_axis{lr_axis}"

write_mask(l_white, "l_white.nii.gz")
write_mask(r_white, "r_white.nii.gz")
write_mask(l_outer, "l_outer.nii.gz")
write_mask(r_outer, "r_outer.nii.gz")

print(f"[surface-mask] mode={mode}")
print(f"[surface-mask] l_white={int(l_white.sum())} r_white={int(r_white.sum())}")
print(f"[surface-mask] l_outer={int(l_outer.sum())} r_outer={int(r_outer.sum())}")
PY

    mri_convert "${surface_subject_path}/tmp/l_white.nii.gz" "${surface_subject_path}/tmp/l_white.mgz"
    mri_convert "${surface_subject_path}/tmp/r_white.nii.gz" "${surface_subject_path}/tmp/r_white.mgz"
    mri_convert "${surface_subject_path}/tmp/l_outer.nii.gz" "${surface_subject_path}/tmp/l_outer.mgz"
    mri_convert "${surface_subject_path}/tmp/r_outer.nii.gz" "${surface_subject_path}/tmp/r_outer.mgz"

    mri_morphology "${surface_subject_path}/tmp/l_white.mgz" erode 1 "${surface_subject_path}/tmp/l_white.e1.mgz"
    mri_morphology "${surface_subject_path}/tmp/l_white.e1.mgz" dilate 1 "${surface_subject_path}/tmp/l_white.ed.mgz"
    mri_morphology "${surface_subject_path}/tmp/r_white.mgz" erode 1 "${surface_subject_path}/tmp/r_white.e1.mgz"
    mri_morphology "${surface_subject_path}/tmp/r_white.e1.mgz" dilate 1 "${surface_subject_path}/tmp/r_white.ed.mgz"
    mv "${surface_subject_path}/tmp/l_white.ed.mgz" "${surface_subject_path}/tmp/l_white.mgz"
    mv "${surface_subject_path}/tmp/r_white.ed.mgz" "${surface_subject_path}/tmp/r_white.mgz"

    cd "${surface_subject_path}"

    mri_tessellate tmp/l_white.mgz 1 surf/lh.white.nofix
    mri_tessellate tmp/r_white.mgz 1 surf/rh.white.nofix
    mris_extract_main_component surf/lh.white.nofix surf/lh.white.nofix
    mris_extract_main_component surf/rh.white.nofix surf/rh.white.nofix
    mris_smooth -nw surf/lh.white.nofix surf/lh.white
    mris_smooth -nw surf/rh.white.nofix surf/rh.white
    mris_remove_intersection surf/lh.white surf/lh.white
    mris_remove_intersection surf/rh.white surf/rh.white

    mri_tessellate tmp/l_outer.mgz 1 surf/lh.pial.nofix
    mri_tessellate tmp/r_outer.mgz 1 surf/rh.pial.nofix
    mris_extract_main_component surf/lh.pial.nofix surf/lh.pial.nofix
    mris_extract_main_component surf/rh.pial.nofix surf/rh.pial.nofix
    mris_smooth -nw surf/lh.pial.nofix surf/lh.pial
    mris_smooth -nw surf/rh.pial.nofix surf/rh.pial
    mris_remove_intersection surf/lh.pial surf/lh.pial
    mris_remove_intersection surf/rh.pial surf/rh.pial

    mris_curvature -w -seed 1234 "${surface_subject_path}/surf/lh.pial"
    mris_curvature -w -seed 1234 "${surface_subject_path}/surf/rh.pial"
    mris_curvature -w -seed 1234 "${surface_subject_path}/surf/lh.white"
    mris_curvature -w -seed 1234 "${surface_subject_path}/surf/rh.white"

    mris_inflate "${surface_subject_path}/surf/lh.pial" "${surface_subject_path}/surf/lh.inflated"
    mris_inflate "${surface_subject_path}/surf/rh.pial" "${surface_subject_path}/surf/rh.inflated"

    mris_place_surface --area-map surf/lh.pial surf/lh.area.pial
    mris_place_surface --area-map surf/rh.pial surf/rh.area.pial
    mris_place_surface --area-map surf/lh.white surf/lh.area.white
    mris_place_surface --area-map surf/rh.white surf/rh.area.white

    mri_binarize --i mri/seg4.mgz --match 3 4 --o mri/cortex_mask.mgz
    mri_distance_transform mri/cortex_mask.mgz 1 50 2 mri/thickness_dist.mgz
    mri_mask mri/roi86.mgz mri/cortex_mask.mgz mri/roi86_cortexonly.mgz

    mri_segstats \
      --seg "${surface_subject_path}/mri/roi86_cortexonly.mgz" \
      --pv "${surface_subject_path}/mri/thickness_dist.mgz" \
      --sum "${surface_subject_path}/stats/roi86_thicknessproxy_cortexonly.stats" \
      --excludeid 0

    mri_segstats \
      --seg "${surface_subject_path}/mri/roi86.mgz" \
      --sum "${surface_subject_path}/stats/roi86_basic.stats" \
      --excludeid 0

    mri_vol2surf --src "${surface_subject_path}/mri/roi86.mgz" --out "${surface_subject_path}/surf/lh.roi86.pial.mgh" --regheader "${surface_subject_id}" --hemi lh --surf pial --interp nearest
    mri_vol2surf --src "${surface_subject_path}/mri/roi86.mgz" --out "${surface_subject_path}/surf/rh.roi86.pial.mgh" --regheader "${surface_subject_id}" --hemi rh --surf pial --interp nearest
    mri_vol2surf --src "${surface_subject_path}/mri/roi86.mgz" --out "${surface_subject_path}/surf/lh.roi86.white.mgh" --regheader "${surface_subject_id}" --hemi lh --surf white --interp nearest
    mri_vol2surf --src "${surface_subject_path}/mri/roi86.mgz" --out "${surface_subject_path}/surf/rh.roi86.white.mgh" --regheader "${surface_subject_id}" --hemi rh --surf white --interp nearest

    rm -f surf/lh.pial.nofix surf/rh.pial.nofix surf/lh.white.nofix surf/rh.white.nofix
  )
}

surface_output_complete() {
  local subject_dir="$1"
  local relative_path=""
  local -a required=(
    surf/lh.white surf/rh.white
    surf/lh.pial surf/rh.pial
    surf/lh.inflated surf/rh.inflated
    surf/lh.roi86.pial.mgh surf/rh.roi86.pial.mgh
    surf/lh.roi86.white.mgh surf/rh.roi86.white.mgh
    stats/roi86_thicknessproxy_cortexonly.stats
    stats/roi86_basic.stats
  )
  for relative_path in "${required[@]}"; do
    if [[ ! -s "${subject_dir}/${relative_path}" ]]; then
      return 1
    fi
  done
  return 0
}

render_dashboard_preview() {
  local step_id="$1"
  local image_path="$2"
  local overlay_path="${3:-}"
  local preview_title="${4:-}"
  local overlay_mode="${5:-label}"

  if [[ "${DASHBOARD_ENABLED}" != "1" || "${DASHBOARD_PREVIEW_ENABLED}" != "1" ]]; then
    return 0
  fi
  if [[ ! -f "${image_path}" ]]; then
    return 0
  fi

  local preview_path
  preview_path="$(step_preview_path "${step_id}")"

  local -a cmd=(
    render-preview
    --image "${image_path}"
    --output "${preview_path}"
    --title "${preview_title}"
    --overlay-mode "${overlay_mode}"
  )

  if [[ -n "${overlay_path}" && -f "${overlay_path}" ]]; then
    cmd+=(--overlay "${overlay_path}")
  fi

  if monitor_cmd "${cmd[@]}" >/dev/null 2>&1; then
    printf '%s\n' "${preview_path}"
  fi
}

setup_dashboard() {
  if [[ "${DASHBOARD_MODE}" == "off" ]]; then
    return 0
  fi

  if ! select_dashboard_python; then
    if [[ "${DASHBOARD_MODE}" == "on" ]]; then
      echo "Dashboard requested, but no usable Python interpreter was found." >&2
      exit 1
    fi
    echo "Dashboard disabled: no usable Python interpreter found."
    return 0
  fi

  DASHBOARD_ENABLED=1
  DASHBOARD_RUN_DIR="${WORK_ROOT}/dashboard"
  DASHBOARD_LOG_DIR="${DASHBOARD_RUN_DIR}/logs"
  DASHBOARD_PREVIEW_DIR="${DASHBOARD_RUN_DIR}/previews"
  DASHBOARD_URL="http://${DASHBOARD_HOST}:${DASHBOARD_PORT}"

  mkdir -p "${DASHBOARD_LOG_DIR}" "${DASHBOARD_PREVIEW_DIR}"
  echo "$$" > "${DASHBOARD_RUN_DIR}/pipeline.pid"
  monitor_cmd init \
    --run-dir "${DASHBOARD_RUN_DIR}" \
    --subject-name "${SUBJECT_NAME}" \
    --subject-dir "${SUBJECT_DIR}" \
    --work-root "${WORK_ROOT}" \
    --dashboard-url "${DASHBOARD_URL}" \
    --message "Preparing staging subject."

  for optional_step in extraction reconstruction registration tissue roi surface; do
    if ! step_enabled "${optional_step}"; then
      dashboard_step_skip "${optional_step}" "Not selected by the validated execution plan."
    fi
  done

  if step_enabled registration && [[ -z "${ATLAS_PATH}" ]]; then
    dashboard_step_skip "registration" "Skipped because --atlas was not provided."
  fi
  if [[ "${ROI_MODE}" == "skip" ]]; then
    dashboard_step_skip "roi" "Skipped because --roi-mode skip."
  fi
  if [[ "${SURFACE_MODE}" == "off" ]]; then
    dashboard_step_skip "surface" "Skipped because --surface off."
  elif [[ "${ROI_MODE}" == "skip" ]]; then
    dashboard_step_skip "surface" "Skipped because surface reconstruction requires ROI output."
  fi

  local server_log="${DASHBOARD_LOG_DIR}/server.log"
  set +e
  # Close fd 9 in the server (fallback flock path) and detach the session so a
  # leftover dashboard cannot keep the work-root lock or pipeline process group.
  (
    exec 9>&-
    if command -v setsid >/dev/null 2>&1; then
      exec setsid "${DASHBOARD_PYTHON}" "${REPO_ROOT}/vis/pipeline_dashboard.py" serve \
        --run-dir "${DASHBOARD_RUN_DIR}" \
        --host "${DASHBOARD_HOST}" \
        --port "${DASHBOARD_PORT}" \
        --replace </dev/null >"${server_log}" 2>&1
    else
      exec nohup "${DASHBOARD_PYTHON}" "${REPO_ROOT}/vis/pipeline_dashboard.py" serve \
        --run-dir "${DASHBOARD_RUN_DIR}" \
        --host "${DASHBOARD_HOST}" \
        --port "${DASHBOARD_PORT}" \
        --replace </dev/null >"${server_log}" 2>&1
    fi
  ) 9>&- &
  local server_pid=$!
  set -e
  echo "${server_pid}" > "${DASHBOARD_RUN_DIR}/server.pid"
  sleep 1
  if kill -0 "${server_pid}" >/dev/null 2>&1; then
    echo "Dashboard ready: ${DASHBOARD_URL}"
    echo "Dashboard root: ${DASHBOARD_RUN_DIR}"
  elif [[ "${DASHBOARD_MODE}" == "on" ]]; then
    echo "Dashboard server failed to start. See ${server_log}" >&2
    exit 1
  else
    echo "Dashboard assets created, but the server did not stay up. See ${server_log}"
  fi

  if [[ "${DASHBOARD_PREVIEW_ENABLED}" != "1" ]]; then
    echo "Dashboard is running without preview rendering dependencies. Logs and statuses will still update."
  fi
}

pipeline_exit_trap() {
  local exit_code=$?
  local finished_at
  finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [[ "${exit_code}" -ne 0 && -n "${CURRENT_STEP_ID:-}" ]]; then
    dashboard_step_fail "${CURRENT_STEP_ID}" "Step failed with exit code ${exit_code}."
  fi

  if [[ "${DASHBOARD_ENABLED}" == "1" ]]; then
    if [[ "${exit_code}" -eq 0 ]]; then
      dashboard_finalize "Pipeline finished successfully." "completed" "${exit_code}"
    else
      dashboard_finalize "Pipeline failed with exit code ${exit_code}." "failed" "${exit_code}"
    fi
  fi

  "${RECON_RUNNER_PYTHON}" -c '
import json, os, sys
path, code, started, finished, subject, backend, steps, preset = sys.argv[1:]
payload = {
    "schema_version": 1,
    "status": "completed" if int(code) == 0 else "failed",
    "exit_code": int(code),
    "started_at": started,
    "finished_at": finished,
    "subject": subject,
    "reconstruction_backend": backend,
    "requested_steps": [item for item in steps.split(",") if item],
    "registration_preset": preset,
}
temporary = path + ".tmp"
with open(temporary, "w", encoding="utf-8") as stream:
    json.dump(payload, stream, indent=2, ensure_ascii=False)
    stream.write("\n")
os.replace(temporary, path)
' "${WORK_ROOT}/pipeline_result.json" "${exit_code}" "${PIPELINE_STARTED_AT}" "${finished_at}" \
    "${SUBJECT_NAME}" "${RECONSTRUCTION_TOOL}" "${REQUESTED_STEPS}" "${REGISTRATION_PRESET}" || true
  return "${exit_code}"
}

pipeline_signal_trap() {
  local signal_number="$1"
  trap - INT TERM HUP
  exit "$((128 + signal_number))"
}

trap pipeline_exit_trap EXIT
trap 'pipeline_signal_trap 2' INT
trap 'pipeline_signal_trap 15' TERM
trap 'pipeline_signal_trap 1' HUP

setup_dashboard

if step_enabled extraction; then
EXTRACTION_STATE="${STAGING_SUBJECT_DIR}/seg/extraction_state.json"
if [[ "${RESUME_MODE}" == "1" ]] && python "${REPO_ROOT}/extraction_state.py" validate \
    --source-dir "${SUBJECT_DIR}" --staging-dir "${STAGING_SUBJECT_DIR}" \
    --runtime-root "${RUNTIME_ROOT}" --state "${EXTRACTION_STATE}" >/dev/null 2>&1; then
  echo "Step 1/6: reusing verified extraction output"
  printf '%s\n' "Reused verified extraction output; provenance: ${EXTRACTION_STATE}" > "$(step_log_path extraction)"
  dashboard_step_finish "extraction" "Reused existing extraction output (--resume)." "" "Extraction output=${STAGING_SUBJECT_DIR}/seg"
else
echo "Preparing staging subject under ${STAGING_SUBJECT_DIR}"
find "${STAGING_SUBJECT_DIR}" -maxdepth 1 -type l -name '*.nii.gz' -delete
find "${STAGING_SUBJECT_DIR}" -maxdepth 1 -type f -name '*.nii.gz' -delete
rm -rf "${STAGING_SUBJECT_DIR}/seg"

while IFS= read -r -d '' src_file; do
  cp -f "${src_file}" "${STAGING_SUBJECT_DIR}/$(basename "${src_file}")"
done < <(find "${SUBJECT_DIR}" -maxdepth 1 -type f -name '*.nii.gz' -print0 | sort -z)

echo "Step 1/6: 2D extraction"
dashboard_step_start "extraction" "Running 2D extraction on staging subject."
if ! run_logged_command "$(step_log_path extraction)" run_extraction_step; then
  dashboard_step_fail "extraction" "2D extraction failed. See the step log."
  exit 1
fi
python "${REPO_ROOT}/extraction_state.py" record \
  --source-dir "${SUBJECT_DIR}" --staging-dir "${STAGING_SUBJECT_DIR}" \
  --runtime-root "${RUNTIME_ROOT}" --state "${EXTRACTION_STATE}"
EXTRACTION_SAMPLE_INPUT="$(find "${STAGING_SUBJECT_DIR}" -maxdepth 1 -type f -name '*.nii.gz' | sort | head -n 1 || true)"
EXTRACTION_SAMPLE_SEG=""
if [[ -n "${EXTRACTION_SAMPLE_INPUT}" ]]; then
  EXTRACTION_SAMPLE_SEG="${STAGING_SUBJECT_DIR}/seg/$(basename "${EXTRACTION_SAMPLE_INPUT}")"
fi
EXTRACTION_PREVIEW="$(render_dashboard_preview "extraction" "${EXTRACTION_SAMPLE_INPUT:-}" "${EXTRACTION_SAMPLE_SEG:-}" "Step 1: 2D extraction" "mask" || true)"
EXTRACTION_VIEWER_ARTIFACT=""
if [[ "${DASHBOARD_ENABLED}" == "1" && "${DASHBOARD_PREVIEW_ENABLED}" == "1" ]]; then
  EXTRACTION_VIEWER="${DASHBOARD_PREVIEW_DIR}/01_extraction_interactive.html"
  if monitor_cmd render-stack-viewer \
    --image-dir "${STAGING_SUBJECT_DIR}" \
    --overlay-dir "${STAGING_SUBJECT_DIR}/seg" \
    --pattern '*.nii.gz' \
    --output "${EXTRACTION_VIEWER}" \
    --title "${SUBJECT_NAME} · 脑提取" >/dev/null 2>&1; then
    EXTRACTION_VIEWER_ARTIFACT="脑提取交互查看=${EXTRACTION_VIEWER}"
  fi
fi
dashboard_step_finish \
  "extraction" \
  "2D extraction finished." \
  "${EXTRACTION_PREVIEW:-}" \
  "Staging subject=${STAGING_SUBJECT_DIR}" \
  "Extraction output=${STAGING_SUBJECT_DIR}/seg" \
  "${EXTRACTION_VIEWER_ARTIFACT}"
fi
enforce_step_l0 extraction
fi

RECON_FILE="${RECON_DIR}/${SUBJECT_NAME}.nii.gz"
if step_enabled reconstruction; then
gate_next_l0 reconstruction

RECON_BACKEND_RESULT="${OUTPUT_ROOT}/reconstruction/${RECONSTRUCTION_TOOL}/result.json"
if [[ -z "${COMPARE_RECONSTRUCTION_TOOLS}" && "${RESUME_MODE}" == "1" && -f "${RECON_FILE}" && -f "${RECON_BACKEND_RESULT}" ]] \
  && "${RECON_RUNNER_PYTHON}" "${REPO_ROOT}/reconstruction/run_backend.py" \
    --backend "${RECONSTRUCTION_TOOL}" \
    --subject-dir "${STAGING_SUBJECT_DIR}" \
    --output-root "${OUTPUT_ROOT}" \
    --scratch-root "${SCRATCH_ROOT}" \
    --canonical-output "${RECON_FILE}" \
    --project-root "${PROJECT_ROOT}" \
    --validate-existing; then
  echo "Step 2/6: reusing reconstruction output"
  dashboard_step_finish "reconstruction" "Reused ${RECONSTRUCTION_TOOL} reconstruction output (--resume)." "" \
    "Reconstruction backend=${RECONSTRUCTION_TOOL}" "Reconstruction output=${RECON_FILE}" \
    "Backend result=${RECON_BACKEND_RESULT}"
else
echo "Step 2/6: 3D reconstruction"
dashboard_step_start "reconstruction" "Running ${RECONSTRUCTION_TOOL} reconstruction."
reconstruction_runner="${REPO_ROOT}/reconstruction/run_backend.py"
reconstruction_args=(
  --backend "${RECONSTRUCTION_TOOL}"
  --subject-dir "${STAGING_SUBJECT_DIR}"
  --output-root "${OUTPUT_ROOT}"
  --scratch-root "${SCRATCH_ROOT}"
  --canonical-output "${RECON_FILE}"
  --project-root "${PROJECT_ROOT}"
)
if [[ -n "${COMPARE_RECONSTRUCTION_TOOLS}" ]]; then
  reconstruction_runner="${REPO_ROOT}/reconstruction/run_comparison.py"
  reconstruction_args=(
    --selected "${RECONSTRUCTION_TOOL}"
    --subject-dir "${STAGING_SUBJECT_DIR}"
    --output-root "${OUTPUT_ROOT}"
    --scratch-root "${SCRATCH_ROOT}"
    --canonical-output "${RECON_FILE}"
    --project-root "${PROJECT_ROOT}"
    --backends
  )
  if [[ "${COMPARE_RECONSTRUCTION_TOOLS}" == "all" ]]; then
    reconstruction_args+=(frost nesvor autosvrtk niftymic)
  else
    read -r -a comparison_backends <<< "${COMPARE_RECONSTRUCTION_TOOLS//,/ }"
    reconstruction_args+=("${comparison_backends[@]}")
  fi
fi
if ! run_logged_command "$(step_log_path reconstruction)" \
  "${RECON_RUNNER_PYTHON}" "${reconstruction_runner}" "${reconstruction_args[@]}"; then
  dashboard_step_fail "reconstruction" "${RECONSTRUCTION_TOOL} reconstruction failed. See the step log."
  exit 1
fi

if [[ ! -f "${RECON_FILE}" ]]; then
  dashboard_step_fail "reconstruction" "Reconstruction finished but the output file is missing."
  echo "Reconstruction output missing: ${RECON_FILE}" >&2
  exit 1
fi

RECON_PREVIEW="$(render_dashboard_preview "reconstruction" "${RECON_FILE}" "" "Step 2: 3D reconstruction" "label" || true)"
RECON_VIEWER_ARTIFACT=""
if [[ "${DASHBOARD_ENABLED}" == "1" && "${DASHBOARD_PREVIEW_ENABLED}" == "1" ]]; then
  RECON_VIEWER="${DASHBOARD_PREVIEW_DIR}/02_reconstruction_interactive.html"
  if monitor_cmd render-mpr-viewer \
    --image "${RECON_FILE}" \
    --output "${RECON_VIEWER}" \
    --title "${SUBJECT_NAME} · 三维重建" >/dev/null 2>&1; then
    RECON_VIEWER_ARTIFACT="三维重建交互查看=${RECON_VIEWER}"
  fi
fi
dashboard_step_finish \
  "reconstruction" \
  "3D reconstruction finished with ${RECONSTRUCTION_TOOL}." \
  "${RECON_PREVIEW:-}" \
  "Reconstruction backend=${RECONSTRUCTION_TOOL}" \
  "Reconstruction output=${RECON_FILE}" \
  "Backend result=${RECON_BACKEND_RESULT}" \
  "${RECON_VIEWER_ARTIFACT}"
fi
enforce_step_l0 reconstruction
fi

REG_INPUT_DIR="${RECON_DIR}"
REGISTERED_FILE=""
ANALYSIS_INPUT_DIR="${RECON_DIR}"
ANALYSIS_IMAGE="${RECON_FILE}"
if step_enabled registration && [[ -n "${ATLAS_PATH}" ]]; then
  gate_next_l0 registration
  if [[ "${RESUME_MODE}" == "1" && -f "${REGISTERED_INPUT_DIR}/${SUBJECT_NAME}.nii.gz" ]]; then
    REGISTERED_FILE="${REGISTERED_INPUT_DIR}/${SUBJECT_NAME}.nii.gz"
    ANALYSIS_INPUT_DIR="${REGISTERED_INPUT_DIR}"
    ANALYSIS_IMAGE="${REGISTERED_FILE}"
    echo "Step 3/6: reusing registered MRI"
    dashboard_step_finish "registration" "Reused existing registered MRI (--resume)." "" "Registered image=${REGISTERED_FILE}"
  else
  if [[ ! -f "${ATLAS_PATH}" ]]; then
    echo "Atlas file not found: ${ATLAS_PATH}" >&2
    exit 1
  fi
  echo "Step 3/6: rigid registration"
  dashboard_step_start "registration" "Running ANTs rigid registration."
  reg_cmd=(
    python "${REPO_ROOT}/scripts/registration/run_ants_rigid_orient48_batch.py"
    --mode single
    --input-dir "${RECON_DIR}"
    --atlas "${ATLAS_PATH}"
    --output-dir "${REG_DIR}"
    --preset "${REGISTRATION_PRESET}"
    --case-jobs "${REGISTRATION_CASE_JOBS}"
    --orientation-jobs "${REGISTRATION_ORIENTATION_JOBS}"
    --itk-threads "${REGISTRATION_ITK_THREADS}"
  )
  if [[ -n "${ANTS_DIR}" ]]; then
    reg_cmd+=(--ants-dir "${ANTS_DIR}")
  fi
  if ! run_logged_command "$(step_log_path registration)" "${reg_cmd[@]}"; then
    dashboard_step_fail "registration" "Rigid registration failed. See the step log."
    exit 1
  fi

  for candidate_dir in \
    "${REG_DIR}/best" \
    "${REG_DIR}/acceptable_cases/best" \
    "${REG_DIR}/suspicious_cases/best"
  do
    if [[ -d "${candidate_dir}" ]] && find "${candidate_dir}" -maxdepth 1 -type f -name '*.nii.gz' | read -r _; then
      REG_INPUT_DIR="${candidate_dir}"
      break
    fi
  done

  REGISTERED_FILE="$(find "${REG_INPUT_DIR}" -maxdepth 1 -type f -name '*.nii.gz' | sort | head -n 1 || true)"
  if [[ -z "${REGISTERED_FILE}" || ! -f "${REGISTERED_FILE}" ]]; then
    dashboard_step_fail "registration" "Registration finished but no registered MRI was found."
    echo "Registered MRI missing under: ${REG_DIR}" >&2
    exit 1
  fi
  # Downstream models expect an input directory containing <subject>.nii.gz.
  # Normalize the registered output name once, then make steps 4-6 consume it.
  ANALYSIS_INPUT_DIR="${REGISTERED_INPUT_DIR}"
  ANALYSIS_IMAGE="${REGISTERED_INPUT_DIR}/${SUBJECT_NAME}.nii.gz"
  cp -f "${REGISTERED_FILE}" "${ANALYSIS_IMAGE}"
  REG_PREVIEW="$(render_dashboard_preview "registration" "${REGISTERED_FILE:-}" "" "Step 3: rigid registration" "label" || true)"
  REG_VIEWER_ARTIFACT=""
  if [[ "${DASHBOARD_ENABLED}" == "1" && "${DASHBOARD_PREVIEW_ENABLED}" == "1" && -f "${REGISTERED_FILE:-}" ]]; then
    REG_VIEWER="${DASHBOARD_PREVIEW_DIR}/03_registration_interactive.html"
    if monitor_cmd render-mpr-viewer \
      --image "${REGISTERED_FILE}" \
      --output "${REG_VIEWER}" \
      --title "${SUBJECT_NAME} · 图像配准" >/dev/null 2>&1; then
      REG_VIEWER_ARTIFACT="图像配准交互查看=${REG_VIEWER}"
    fi
  fi
  dashboard_step_finish \
    "registration" \
    "Rigid registration finished." \
    "${REG_PREVIEW:-}" \
    "Registration root=${REG_DIR}" \
    "Registered image=${REGISTERED_FILE:-${REG_DIR}}" \
    "${REG_VIEWER_ARTIFACT}"
  fi
  enforce_step_l0 registration
elif step_enabled tissue || step_enabled roi || step_enabled surface; then
  # A downstream-only resume must consume the normalized registered image,
  # rather than silently falling back to the unregistered reconstruction.
  REGISTERED_FILE="${REGISTERED_INPUT_DIR}/${SUBJECT_NAME}.nii.gz"
  ANALYSIS_INPUT_DIR="${REGISTERED_INPUT_DIR}"
  ANALYSIS_IMAGE="${REGISTERED_FILE}"
fi

if step_enabled tissue; then
gate_next_l0 tissue
if [[ "${RESUME_MODE}" == "1" && -f "${TISSUE_DIR}/${SUBJECT_NAME}.nii.gz" ]]; then
  TISSUE_FILE="${TISSUE_DIR}/${SUBJECT_NAME}.nii.gz"
  echo "Step 4/6: reusing tissue segmentation"
  dashboard_step_finish "tissue" "Reused existing tissue output (--resume)." "" "Analysis MRI=${ANALYSIS_IMAGE}" "Tissue output=${TISSUE_FILE}"
else
echo "Step 4/6: tissue segmentation"
dashboard_step_start "tissue" "Running 3D tissue segmentation."
if ! run_logged_command "$(step_log_path tissue)" run_tissue_step; then
  dashboard_step_fail "tissue" "Tissue segmentation failed. See the step log."
  exit 1
fi

TISSUE_FILE="${TISSUE_DIR}/${SUBJECT_NAME}.nii.gz"
if [[ ! -f "${TISSUE_FILE}" ]]; then
  dashboard_step_fail "tissue" "Tissue segmentation finished but the output file is missing."
  echo "Tissue output missing: ${TISSUE_FILE}" >&2
  exit 1
fi

TISSUE_PREVIEW="$(render_dashboard_preview "tissue" "${ANALYSIS_IMAGE}" "${TISSUE_FILE}" "Step 4: tissue segmentation on registered MRI" "label" || true)"
TISSUE_VIEWER_ARTIFACT=""
if [[ "${DASHBOARD_ENABLED}" == "1" && "${DASHBOARD_PREVIEW_ENABLED}" == "1" ]]; then
  TISSUE_VIEWER="${DASHBOARD_PREVIEW_DIR}/04_tissue_interactive.html"
  if monitor_cmd render-mpr-viewer \
    --image "${ANALYSIS_IMAGE}" \
    --overlay "${TISSUE_FILE}" \
    --overlay-label "组织标签" \
    --output "${TISSUE_VIEWER}" \
    --title "${SUBJECT_NAME} · 组织分割" >/dev/null 2>&1; then
    TISSUE_VIEWER_ARTIFACT="组织分割交互查看=${TISSUE_VIEWER}"
  fi
fi
dashboard_step_finish \
  "tissue" \
  "Tissue segmentation finished." \
  "${TISSUE_PREVIEW:-}" \
  "Analysis MRI=${ANALYSIS_IMAGE}" \
  "Tissue output=${TISSUE_FILE}" \
  "${TISSUE_VIEWER_ARTIFACT}"
fi
enforce_step_l0 tissue
fi

ROI_FILE=""
if step_enabled roi; then
gate_next_l0 roi
if [[ "${RESUME_MODE}" == "1" && -f "${ROI_DIR}/${SUBJECT_NAME}.nii.gz" ]]; then
  ROI_FILE="${ROI_DIR}/${SUBJECT_NAME}.nii.gz"
  echo "Step 5/6: reusing ROI output"
  dashboard_step_finish "roi" "Reused existing ROI output (--resume)." "" "Analysis MRI=${ANALYSIS_IMAGE}" "ROI output=${ROI_FILE}"
elif [[ "${ROI_MODE}" == "segresnet" ]]; then
  echo "Step 5/6: ROI segmentation with SegResNet"
  dashboard_step_start "roi" "Running ROI segmentation with SegResNet."
  if ! run_logged_command "$(step_log_path roi)" \
    env ROOT_DIR="${ANALYSIS_INPUT_DIR}" OUTPUT_ROOT="${ROI_DIR}" \
      PROJECT_DIR="${REPO_ROOT}" \
      INPUT_DIR="${ROI_WORK_ROOT}/imagesTs" \
      OUTPUT_DIR="${ROI_WORK_ROOT}/labelsTs" \
    bash "${REPO_ROOT}/02_seg_roi_patch.sh"; then
    dashboard_step_fail "roi" "ROI segmentation failed. See the step log."
    exit 1
  fi
  ROI_FILE="${ROI_DIR}/${SUBJECT_NAME}.nii.gz"
elif [[ "${ROI_MODE}" == "warp" ]]; then
  if [[ -z "${GA_VALUE}" ]]; then
    echo "--ga is required when --roi-mode warp" >&2
    exit 1
  fi
  echo "Step 5/6: ROI warp from atlas"
  dashboard_step_start "roi" "Warping ROI atlas labels to subject space."
  roi_warp_python="python"
  if [[ -n "${ROI_WARP_ENV}" ]]; then
    if [[ -x "${ROI_WARP_ENV}/bin/python" ]]; then
      roi_warp_python="${ROI_WARP_ENV}/bin/python"
    else
      dashboard_step_fail "roi" "ROI warp environment does not contain bin/python."
      echo "ROI warp env does not contain bin/python: ${ROI_WARP_ENV}" >&2
      exit 1
    fi
  fi
  if ! "${roi_warp_python}" -c "import ants" >/dev/null 2>&1; then
    dashboard_step_fail "roi" "Selected ROI warp Python cannot import ants."
    echo "Selected ROI warp python cannot import ants: ${roi_warp_python}" >&2
    echo "Pass --roi-warp-env /path/to/conda/env with antspy installed." >&2
    exit 1
  fi
  if ! run_logged_command "$(step_log_path roi)" \
    "${roi_warp_python}" "${REPO_ROOT}/src/ROI_warp/roi_warp.py" \
      --subject_img "${ANALYSIS_IMAGE}" \
      --ga "${GA_VALUE}" \
      --out_dir "${ROI_DIR}"; then
    dashboard_step_fail "roi" "ROI warp failed. See the step log."
    exit 1
  fi
  ROI_FILE="${ROI_DIR}/$(basename "${ANALYSIS_IMAGE}")"
else
  echo "Step 5/6: ROI step skipped"
fi

if [[ "${ROI_MODE}" != "skip" ]]; then
  if [[ ! -f "${ROI_FILE}" ]]; then
    dashboard_step_fail "roi" "ROI step finished but the output file is missing."
    echo "ROI output missing: ${ROI_FILE}" >&2
    exit 1
  fi

  ROI_PREVIEW="$(render_dashboard_preview "roi" "${ANALYSIS_IMAGE}" "${ROI_FILE}" "Step 5: ROI result on registered MRI" "label" || true)"
  ROI_VIEWER_ARTIFACT=""
  if [[ "${DASHBOARD_ENABLED}" == "1" && "${DASHBOARD_PREVIEW_ENABLED}" == "1" ]]; then
    ROI_VIEWER="${DASHBOARD_PREVIEW_DIR}/05_roi_interactive.html"
    if monitor_cmd render-mpr-viewer \
      --image "${ANALYSIS_IMAGE}" \
      --overlay "${ROI_FILE}" \
      --overlay-label "脑区标签" \
      --output "${ROI_VIEWER}" \
      --title "${SUBJECT_NAME} · 脑区划分" >/dev/null 2>&1; then
      ROI_VIEWER_ARTIFACT="脑区分割交互查看=${ROI_VIEWER}"
    fi
  fi
  dashboard_step_finish \
    "roi" \
    "ROI step finished." \
    "${ROI_PREVIEW:-}" \
    "Analysis MRI=${ANALYSIS_IMAGE}" \
    "ROI output=${ROI_FILE}" \
    "${ROI_VIEWER_ARTIFACT}"
  enforce_step_l0 roi
fi
fi

SURFACE_OUTPUT_DIR=""
SURFACE_PREVIEW=""
SURFACE_VIEWER_ARTIFACT=""
if ! step_enabled surface; then
  :
elif [[ "${RESUME_MODE}" == "1" ]] && surface_output_complete "${SURFACE_SUBJECT_DIR}"; then
  SURFACE_OUTPUT_DIR="${SURFACE_SUBJECT_DIR}"
  echo "Step 6/6: reusing surface output"
  dashboard_step_finish "surface" "Reused existing surface output (--resume)." "" "Surface subject=${SURFACE_OUTPUT_DIR}"
  enforce_step_l0 surface
elif [[ "${SURFACE_MODE}" == "off" ]]; then
  echo "Step 6/6: surface reconstruction skipped"
elif [[ "${ROI_MODE}" == "skip" || -z "${ROI_FILE}" || ! -f "${ROI_FILE}" ]]; then
  if [[ "${SURFACE_MODE}" == "on" ]]; then
    dashboard_step_fail "surface" "Surface reconstruction requires ROI output."
    echo "Surface reconstruction requires ROI output; rerun with --roi-mode segresnet|warp or set --surface auto|off." >&2
    exit 1
  fi
  dashboard_step_skip "surface" "Skipped because surface reconstruction requires ROI output."
  echo "Step 6/6: surface reconstruction skipped because ROI output is unavailable"
else
  gate_next_l0 surface
  echo "Step 6/6: surface reconstruction"
  dashboard_step_start "surface" "Running FreeSurfer-style surface reconstruction."
  if ! run_logged_command "$(step_log_path surface)" \
    run_surface_reconstruction "${ANALYSIS_IMAGE}" "${TISSUE_FILE}" "${ROI_FILE}" "${SUBJECT_NAME}" "${SURFACE_SUBJECTS_DIR}"; then
    dashboard_step_fail "surface" "Surface reconstruction failed. See the step log."
    exit 1
  fi

  SURFACE_OUTPUT_DIR="${SURFACE_SUBJECT_DIR}"
  if ! surface_output_complete "${SURFACE_OUTPUT_DIR}"; then
    dashboard_step_fail "surface" "Surface reconstruction finished but required artifacts are missing or empty."
    echo "Surface output is incomplete: ${SURFACE_OUTPUT_DIR}" >&2
    exit 1
  fi

  if [[ "${DASHBOARD_ENABLED}" == "1" && "${DASHBOARD_PREVIEW_ENABLED}" == "1" ]]; then
    SURFACE_PREVIEW="$(step_preview_path surface)"
    if ! monitor_cmd render-surface-preview \
      --surface-subject-dir "${SURFACE_OUTPUT_DIR}" \
      --output "${SURFACE_PREVIEW}" \
      --title "${SUBJECT_NAME} · 表面重建" >/dev/null 2>&1; then
      SURFACE_PREVIEW=""
    fi

    SURFACE_VIEWER="${DASHBOARD_PREVIEW_DIR}/06_surface_interactive.html"
    if monitor_cmd render-surface-html \
      --surface-subject-dir "${SURFACE_OUTPUT_DIR}" \
      --output "${SURFACE_VIEWER}" \
      --title "${SUBJECT_NAME} · 表面重建" >/dev/null 2>&1; then
      SURFACE_VIEWER_ARTIFACT="表面重建交互查看=${SURFACE_VIEWER}"
    fi
  fi

  dashboard_step_finish \
    "surface" \
    "Surface reconstruction finished." \
    "${SURFACE_PREVIEW:-}" \
    "Surface subject=${SURFACE_OUTPUT_DIR}" \
    "Surface surf=${SURFACE_OUTPUT_DIR}/surf" \
    "Surface stats=${SURFACE_OUTPUT_DIR}/stats" \
    "${SURFACE_VIEWER_ARTIFACT}"
  enforce_step_l0 surface
fi

cat <<EOF
Single-case pipeline finished.

Source subject: ${SUBJECT_DIR}
Staging subject: ${STAGING_SUBJECT_DIR}
Recon output: ${RECON_FILE}
Registration root: ${REG_DIR}
Tissue output: ${TISSUE_DIR}
ROI output: ${ROI_DIR}
Surface subjects: ${SURFACE_SUBJECTS_DIR}
EOF

if [[ "${DASHBOARD_ENABLED}" == "1" ]]; then
  cat <<EOF

Dashboard URL: ${DASHBOARD_URL}
Dashboard root: ${DASHBOARD_RUN_DIR}
EOF
fi

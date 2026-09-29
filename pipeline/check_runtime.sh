#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

EXTRACT_NUNET_ENV="${EXTRACT_NUNET_ENV:-/home/wangxiao/.conda/envs/nunet}"
FROST_CONDA_ENV="${FROST_CONDA_ENV:-/home/wangxiao/.conda/envs/frost}"
TISSUE_NUNET_ENV="${TISSUE_NUNET_ENV:-/home/zhaojunyang/.conda/envs/zjy}"
PIPELINE_DASHBOARD_PYTHON="${PIPELINE_DASHBOARD_PYTHON:-/home/zhaojunyang/.conda/envs/zjy/bin/python}"
ROI_WARP_ENV="${ROI_WARP_ENV:-/home/zhaojunyang/.conda/envs/zjy}"

required_files=(
  "${SCRIPT_DIR}/run_single_case_pipeline.sh"
  "${SCRIPT_DIR}/00_extraction_patch.sh"
  "${SCRIPT_DIR}/01_recon_patch.sh"
  "${SCRIPT_DIR}/02_seg_patch.sh"
  "${SCRIPT_DIR}/FROST/recon_all_patch.py"
  "${SCRIPT_DIR}/Unet/label.py"
  "${SCRIPT_DIR}/Unet/nnUNet/nnUNet-master/nnUNetFrame/DATASET/nnUNet_results/Dataset005_Organ/nnUNetTrainer__nnUNetPlans__2d/dataset.json"
  "${SCRIPT_DIR}/models/tissue_bs5_resenc_nnunet/nnUNet_results/Dataset003_Full/nnUNetTrainer_BS5__nnUNetResEncUNetLPlans__3d_fullres/dataset.json"
  "${SCRIPT_DIR}/data/FBA_Chinese_Atlas/img/31w.nii.gz"
  "${SCRIPT_DIR}/data/FBA_Chinese_Atlas/ROI/31w.nii.gz"
  "${SCRIPT_DIR}/vis/pipeline_dashboard.py"
  "${SCRIPT_DIR}/vis/pipeline_dashboard_template.html"
)

for path in "${required_files[@]}"; do
  if [[ ! -e "${path}" ]]; then
    echo "MISSING: ${path}" >&2
    exit 1
  fi
done

for path in \
  "${EXTRACT_NUNET_ENV}/bin/nnUNetv2_predict" \
  "${FROST_CONDA_ENV}/bin/python" \
  "${TISSUE_NUNET_ENV}/bin/nnUNetv2_predict" \
  "${PIPELINE_DASHBOARD_PYTHON}"
do
  if [[ ! -x "${path}" ]]; then
    echo "NOT EXECUTABLE: ${path}" >&2
    exit 1
  fi
done

"${FROST_CONDA_ENV}/bin/python" -c "import torch, SimpleITK, nibabel"
"${PIPELINE_DASHBOARD_PYTHON}" -c "import SimpleITK, matplotlib, numpy, PIL"
"${ROI_WARP_ENV}/bin/python" -c "import ants"

for script in "${SCRIPT_DIR}"/*.sh; do
  bash -n "${script}"
done

echo "Runtime check passed."

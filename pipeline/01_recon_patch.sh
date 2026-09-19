#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "======================================"
echo "🚀 A unified pipeline for 2D fetal brain reconstruction"
echo "======================================"

# 🐍 Initialize conda
CONDA_BASE=$(conda info --base)
source "${CONDA_BASE}/etc/profile.d/conda.sh"

# 💻 GPU settings
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-3}"
echo "💻 CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}"

# 🧵 Limit CPU threads
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=1

# Conda env
CONDA_ENV="${FROST_CONDA_ENV:-${CONDA_ENV:-/home/wangxiao/.conda/envs/frost}}"
echo "🐍 Reconstruction conda env: ${CONDA_ENV}"

# FROST project directory
FROST_DIR="${FROST_DIR:-${SCRIPT_DIR}/FROST}"

# 父目录：其下每个一级子文件夹是一个个体
# ROOT_DIR="/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain/IngeniaAmbition/tmp"
# ROOT_DIR="/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain/IngeniaAmbition_patch2/nii"
ROOT_DIR="${ROOT_DIR:-/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain/uMR790_3T_patch2/nii}"
# ROOT_DIR="/mnt/sda/public/00_Datasets/in_house/MRI/20260428-huaxi-fetal-cardiac/huaxi-fetal-cardiac_nii"
# ROOT_DIR="/mnt/sda/lx/00_Data/202605_huaxi_cardiac/"

# 最终 recon 输出目录
# OUT_DIR="/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain/IngeniaAmbition/recon"
# OUT_DIR="/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain/IngeniaAmbition_patch2/recon"
OUT_DIR="${OUT_DIR:-/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain/uMR790_3T_patch2/recon}"
# OUT_DIR="/mnt/sda/public/00_Datasets/in_house/MRI/20260428-huaxi-fetal-cardiac/recon"

mkdir -p "${OUT_DIR}"

if [[ ! -d "${ROOT_DIR}" ]]; then
  echo "❌ ROOT_DIR not found: ${ROOT_DIR}"
  exit 1
fi

cd "${FROST_DIR}" || {
  echo "❌ Failed to enter ${FROST_DIR}"
  exit 1
}

# echo "📍 Current directory: $(pwd)"
# echo "📂 ROOT_DIR: ${ROOT_DIR}"
# echo "📤 OUT_DIR: ${OUT_DIR}"

# 查找所有个体文件夹
mapfile -d '' subject_dirs < <(
  find "${ROOT_DIR}" \
    -mindepth 1 \
    -maxdepth 1 \
    -type d \
    ! -name "seg" \
    -print0 | sort -z
)

if [[ "${#subject_dirs[@]}" -eq 0 ]]; then
  echo "❌ No subject folders found under ${ROOT_DIR}"
  exit 1
fi

echo "🧠 Found ${#subject_dirs[@]} subject folders"

# =======================================
# Main loop: process subjects one by one
# =======================================

for FILE_DIR in "${subject_dirs[@]}"; do
  SUBJECT_NAME=$(basename "${FILE_DIR}")
  SEG_DIR="${FILE_DIR}/seg"
  FINAL_RECON="${OUT_DIR}/${SUBJECT_NAME}.nii.gz"

  echo ""
  echo "======================================"
  echo "🧠 Processing subject: ${SUBJECT_NAME}"
  echo "📂 FILE_DIR: ${FILE_DIR}"
  echo "🏷️ SEG_DIR: ${SEG_DIR}"
  echo "📤 FINAL_RECON: ${FINAL_RECON}"
  echo "======================================"

  if [[ ! -d "${SEG_DIR}" ]]; then
    echo "⚠️ SEG_DIR not found, skip subject: ${SEG_DIR}"
    continue
  fi
  # 如果文件夹下没有文件，跳过
  if [[ $(find "${FILE_DIR}" -type f -name "*.nii.gz" | wc -l) -eq 0 ]]; then
    echo "⚠️ No files found in ${FILE_DIR}, skip subject: ${SUBJECT_NAME}"
    continue
  fi
  

  # 如果已经重建过，可以跳过，避免重复计算
  if [[ -f "${FINAL_RECON}" ]]; then
    echo "✅ Existing recon found, skip: ${FINAL_RECON}"
    continue
  fi

  # echo "🔧 Running recon_all_patch.py for ${SUBJECT_NAME}"
  # # conda run -p "${CONDA_ENV}" python recon_all_patch.py \
  # # conda run -p "${CONDA_ENV}" python recon_all_prefix.py \
  # conda run -p "${CONDA_ENV}" python recon_all_patch.py \
  #   --file_dir "${FILE_DIR}" \
  #   --seg_dir "${SEG_DIR}" \
  #   --out_dir "${OUT_DIR}"

  # echo "✅ Reconstruction finished for subject: ${SUBJECT_NAME}"
  
  conda run -p "${CONDA_ENV}" python recon_all_patch.py \
    --file_dir "${FILE_DIR}" \
    --seg_dir "${SEG_DIR}" \
    --out_dir "${OUT_DIR}" || {
      echo "❌ Failed: ${SUBJECT_NAME}"
      echo "${SUBJECT_NAME}" >> "${OUT_DIR}/failed_subjects.txt"
      continue
    }

  # 如果只想先测试一个个体，取消下面这一行注释
#   break
done

echo ""
echo "======================================"
echo "🎉 All reconstruction finished"
echo "📤 Results saved to: ${OUT_DIR}"
echo "======================================"

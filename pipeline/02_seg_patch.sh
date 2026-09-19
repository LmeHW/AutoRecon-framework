#!/usr/bin/env bash
set -euo pipefail

echo "======================================"
echo "🚀 A unified pipeline for 3D fetal brain tissue segmentation"
echo "======================================"

# 💻 GPU settings
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-7}"
echo "💻 CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}"

# 🧵 Limit CPU threads
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=1

# ======================================
# User settings
# ======================================

# 输入：前一步得到的 3D 重建结果，每个 .nii.gz 是一个个体
SRC_DIR="${SRC_DIR:-/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain/IngeniaAmbition/recon}"

# 输出：组织分割结果
TISSUE_DIR="${TISSUE_DIR:-/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain/IngeniaAmbition/Tissue}"

# nnUNet env and model package
NUNET_ENV="${TISSUE_NUNET_ENV:-${NUNET_ENV:-/home/zhaojunyang/.conda/envs/zjy}}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_ROOT="${MODEL_ROOT:-${SCRIPT_DIR}/models/tissue_boundaryperturb_nnunet}"

export nnUNet_raw="${MODEL_ROOT}/nnUNet_raw"
export nnUNet_preprocessed="${MODEL_ROOT}/nnUNet_preprocessed"
export nnUNet_results="${MODEL_ROOT}/nnUNet_results"

# Isolated working folders for this model package.
INPUT_DIR="${INPUT_DIR:-${MODEL_ROOT}/work/Dataset003_Full/imagesTs}"
OUTPUT_DIR="${OUTPUT_DIR:-${MODEL_ROOT}/work/Dataset003_Full/labelsTs}"

DATASET_ID="${DATASET_ID:-3}"
TRAINER="${TRAINER:-nnUNetTrainerBoundaryPerturb_250epochs}"
CONFIG="${CONFIG:-3d_fullres}"
FOLD="${FOLD:-all}"
CHECKPOINT="${CHECKPOINT:-checkpoint_best.pth}"

mkdir -p "${INPUT_DIR}"
mkdir -p "${OUTPUT_DIR}"
mkdir -p "${TISSUE_DIR}"

echo "🐍 Segmentation conda env: ${NUNET_ENV}"
echo "📂 Source recon dir: ${SRC_DIR}"
echo "📥 nnUNet input dir: ${INPUT_DIR}"
echo "📤 nnUNet output dir: ${OUTPUT_DIR}"
echo "🧠 Tissue output dir: ${TISSUE_DIR}"

if [[ ! -d "${SRC_DIR}" ]]; then
  echo "❌ SRC_DIR not found: ${SRC_DIR}"
  exit 1
fi

# ======================================
# Step 1: Prepare nnUNet input
# ======================================

echo ""
echo "📂 Step 1: Preparing nnUNet input files"

echo "🧹 Cleaning existing files in ${INPUT_DIR}"
rm -f "${INPUT_DIR}"/*.nii.gz

echo "🧹 Cleaning existing files in ${OUTPUT_DIR}"
rm -f "${OUTPUT_DIR}"/*.nii.gz

MAP_FILE="${TISSUE_DIR}/case_name_mapping.tsv"
: > "${MAP_FILE}"
echo -e "case_base\toriginal_name\toriginal_path" > "${MAP_FILE}"

mapfile -d '' recon_files < <(
  find "${SRC_DIR}" \
    -maxdepth 1 \
    -type f \
    -name "*.nii.gz" \
    -print0 | sort -z
)

if [[ "${#recon_files[@]}" -eq 0 ]]; then
  echo "❌ No .nii.gz files found in ${SRC_DIR}"
  exit 1
fi

idx=0
prepared_count=0
skipped_count=0

for f in "${recon_files[@]}"; do
  original_name=$(basename "${f}")
  final_tissue="${TISSUE_DIR}/${original_name}"

  # 如果已经有结果，可以跳过，避免重复推理
  if [[ -f "${final_tissue}" ]]; then
    echo "✅ Existing tissue segmentation found, skip: ${original_name}"
    skipped_count=$((skipped_count + 1))
    continue
  fi

  printf -v case_id "%03d" "${idx}"
  case_base="case_${case_id}"
  dst_name="${case_base}_0000.nii.gz"

  # 使用软链接，减少大文件复制 I/O
  ln -sf "$(readlink -f "${f}")" "${INPUT_DIR}/${dst_name}"

  echo -e "${case_base}\t${original_name}\t${f}" >> "${MAP_FILE}"
  echo "Linked ${original_name} -> ${dst_name}"

  idx=$((idx + 1))
  prepared_count=$((prepared_count + 1))
  # break
done

echo "✅ Prepared ${prepared_count} files for nnUNet"
echo "⏭️ Skipped ${skipped_count} existing files"
echo "🧾 Mapping file saved to: ${MAP_FILE}"

if [[ "${prepared_count}" -eq 0 ]]; then
  echo "✅ No new files need tissue segmentation. Exit."
  exit 0
fi

# ======================================
# Step 2: Run nnUNet prediction
# ======================================

echo ""
echo "▶️ Step 2: Running tissue segmentation prediction"

"${NUNET_ENV}/bin/nnUNetv2_predict" \
  -i "${INPUT_DIR}" \
  -o "${OUTPUT_DIR}" \
  -d "${DATASET_ID}" \
  -tr "${TRAINER}" \
  -c "${CONFIG}" \
  -f "${FOLD}" \
  -chk "${CHECKPOINT}" \
  -npp 1 \
  -nps 1

echo "🧠 Tissue segmentation prediction finished"

# ======================================
# Step 3: Copy labels back with original names
# ======================================

echo ""
echo "📦 Step 3: Copy tissue labels back with original names"

copied_count=0
missing_count=0

tail -n +2 "${MAP_FILE}" | while IFS=$'\t' read -r case_base original_name original_path; do
  pred_label="${OUTPUT_DIR}/${case_base}.nii.gz"
  final_tissue="${TISSUE_DIR}/${original_name}"

  if [[ ! -f "${pred_label}" ]]; then
    echo "⚠️ Missing predicted label: ${pred_label}"
    missing_count=$((missing_count + 1))
    continue
  fi

  cp -f "${pred_label}" "${final_tissue}"
  echo "Copied ${case_base}.nii.gz -> ${final_tissue}"

  copied_count=$((copied_count + 1))
done

echo ""
echo "======================================"
echo "🎉 Tissue segmentation finished"
echo "📂 Input recon dir: ${SRC_DIR}"
echo "📤 Tissue output dir: ${TISSUE_DIR}"
echo "======================================"

#!/usr/bin/env bash
set -euo pipefail

echo "======================================"
echo "🚀 A unified pipeline for fetal brain ROI regional segmentation"
echo "======================================"

# 🐍 Initialize conda
CONDA_BASE=$(conda info --base)
source "${CONDA_BASE}/etc/profile.d/conda.sh"

# 💻 GPU settings
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
echo "💻 CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}"
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=1
export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"

# MPLCONFIGDIR="/mnt/sda/zhaojunyang/tmp/matplotlib"
# mkdir -p "${MPLCONFIGDIR}"
# export MPLCONFIGDIR

echo "🧵 OMP_NUM_THREADS=${OMP_NUM_THREADS}"
echo "🧵 ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=${ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS}"

# ============================================================
# User settings
# ============================================================

# 路径 A：其下每个 nii.gz 文件是一个重建后的 3D 个体
# 例如：
# ROOT_DIR/
#   subject_001.nii.gz
#   subject_002.nii.gz
# ROOT_DIR="/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain/uMR790_3T/recon"
ROOT_DIR="${ROOT_DIR:-/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain/uMR790_3T/registration}"
INPUT_PATTERN="*.nii.gz"

# 路径 B：ROI 分割结果直接保存到该目录下
# 例如：
# OUTPUT_ROOT/
#   subject_001.nii.gz
OUTPUT_ROOT="${OUTPUT_ROOT:-/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain/uMR790_3T/ROI}"
# OUTPUT_ROOT="/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain/uMR790_3T/ROI"

# SegResNet working directories
PROJECT_DIR="${PROJECT_DIR:-/mnt/sda/public/00_Projects/2512_AutoRecon}"
SEGRESNET_PROJECT_DIR="${SEGRESNET_PROJECT_DIR:-/mnt/sda/zhaojunyang/codes/fetal_seg/transformer_regional}"

INPUT_DIR="${INPUT_DIR:-/mnt/sda/zhaojunyang/codes/njgl/work/SegResNet_ROI/imagesTs}"
OUTPUT_DIR="${OUTPUT_DIR:-/mnt/sda/zhaojunyang/codes/njgl/work/SegResNet_ROI/labelsTs}"

# SegResNet environment
SEG_ENV="${ROI_SEG_ENV:-${SEG_ENV:-/home/zhaojunyang/.conda/envs/zjy}}"

# SegResNet model settings
PREDICT_SCRIPT="${PREDICT_SCRIPT:-${SEGRESNET_PROJECT_DIR}/predict_swinunetrv2_holdout.py}"
RUN_DIR="${RUN_DIR:-/mnt/sda/zhaojunyang/outputs/transformer_regional/model_zoo_dataset501/segresnet_roi96x128x96_f48_b2}"
CHECKPOINT="${CHECKPOINT:-${RUN_DIR}/checkpoint_best.pt}"
SW_BATCH_SIZE="${SW_BATCH_SIZE:-1}"
export PYTHONPATH="/mnt/sda/zhaojunyang/codes/vendor/monai_1_5_2:${PYTHONPATH:-}"

mkdir -p "${INPUT_DIR}"
mkdir -p "${OUTPUT_DIR}"

echo "🐍 Segmentation conda env: ${SEG_ENV}"
echo "📂 Root recon directory: ${ROOT_DIR}"
echo "🔎 Input file pattern: ${INPUT_PATTERN}"
echo "📥 SegResNet input dir: ${INPUT_DIR}"
echo "📤 SegResNet output dir: ${OUTPUT_DIR}"
echo "📦 ROI output root: ${OUTPUT_ROOT}"

# ============================================================
# Function: process one subject
# ============================================================

process_one_subject() {
    local SRC_FILE="$1"
    local SUBJECT_NAME
    SUBJECT_NAME=$(basename "${SRC_FILE}" .nii.gz)

    echo ""
    echo "======================================"
    echo "🧠 Processing subject: ${SUBJECT_NAME}"
    echo "📂 Source file: ${SRC_FILE}"
    echo "======================================"

    local SEG_DIR="${OUTPUT_ROOT}"
    mkdir -p "${SEG_DIR}"

    local MAP_FILE="${OUTPUT_DIR}/${SUBJECT_NAME}_case_name_mapping.tsv"

    # ------------------------------------------------------------
    # Step 1: File Matching & Rename
    # ------------------------------------------------------------
    echo "📂 Step 1: File matching & renaming"

    echo "🧹 Cleaning existing files in ${INPUT_DIR}"
    rm -f "${INPUT_DIR}"/*.nii.gz

    echo "🧹 Cleaning existing files in ${OUTPUT_DIR}"
    rm -f "${OUTPUT_DIR}"/*.nii.gz

    : > "${MAP_FILE}"
    echo -e "case_base\toriginal_name\toriginal_path" > "${MAP_FILE}"

    local case_base="case_001"
    local dst_name="${case_base}_0000.nii.gz"
    local original_name
    original_name=$(basename "${SRC_FILE}")

    # cp "${SRC_FILE}" "${INPUT_DIR}/${dst_name}"
    #change to link
    ln -sf "${SRC_FILE}" "${INPUT_DIR}/${dst_name}"

    echo -e "${case_base}\t${original_name}\t${SRC_FILE}" >> "${MAP_FILE}"
    echo "Copied ${original_name} -> ${dst_name}"

    echo "✅ Step 1 finished: Files prepared for SegResNet"
    echo "🧾 Mapping file saved to: ${MAP_FILE}"

    # ------------------------------------------------------------
    # Step 2: ROI Regional Segmentation
    # ------------------------------------------------------------
    echo "▶️ Step 2: Running ROI Regional Segmentation"

    conda run -p "${SEG_ENV}" python "${PREDICT_SCRIPT}" \
        --run-dir "${RUN_DIR}" \
        --checkpoint "${CHECKPOINT}" \
        --input-dir "${INPUT_DIR}" \
        --output-dir "${OUTPUT_DIR}" \
        --sw-batch-size "${SW_BATCH_SIZE}"

    echo "🧠 ROI Regional Segmentation finished"

    # ------------------------------------------------------------
    # Step 3: Copy labels directly to ROI output root with original names
    # ------------------------------------------------------------
    echo "📦 Step 3: Copy labels directly to ROI output root"

    local missing_count=0
    local copied_count=0

    tail -n +2 "${MAP_FILE}" | while IFS=$'\t' read -r case_base original_name original_path; do
        local pred_label="${OUTPUT_DIR}/${case_base}.nii.gz"
        local dst_label="${SEG_DIR}/${original_name}"

        if [[ ! -f "${pred_label}" ]]; then
            echo "⚠️ Missing predicted label: ${pred_label}"
            missing_count=$((missing_count + 1))
            continue
        fi

        cp -f "${pred_label}" "${dst_label}"
        echo "Copied label ${case_base}.nii.gz -> ROI/${original_name}"
        copied_count=$((copied_count + 1))
    done

    echo "✅ Step 3 finished for subject: ${SUBJECT_NAME}"
    echo "📁 ROI segmentation saved to: ${SEG_DIR}/${original_name}"

    rm -f "${MAP_FILE}"
}

# ============================================================
# Main loop: process all subjects
# ============================================================

echo ""
echo "🚀 Start processing all subjects under:"
echo "${ROOT_DIR}"

mapfile -d '' subject_files < <(
    find "${ROOT_DIR}" \
        -maxdepth 1 \
        -type f \
        -name "${INPUT_PATTERN}" \
        -print0 | sort -z
)

if [[ "${#subject_files[@]}" -eq 0 ]]; then
    echo "❌ No ${INPUT_PATTERN} files found under ${ROOT_DIR}"
    exit 1
fi

for subject_file in "${subject_files[@]}"; do
    process_one_subject "${subject_file}"
    # break
done

echo ""
echo "======================================"
echo "🎉 All subjects finished"
echo "======================================"
echo "The file path flow is:"
echo "Each recon file ${INPUT_PATTERN} -> ${INPUT_DIR} -> ${OUTPUT_DIR} -> ROI/"

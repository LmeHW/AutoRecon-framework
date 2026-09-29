#!/usr/bin/env bash
set -euo pipefail

echo "======================================"
echo "🚀 A unified pipeline for 2D fetal brain extraction"
echo "======================================"

# 💻 GPU settings
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-3}"
echo "💻 CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}"
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=1

echo "🧵 OMP_NUM_THREADS=${OMP_NUM_THREADS}"
echo "🧵 ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS=${ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS}"

# ============================================================
# User settings
# ============================================================

# 路径 A：其下每个一级子文件夹是一个个体
# 例如：
# ROOT_DIR/
#   subject_001/
#     aaa.nii.gz
#     bbb.nii.gz
#   subject_002/
#     xxx.nii.gz
#     yyy.nii.gz
# ROOT_DIR="/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain/IngeniaAmbition/nii"
# ROOT_DIR="/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain/IngeniaAmbition_patch2/nii"
ROOT_DIR="${ROOT_DIR:-/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain/uMR790_3T_patch2/nii}"

# nnUNet working directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NNUNET_PROJECT_DIR="${NNUNET_PROJECT_DIR:-${SCRIPT_DIR}/Unet}"
NNUNET_DATA_ROOT="${NNUNET_DATA_ROOT:-${NNUNET_PROJECT_DIR}/nnUNet/nnUNet-master/nnUNetFrame/DATASET}"

INPUT_DIR="${INPUT_DIR:-${NNUNET_DATA_ROOT}/nnUNet_raw/Dataset005_Organ/imagesTs}"
OUTPUT_DIR="${OUTPUT_DIR:-${NNUNET_DATA_ROOT}/nnUNet_raw/Dataset005_Organ/labelsTs}"

# nnUNet environment
NUNET_ENV="${EXTRACT_NUNET_ENV:-${NUNET_ENV:-/home/wangxiao/.conda/envs/nunet}}"

# nnUNet environment variables
# Do not inherit machine-level nnUNet_* defaults implicitly.
NNUNET_RAW_DIR="${EXTRACT_NNUNET_RAW:-${NNUNET_RAW_DIR:-${NNUNET_DATA_ROOT}/nnUNet_raw}}"
NNUNET_PREPROCESSED_DIR="${EXTRACT_NNUNET_PREPROCESSED:-${NNUNET_PREPROCESSED_DIR:-${NNUNET_DATA_ROOT}/nnUNet_preprocessed}}"
NNUNET_RESULTS_DIR="${EXTRACT_NNUNET_RESULTS:-${NNUNET_RESULTS_DIR:-${NNUNET_DATA_ROOT}/nnUNet_results}}"

export nnUNet_raw="${NNUNET_RAW_DIR}"
export nnUNet_preprocessed="${NNUNET_PREPROCESSED_DIR}"
export nnUNet_results="${NNUNET_RESULTS_DIR}"

DATASET_ID="${DATASET_ID:-005}"
DATASET_NAME="${DATASET_NAME:-Dataset005_Organ}"
CONFIG="${CONFIG:-2d}"
FOLD="${FOLD:-0}"
TRAINER_NAME="${TRAINER_NAME:-nnUNetTrainer}"
PLANS_NAME="${PLANS_NAME:-nnUNetPlans}"
MODEL_DIR="${nnUNet_results}/${DATASET_NAME}/${TRAINER_NAME}__${PLANS_NAME}__${CONFIG}"
MODEL_DATASET_JSON="${MODEL_DIR}/dataset.json"

mkdir -p "${INPUT_DIR}"
mkdir -p "${OUTPUT_DIR}"

echo "🐍 Segmentation conda env: ${NUNET_ENV}"
echo "📂 Root subject directory: ${ROOT_DIR}"
echo "📥 nnUNet input dir: ${INPUT_DIR}"
echo "📤 nnUNet output dir: ${OUTPUT_DIR}"
echo "🧭 nnUNet_raw=${nnUNet_raw}"
echo "🧭 nnUNet_preprocessed=${nnUNet_preprocessed}"
echo "🧭 nnUNet_results=${nnUNet_results}"
echo "🧠 Model dir: ${MODEL_DIR}"

if [[ ! -f "${MODEL_DATASET_JSON}" ]]; then
    echo "❌ nnUNet model metadata not found: ${MODEL_DATASET_JSON}" >&2
    echo "   Check nnUNet_results / dataset / trainer / config settings." >&2
    exit 1
fi

# ============================================================
# Function: process one subject
# ============================================================

process_one_subject() {
    local SRC_DIR="$1"
    local SUBJECT_NAME
    SUBJECT_NAME=$(basename "${SRC_DIR}")

    echo ""
    echo "======================================"
    echo "🧠 Processing subject: ${SUBJECT_NAME}"
    echo "📂 Source dir: ${SRC_DIR}"
    echo "======================================"

    local SEG_DIR="${SRC_DIR}/seg"
    mkdir -p "${SEG_DIR}"

    local MAP_FILE="${SEG_DIR}/case_name_mapping.tsv"

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

    mapfile -d '' nii_files < <(
        find "${SRC_DIR}" \
            -maxdepth 1 \
            -type f \
            -name "*.nii.gz" \
            -print0 | sort -z
    )

    if [[ "${#nii_files[@]}" -eq 0 ]]; then
        echo "⚠️ No .nii.gz files found in ${SRC_DIR}, skip."
        return 0
    fi

    local idx=1
    local f
    for f in "${nii_files[@]}"; do
        local case_id
        local case_base
        local dst_name
        local original_name

        printf -v case_id "%03d" "${idx}"
        case_base="case_${case_id}"
        dst_name="${case_base}_0000.nii.gz"
        original_name=$(basename "${f}")

        # cp "${f}" "${INPUT_DIR}/${dst_name}"
        #change to link
        ln -sf "${f}" "${INPUT_DIR}/${dst_name}"

        echo -e "${case_base}\t${original_name}\t${f}" >> "${MAP_FILE}"
        echo "Copied ${original_name} -> ${dst_name}"

        ((idx++))
    done

    echo "✅ Step 1 finished: Files prepared for nnUNet"
    echo "🧾 Mapping file saved to: ${MAP_FILE}"

    # ------------------------------------------------------------
    # Step 2: Brain Extraction
    # ------------------------------------------------------------
    echo "▶️ Step 2: Running Brain Extraction"

    env \
        nnUNet_raw="${nnUNet_raw}" \
        nnUNet_preprocessed="${nnUNet_preprocessed}" \
        nnUNet_results="${nnUNet_results}" \
        nnUNet_use_compressed="1" \
        "${NUNET_ENV}/bin/nnUNetv2_predict" \
        -i "${INPUT_DIR}" \
        -o "${OUTPUT_DIR}" \
        -d "${DATASET_ID}" \
        -c "${CONFIG}" \
        -f "${FOLD}" \
        -npp 1 \
        -nps 1

    echo "🧠 Brain Pre-Extraction finished"

    # ------------------------------------------------------------
    # Step 3: Label Post-processing
    # ------------------------------------------------------------
    echo "🏷️ Step 3: Running label post-processing"

    cd "${NNUNET_PROJECT_DIR}" || {
        echo "❌ Failed to enter Unet directory: ${NNUNET_PROJECT_DIR}"
        exit 1
    }

    "${NUNET_ENV}/bin/python" label.py "${OUTPUT_DIR}"

    echo "✅ Label post-processing finished"

    # ------------------------------------------------------------
    # Step 4: Copy labels back to subject/seg with original names
    # ------------------------------------------------------------
    echo "📦 Step 4: Copy labels back to original subject seg folder"

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
        echo "Copied label ${case_base}.nii.gz -> seg/${original_name}"
        copied_count=$((copied_count + 1))
    done

    echo "✅ Step 4 finished for subject: ${SUBJECT_NAME}"
    echo "📁 Segmentation saved to: ${SEG_DIR}"

    rm -f "${MAP_FILE}"
}

# ============================================================
# Main loop: process all subjects
# ============================================================

echo ""
echo "🚀 Start processing all subjects under:"
echo "${ROOT_DIR}"

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

for subject_dir in "${subject_dirs[@]}"; do
    process_one_subject "${subject_dir}"
    # break
done

echo ""
echo "======================================"
echo "🎉 All subjects finished"
echo "======================================"
echo "The file path flow is:"
echo "Each subject folder -> ${INPUT_DIR} -> ${OUTPUT_DIR} -> subject/seg/"

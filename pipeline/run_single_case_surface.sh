#!/usr/bin/env bash
set -euo pipefail

# Legacy helper:
#   the single-case surface step is now integrated into run_single_case_pipeline.sh.
# Use this script only when you already have recon/tissue/ROI outputs and want to rerun surface alone.

usage() {
  cat <<'EOF'
Usage:
  bash run_single_case_surface.sh \
    --img /path/to/recon_case.nii.gz \
    --seg /path/to/tissue_case.nii.gz \
    --roi /path/to/roi_case.nii.gz \
    --subject-id case_name \
    --subjects-dir /path/to/surface_subjects

What this does:
  - Builds one FreeSurfer-style subject directory
  - Creates white/pial proxy surfaces from the 4-class tissue segmentation
  - Computes curvature, inflated surfaces, ROI stats, and vol2surf outputs

Notes:
  - By default this script sources FreeSurfer from /mnt/sda/lx/00_Software/freesurfer.
    Override with FREESURFER_HOME if needed.
  - Requires FreeSurfer commands on PATH: mri_convert, mri_binarize, mri_mask, mri_tessellate,
    mri_morphology, mris_extract_main_component, mris_smooth, mris_remove_intersection, mris_curvature,
    mris_inflate, mris_place_surface, mri_distance_transform, mri_segstats, mri_vol2surf
EOF
}

IMG_NII=""
SEG_NII=""
ROI_NII=""
SUBJECT_ID=""
SUBJECTS_DIR=""
SURFACE_PYTHON="${SURFACE_PYTHON:-/home/zhaojunyang/.conda/envs/zjy/bin/python}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --img)
      IMG_NII="${2:-}"
      shift 2
      ;;
    --seg)
      SEG_NII="${2:-}"
      shift 2
      ;;
    --roi)
      ROI_NII="${2:-}"
      shift 2
      ;;
    --subject-id)
      SUBJECT_ID="${2:-}"
      shift 2
      ;;
    --subjects-dir)
      SUBJECTS_DIR="${2:-}"
      shift 2
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

if [[ -z "${IMG_NII}" || -z "${SEG_NII}" || -z "${ROI_NII}" || -z "${SUBJECT_ID}" || -z "${SUBJECTS_DIR}" ]]; then
  usage >&2
  exit 1
fi

FREESURFER_HOME="${FREESURFER_HOME:-/mnt/sda/lx/00_Software/freesurfer}"
if [[ ! -f "${FREESURFER_HOME}/SetUpFreeSurfer.sh" ]]; then
  echo "Missing FreeSurfer setup script: ${FREESURFER_HOME}/SetUpFreeSurfer.sh" >&2
  exit 1
fi

# FreeSurfer commands are usually provided via the setup script rather than login shell PATH.
# shellcheck disable=SC1090
set +e
set +u
set +o pipefail
source "${FREESURFER_HOME}/SetUpFreeSurfer.sh"
fs_setup_status=$?
set -e
set -u
set -o pipefail
if [[ "${fs_setup_status}" -ne 0 ]]; then
  echo "FreeSurfer setup failed with status ${fs_setup_status}" >&2
  exit "${fs_setup_status}"
fi
set -u

for path in "${IMG_NII}" "${SEG_NII}" "${ROI_NII}"; do
  if [[ ! -f "${path}" ]]; then
    echo "Missing input file: ${path}" >&2
    exit 1
  fi
done

export SUBJECTS_DIR="$(realpath -m "${SUBJECTS_DIR}")"
SUBJECT_ID="$(basename "${SUBJECT_ID}")"
S="${SUBJECTS_DIR}/${SUBJECT_ID}"

if [[ ! -x "${SURFACE_PYTHON}" ]]; then
  echo "Missing SURFACE_PYTHON executable: ${SURFACE_PYTHON}" >&2
  exit 1
fi
if ! "${SURFACE_PYTHON}" -c "import SimpleITK" >/dev/null 2>&1; then
  echo "SURFACE_PYTHON cannot import SimpleITK: ${SURFACE_PYTHON}" >&2
  exit 1
fi

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

mkdir -p "$S"/{mri,surf,label,stats,tmp}

echo "Building surface subject under ${S}"

mri_convert "${IMG_NII}" "$S/mri/orig.mgz"
mri_convert "${SEG_NII}" "$S/mri/seg4.mgz"
mri_convert "${ROI_NII}" "$S/mri/roi86.mgz"

mri_binarize --i "$S/mri/seg4.mgz" --min 1 --o "$S/mri/brainmask.mgz"
mri_mask "$S/mri/orig.mgz" "$S/mri/brainmask.mgz" "$S/mri/brain.mgz"

"${SURFACE_PYTHON}" - <<'PY' "${SEG_NII}" "$S/tmp"
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

mri_convert "$S/tmp/l_white.nii.gz" "$S/tmp/l_white.mgz"
mri_convert "$S/tmp/r_white.nii.gz" "$S/tmp/r_white.mgz"
mri_convert "$S/tmp/l_outer.nii.gz" "$S/tmp/l_outer.mgz"
mri_convert "$S/tmp/r_outer.nii.gz" "$S/tmp/r_outer.mgz"

mri_morphology "$S/tmp/l_white.mgz" erode 1 "$S/tmp/l_white.e1.mgz"
mri_morphology "$S/tmp/l_white.e1.mgz" dilate 1 "$S/tmp/l_white.ed.mgz"
mri_morphology "$S/tmp/r_white.mgz" erode 1 "$S/tmp/r_white.e1.mgz"
mri_morphology "$S/tmp/r_white.e1.mgz" dilate 1 "$S/tmp/r_white.ed.mgz"
mv "$S/tmp/l_white.ed.mgz" "$S/tmp/l_white.mgz"
mv "$S/tmp/r_white.ed.mgz" "$S/tmp/r_white.mgz"

cd "$S"

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

mris_curvature -w -seed 1234 "$S/surf/lh.pial"
mris_curvature -w -seed 1234 "$S/surf/rh.pial"
mris_curvature -w -seed 1234 "$S/surf/lh.white"
mris_curvature -w -seed 1234 "$S/surf/rh.white"

mris_inflate "$S/surf/lh.pial" "$S/surf/lh.inflated"
mris_inflate "$S/surf/rh.pial" "$S/surf/rh.inflated"

mris_place_surface --area-map surf/lh.pial surf/lh.area.pial
mris_place_surface --area-map surf/rh.pial surf/rh.area.pial
mris_place_surface --area-map surf/lh.white surf/lh.area.white
mris_place_surface --area-map surf/rh.white surf/rh.area.white

mri_binarize --i mri/seg4.mgz --match 3 4 --o mri/cortex_mask.mgz
mri_distance_transform mri/cortex_mask.mgz 1 50 2 mri/thickness_dist.mgz
mri_mask mri/roi86.mgz mri/cortex_mask.mgz mri/roi86_cortexonly.mgz

mri_segstats \
  --seg "$S/mri/roi86_cortexonly.mgz" \
  --pv "$S/mri/thickness_dist.mgz" \
  --sum "$S/stats/roi86_thicknessproxy_cortexonly.stats" \
  --excludeid 0

mri_segstats \
  --seg "$S/mri/roi86.mgz" \
  --sum "$S/stats/roi86_basic.stats" \
  --excludeid 0

mri_vol2surf \
  --src "$S/mri/roi86.mgz" \
  --out "$S/surf/lh.roi86.pial.mgh" \
  --regheader "$SUBJECT_ID" \
  --hemi lh \
  --surf pial \
  --interp nearest

mri_vol2surf \
  --src "$S/mri/roi86.mgz" \
  --out "$S/surf/rh.roi86.pial.mgh" \
  --regheader "$SUBJECT_ID" \
  --hemi rh \
  --surf pial \
  --interp nearest

mri_vol2surf \
  --src "$S/mri/roi86.mgz" \
  --out "$S/surf/lh.roi86.white.mgh" \
  --regheader "$SUBJECT_ID" \
  --hemi lh \
  --surf white \
  --interp nearest

mri_vol2surf \
  --src "$S/mri/roi86.mgz" \
  --out "$S/surf/rh.roi86.white.mgh" \
  --regheader "$SUBJECT_ID" \
  --hemi rh \
  --surf white \
  --interp nearest

rm -f "$S/surf/lh.pial.nofix" "$S/surf/rh.pial.nofix" "$S/surf/lh.white.nofix" "$S/surf/rh.white.nofix"

cat <<EOF
Single-case surface pipeline finished.

Subject ID: ${SUBJECT_ID}
Subjects dir: ${SUBJECTS_DIR}
Output subject dir: ${S}
EOF

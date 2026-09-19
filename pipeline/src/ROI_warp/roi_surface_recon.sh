#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   bash batch_fetal_surf.sh IMG_DIR SEG_DIR ROI_DIR CSV_PATH
#
# Example:
#   bash batch_fetal_surf.sh \
#     /mnt/sda/public/00_Projects/2512_AutoRecon/data/gfy_img \
#     /mnt/sda/public/00_Projects/2512_AutoRecon/data/gfy_seg \
#     /mnt/sda/public/00_Projects/2512_AutoRecon/data/gfy_roi \
#     /mnt/sda/public/00_Projects/2512_AutoRecon/results/gfy_results/gfy_surface_vol_all_with_age_dropna.csv

# IMG_DIR="/mnt/sda/public/00_Shares/Fetal_brain/gt"
# SEG_DIR="/mnt/sda/public/00_Projects/2512_AutoRecon/data/gfy_seg"
# ROI_DIR="/mnt/sda/public/00_Projects/2512_AutoRecon/data/gfy_ROI"
# CSV_PATH="/mnt/sda/public/00_Projects/2512_AutoRecon/results/gfy_results/gfy_surface_vol_all_with_age_dropna.csv"

IMG_DIR="/mnt/sda/public/00_Projects/2512_AutoRecon/data/recon"
SEG_DIR="/mnt/sda/public/00_Projects/2512_AutoRecon/data/recon_seg_remap"
# ROI_DIR="/mnt/sda/public/00_Projects/2512_AutoRecon/data/njgl_ROI"
ROI_DIR="/mnt/sda/public/00_Projects/2512_AutoRecon/data/njgl_Unet2ROI"
CSV_PATH="/mnt/sda/public/00_Projects/2512_AutoRecon/results/njgl_analysis/suface_vol_age_all.csv"

# Fixed output SUBJECTS_DIR
export SUBJECTS_DIR="/mnt/sda/public/00_Projects/2512_AutoRecon/data/njgl_surf_full"

mkdir -p "$SUBJECTS_DIR"

# -----------------------------
# Extract subj_names from CSV (robust)
# -----------------------------
mapfile -t SUBJ_NAMES < <(python3 - <<'PY'
import pandas as pd

CSV_PATH = "/mnt/sda/public/00_Projects/2512_AutoRecon/results/njgl_analysis/suface_vol_age_all_v2.csv"
df = pd.read_csv(CSV_PATH)

df.columns = [c.strip() for c in df.columns]
if "subj_names" not in df.columns:
    raise SystemExit(f"ERROR: CSV missing column 'subj_names'. columns={df.columns.tolist()}")

for x in df["subj_names"].dropna().astype(str):
    x = x.strip()
    if x:
        print(x)
PY
)

if [[ "${#SUBJ_NAMES[@]}" -eq 0 ]]; then
  echo "[ERROR] No subj_names found in CSV: $CSV_PATH" >&2
  exit 1
fi

echo "[INFO] Found ${#SUBJ_NAMES[@]} subjects in CSV."

# -----------------------------
# Main loop
# -----------------------------
for subj_mask in "${SUBJ_NAMES[@]}"; do
  # subj_names is like "xxxxxxxx-mask"
  base="$subj_mask"
  if [[ "$base" == *-mask ]]; then
    base="${base%-mask}"
  fi

  img_nii="${IMG_DIR}/${base}.nii.gz"
  roi_nii="${ROI_DIR}/${base}.nii.gz"
  seg_nii="${SEG_DIR}/${subj_mask}.nii.gz"   # note: keep -mask in filename

  if [[ ! -f "$img_nii" ]]; then
    echo "[SKIP] missing img: $img_nii"
    continue
  fi
  if [[ ! -f "$roi_nii" ]]; then
    echo "[SKIP] missing roi: $roi_nii"
    continue
  fi
  if [[ ! -f "$seg_nii" ]]; then
    echo "[SKIP] missing seg: $seg_nii"
    continue
  fi

  subj="$base"
  S="$SUBJECTS_DIR/$subj"

  echo "============================================================"
  echo "[RUN ] subj_mask=$subj_mask  subj=$subj"
  echo "      img=$img_nii"
  echo "      seg=$seg_nii"
  echo "      roi=$roi_nii"
  echo "      out=$S"
  echo "============================================================"

  mkdir -p "$S"/{mri,surf,label,stats,tmp}

  # -----------------------------
  # 0) Convert to mgz
  # -----------------------------
  mri_convert "$img_nii" "$S/mri/orig.mgz"
  mri_convert "$seg_nii" "$S/mri/seg4.mgz"
  mri_convert "$roi_nii" "$S/mri/roi86.mgz"

  # -----------------------------
  # 1) Brainmask from seg (>0)
  # -----------------------------
  mri_binarize --i "$S/mri/seg4.mgz" --min 1 --o "$S/mri/brainmask.mgz"
  mri_mask "$S/mri/orig.mgz" "$S/mri/brainmask.mgz" "$S/mri/brain.mgz"

  # -----------------------------
  # 2) Build hemisphere masks
  # -----------------------------
  mri_binarize --i "$S/mri/seg4.mgz" --match 1 --o "$S/tmp/l_white.mgz"
  mri_binarize --i "$S/mri/seg4.mgz" --match 2 --o "$S/tmp/r_white.mgz"

  mri_binarize --i "$S/mri/seg4.mgz" --match 1 3 --o "$S/tmp/l_outer.mgz"
  mri_binarize --i "$S/mri/seg4.mgz" --match 2 4 --o "$S/tmp/r_outer.mgz"

  # Clean small islands
  mri_morphology "$S/tmp/l_white.mgz" erode 1 "$S/tmp/l_white.e1.mgz"
  mri_morphology "$S/tmp/l_white.e1.mgz" dilate 1 "$S/tmp/l_white.ed.mgz"
  mri_morphology "$S/tmp/r_white.mgz" erode 1 "$S/tmp/r_white.e1.mgz"
  mri_morphology "$S/tmp/r_white.e1.mgz" dilate 1 "$S/tmp/r_white.ed.mgz"

  mv "$S/tmp/l_white.ed.mgz" "$S/tmp/l_white.mgz"
  mv "$S/tmp/r_white.ed.mgz" "$S/tmp/r_white.mgz"

  # -----------------------------
  # 3) Tessellate surfaces
  # -----------------------------
  cd "$S"

  # white (proxy-white)
  mri_tessellate tmp/l_white.mgz 1 surf/lh.white.nofix
  mri_tessellate tmp/r_white.mgz 1 surf/rh.white.nofix
  mris_extract_main_component surf/lh.white.nofix surf/lh.white.nofix
  mris_extract_main_component surf/rh.white.nofix surf/rh.white.nofix
  mris_smooth -nw surf/lh.white.nofix surf/lh.white
  mris_smooth -nw surf/rh.white.nofix surf/rh.white
  mris_remove_intersection surf/lh.white surf/lh.white
  mris_remove_intersection surf/rh.white surf/rh.white

  # Outer (proxy-pial)
  mri_tessellate tmp/l_outer.mgz 1 surf/lh.pial.nofix
  mri_tessellate tmp/r_outer.mgz 1 surf/rh.pial.nofix
  mris_extract_main_component surf/lh.pial.nofix surf/lh.pial.nofix
  mris_extract_main_component surf/rh.pial.nofix surf/rh.pial.nofix
  mris_smooth -nw surf/lh.pial.nofix surf/lh.pial
  mris_smooth -nw surf/rh.pial.nofix surf/rh.pial
  mris_remove_intersection surf/lh.pial surf/lh.pial
  mris_remove_intersection surf/rh.pial surf/rh.pial

  # -----------------------------
  # 4) Surface metrics: curvature + area
  # -----------------------------
  mris_curvature -w -seed 1234 "$S/surf/lh.pial"
  mris_curvature -w -seed 1234 "$S/surf/rh.pial"
  mris_curvature -w -seed 1234 "$S/surf/lh.white"
  mris_curvature -w -seed 1234 "$S/surf/rh.white"

  mris_inflate "$S/surf/lh.pial" "$S/surf/lh.inflated"
  mris_inflate "$S/surf/rh.pial" "$S/surf/rh.inflated"

  # area files
  mris_place_surface --area-map surf/lh.pial surf/lh.area.pial
  mris_place_surface --area-map surf/rh.pial surf/rh.area.pial
  mris_place_surface --area-map surf/lh.white surf/lh.area.white
  mris_place_surface --area-map surf/rh.white surf/rh.area.white

  # -----------------------------
  # 6) ROI stats + vol2surf
  # -----------------------------
  mri_binarize --i mri/seg4.mgz --match 3 4 --o mri/cortex_mask.mgz
  mri_distance_transform mri/cortex_mask.mgz 1 50 2 mri/thickness_dist.mgz

  mri_mask mri/roi86.mgz mri/cortex_mask.mgz mri/roi86_cortexonly.mgz

  mri_segstats \
    --seg "$S/mri/roi86_cortexonly.mgz" \
    --pv  "$S/mri/thickness_dist.mgz" \
    --sum "$S/stats/roi86_thicknessproxy_cortexonly.stats" \
    --excludeid 0

  mri_segstats \
    --seg "$S/mri/roi86.mgz" \
    --sum "$S/stats/roi86_basic.stats" \
    --excludeid 0

  mri_vol2surf \
    --src "$S/mri/roi86.mgz" \
    --out "$S/surf/lh.roi86.pial.mgh" \
    --regheader "$subj" \
    --hemi lh \
    --surf pial \
    --interp nearest

  mri_vol2surf \
    --src "$S/mri/roi86.mgz" \
    --out "$S/surf/rh.roi86.pial.mgh" \
    --regheader "$subj" \
    --hemi rh \
    --surf pial \
    --interp nearest

  mri_vol2surf \
    --src "$S/mri/roi86.mgz" \
    --out "$S/surf/lh.roi86.white.mgh" \
    --regheader "$subj" \
    --hemi lh \
    --surf white \
    --interp nearest

  mri_vol2surf \
    --src "$S/mri/roi86.mgz" \
    --out "$S/surf/rh.roi86.white.mgh" \
    --regheader "$subj" \
    --hemi rh \
    --surf white \
    --interp nearest

  rm -f "$S/surf/lh.pial.nofix" "$S/surf/rh.pial.nofix" "$S/surf/lh.white.nofix" "$S/surf/rh.white.nofix"

  echo "[DONE] subj=$subj"
  echo "  $S/surf (surfaces + curv/area)"
  echo "  $S/mri  (thickness proxy volumes)"
  echo "  $S/stats (roi stats)"
done

echo "[ALL DONE] SUBJECTS_DIR=$SUBJECTS_DIR"

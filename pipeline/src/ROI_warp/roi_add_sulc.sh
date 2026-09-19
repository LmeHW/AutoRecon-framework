#!/usr/bin/env bash
set -euo pipefail

IMG_DIR="/mnt/sda/public/00_Shares/Fetal_brain/gt"
SEG_DIR="/mnt/sda/public/00_Projects/2512_AutoRecon/data/gfy_seg"
ROI_DIR="/mnt/sda/public/00_Projects/2512_AutoRecon/data/gfy_ROI"
# CSV_PATH="/mnt/sda/public/00_Projects/2512_AutoRecon/results/njgl_analysis/suface_vol_age_all.csv"
export SUBJECTS_DIR="/mnt/sda/public/00_Projects/2512_AutoRecon/data/gfy_surf_full_56"

mapfile -t SUBJ_NAMES < <(python3 - <<'PY'
import pandas as pd

CSV_PATH = "/mnt/sda/public/00_Projects/2512_AutoRecon/results/gfy_results/gfy_surface_vol_all_with_age_dropna.csv"
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

  subj="$base"
  S="$SUBJECTS_DIR/$subj"
  mris_inflate "$S/surf/lh.pial" "$S/surf/lh.inflated"
  mris_inflate "$S/surf/rh.pial" "$S/surf/rh.inflated"
done
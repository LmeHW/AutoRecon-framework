#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, math
from pathlib import Path
import ants


def nearest_week(ga, wk_min=22, wk_max=35):
    return max(wk_min, min(wk_max, int(math.floor(ga + 0.5))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject_img", required=True)
    ap.add_argument("--ga", type=float, required=True)
    ap.add_argument("--wk_min", type=int, default=22)
    ap.add_argument("--wk_max", type=int, default=35)
    ap.add_argument("--ants_type", default="SyN", help='e.g. SyN (default) or Affine (faster)')
    ap.add_argument("--out_dir", type=Path, default=Path.cwd() / "outputs" / "ROI")
    ap.add_argument(
        "--atlas_dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data" / "FBA_Chinese_Atlas",
        help="Atlas root containing img/ and ROI/ (defaults to the copied project atlas).",
    )

    args = ap.parse_args()

    subject = Path(args.subject_img)
    atlas_dir = args.atlas_dir
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_roi = out_dir / Path(args.subject_img).name

    wk = nearest_week(args.ga, args.wk_min, args.wk_max)
    atlas_img = atlas_dir / f"img/{wk:02d}w.nii.gz"
    atlas_roi = atlas_dir / f"ROI/{wk:02d}w.nii.gz"

    for p, name in [(subject, "subject_img"), (atlas_img, "atlas_img"), (atlas_roi, "atlas_roi")]:
        if not p.exists():
            raise FileNotFoundError(f"{name} not found: {p}")

    fixed = ants.image_read(str(subject))      # subject space
    moving = ants.image_read(str(atlas_img))   # atlas space

    reg = ants.registration(fixed=fixed, moving=moving, type_of_transform=args.ants_type)

    roi = ants.image_read(str(atlas_roi))
    roi_warp = ants.apply_transforms(
        fixed=fixed, moving=roi,
        transformlist=reg["fwdtransforms"],
        interpolator="nearestNeighbor"
    )

    ants.image_write(roi_warp, str(out_roi))
    print(f"[OK] GA={args.ga:.2f} -> wk={wk}, wrote: {out_roi}")


if __name__ == "__main__":
    main()

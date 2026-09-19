#!/usr/bin/env python3
"""Strict acceptance verifier for all four reconstruction-backed pipelines."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import nibabel as nib
import numpy as np


BACKENDS = ("frost", "nesvor", "autosvrtk", "niftymic")
PIPELINE_STEPS = ("extraction", "reconstruction", "registration", "tissue", "roi", "surface")
SURFACE_ARTIFACTS = (
    "surf/lh.white", "surf/rh.white", "surf/lh.pial", "surf/rh.pial",
    "surf/lh.inflated", "surf/rh.inflated",
    "surf/lh.roi86.pial.mgh", "surf/rh.roi86.pial.mgh",
    "surf/lh.roi86.white.mgh", "surf/rh.roi86.white.mgh",
    "stats/roi86_thicknessproxy_cortexonly.stats", "stats/roi86_basic.stats",
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def valid_volume(path: Path, *, labels: bool = False) -> dict[str, object]:
    if not path.is_file():
        raise AssertionError(f"missing volume: {path}")
    image = nib.load(str(path))
    if len(image.shape) != 3 or any(size < 2 for size in image.shape):
        raise AssertionError(f"invalid 3D shape for {path}: {image.shape}")
    data = np.asarray(image.dataobj)
    if not np.isfinite(data).all() or not np.any(data != 0):
        raise AssertionError(f"empty or non-finite volume: {path}")
    if not np.isfinite(image.affine).all() or abs(np.linalg.det(image.affine[:3, :3])) < 1e-8:
        raise AssertionError(f"invalid affine: {path}")
    if labels and np.any(data < 0):
        raise AssertionError(f"negative labels: {path}")
    if labels and not np.allclose(data, np.rint(data)):
        raise AssertionError(f"non-integer labels: {path}")
    return {
        "shape": [int(value) for value in image.shape],
        "spacing": [float(value) for value in image.header.get_zooms()[:3]],
    }


def same_grid(first: Path, second: Path) -> None:
    a, b = nib.load(str(first)), nib.load(str(second))
    if a.shape != b.shape or not np.allclose(a.affine, b.affine, rtol=1e-5, atol=1e-4):
        raise AssertionError(f"grid mismatch: {first} vs {second}")


def verify_backend(root: Path, backend: str, subject: str) -> dict[str, object]:
    run = root / f"full_pipeline_{backend}"
    acceptance_path = run / "acceptance.json"
    if not acceptance_path.is_file():
        raise AssertionError(f"{backend}: missing per-backend strict acceptance.json")
    acceptance = load(acceptance_path)
    if (acceptance.get("status"), acceptance.get("backend"), acceptance.get("subject")) != (
        "completed", backend, subject
    ):
        raise AssertionError(f"{backend}: per-backend acceptance metadata does not match")
    overall_path = run / "pipeline_result.json"
    if not overall_path.is_file():
        raise AssertionError(f"{backend}: missing pipeline_result.json")
    overall = load(overall_path)
    if overall.get("status") != "completed" or overall.get("exit_code") != 0:
        raise AssertionError(f"{backend}: pipeline did not complete successfully: {overall}")
    if overall.get("reconstruction_backend") != backend:
        raise AssertionError(f"{backend}: pipeline marker names a different backend")
    if set(PIPELINE_STEPS) - set(overall.get("requested_steps", [])):
        raise AssertionError(f"{backend}: full six-step request was not executed")

    staging = run / "staging" / subject
    images = sorted(staging.glob("BTFE_*.nii.gz"))
    masks = [staging / "seg" / path.name for path in images]
    if not images or not all(path.is_file() for path in masks):
        raise AssertionError(f"{backend}: extraction stack/mask pairing is incomplete")
    for image, mask in zip(images, masks, strict=True):
        same_grid(image, mask)

    backend_result_path = run / "outputs" / "reconstruction" / backend / "result.json"
    backend_result = load(backend_result_path)
    if backend_result.get("status") != "completed" or not backend_result.get("input_fingerprint"):
        raise AssertionError(f"{backend}: reconstruction manifest is incomplete")
    native = Path(backend_result["output"])
    canonical = run / "outputs" / "recon" / f"{subject}.nii.gz"
    reconstruction_qc = valid_volume(native)
    valid_volume(canonical)
    if native.resolve() != canonical.resolve():
        raise AssertionError(f"{backend}: canonical output does not resolve to native backend output")

    registered = run / "outputs" / "registered_input" / f"{subject}.nii.gz"
    tissue = run / "outputs" / "Tissue" / f"{subject}.nii.gz"
    roi = run / "outputs" / "ROI" / f"{subject}.nii.gz"
    valid_volume(registered)
    valid_volume(tissue, labels=True)
    valid_volume(roi, labels=True)
    same_grid(registered, tissue)
    same_grid(registered, roi)
    registration_summary = run / "outputs" / "registration" / "summary.csv"
    if not registration_summary.is_file() or registration_summary.stat().st_size == 0:
        raise AssertionError(f"{backend}: registration summary is missing")

    surface_root = run / "outputs" / "surface_subjects" / subject
    surface_dir = surface_root / "surf"
    missing_surfaces = [
        name for name in SURFACE_ARTIFACTS
        if not (surface_root / name).is_file() or (surface_root / name).stat().st_size == 0
    ]
    if missing_surfaces:
        raise AssertionError(f"{backend}: missing surfaces: {', '.join(missing_surfaces)}")
    logs = run / "logs"
    missing_logs = [f"{index:02d}_{step}.log" for index, step in enumerate(PIPELINE_STEPS, 1)
                    if not (logs / f"{index:02d}_{step}.log").is_file()
                    or (logs / f"{index:02d}_{step}.log").stat().st_size == 0]
    if missing_logs:
        raise AssertionError(f"{backend}: missing step logs: {', '.join(missing_logs)}")
    return {
        "status": "passed",
        "strict_acceptance": str(acceptance_path.resolve()),
        "qc": {
            "reconstruction_warnings": acceptance.get("reconstruction_warnings", {}),
            "registration": acceptance.get("registration_qc", {}),
            "surface_warnings": acceptance.get("surface", {}).get("qc_warnings", {}),
        },
        "run_root": str(run.resolve()),
        "input_stacks": len(images),
        "reconstruction_qc": reconstruction_qc,
        "registration_summary": str(registration_summary.resolve()),
        "tissue": str(tissue.resolve()),
        "roi": str(roi.resolve()),
        "surface_dir": str(surface_dir.resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("backend_validation"))
    parser.add_argument("--subject", default="AnHuiJing")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.root / "four_backend_acceptance.json"
    results: dict[str, object] = {}
    failed = False
    for backend in BACKENDS:
        try:
            results[backend] = verify_backend(args.root, backend, args.subject)
            print(f"PASS {backend}")
        except Exception as exc:
            results[backend] = {"status": "failed", "error": str(exc)}
            failed = True
            print(f"FAIL {backend}: {exc}", file=sys.stderr)
    payload = {
        "schema_version": 1,
        "status": "failed" if failed else "completed",
        "subject": args.subject,
        "required_backends": list(BACKENDS),
        "required_steps": list(PIPELINE_STEPS),
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(f"Acceptance summary: {output}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

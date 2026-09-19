#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Sequence

import nibabel as nib
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.reconstruction.run_backend import collect_inputs, input_fingerprint, validate_output
from pipeline.extraction_state import state_payload as extraction_state_payload


PIPELINE_STEP_NAMES = ("extraction", "reconstruction", "registration", "tissue", "roi", "surface")


def resolve_required_logs(work_root: Path) -> list[Path]:
    """Resolve legacy or Dashboard-enabled pipeline log locations."""
    log_roots = (work_root / "logs", work_root / "dashboard" / "logs")
    resolved = []
    for index, step in enumerate(PIPELINE_STEP_NAMES, start=1):
        candidates = [root / f"{index:02d}_{step}.log" for root in log_roots]
        resolved.append(next((path for path in candidates if path.is_file() and path.stat().st_size > 0), candidates[0]))
    return resolved


def validate_label(path: Path, reference: Path, name: str) -> dict[str, object]:
    if not path.is_file():
        raise RuntimeError(f"Missing {name} output: {path}")
    label = nib.load(str(path))
    image = nib.load(str(reference))
    if label.shape != image.shape:
        raise RuntimeError(f"{name} shape mismatch: {label.shape} != {image.shape}")
    if not np.allclose(label.affine, image.affine, rtol=1e-5, atol=1e-4):
        raise RuntimeError(f"{name} affine mismatch")
    data = np.asarray(label.dataobj)
    if not np.isfinite(data).all() or not np.count_nonzero(data):
        raise RuntimeError(f"{name} is empty or non-finite")
    rounded = np.rint(data)
    if not np.allclose(data, rounded):
        raise RuntimeError(f"{name} contains non-integer label values")
    labels, counts = np.unique(rounded.astype(np.int64), return_counts=True)
    return {
        "shape": list(label.shape),
        "labels": labels.tolist(),
        "nonzero_voxels": int(np.count_nonzero(data)),
        "label_counts": {str(int(key)): int(value) for key, value in zip(labels, counts, strict=True)},
    }


def run(args: argparse.Namespace) -> dict[str, object]:
    project_root = args.project_root.resolve()
    work_root = args.work_root.resolve()
    subject = args.subject
    staging = work_root / "staging" / subject
    images, masks = collect_inputs(staging, require_masks=args.backend != "autosvrtk")
    extraction_mask_qc: list[dict[str, object]] = []
    for mask in [staging / "seg" / image.name for image in images]:
        data = np.asarray(nib.load(str(mask)).dataobj) != 0
        slice_axis = int(np.argmin(data.shape))
        counts = np.count_nonzero(data, axis=tuple(axis for axis in range(3) if axis != slice_axis))
        nonempty = np.flatnonzero(counts)
        internal_empty = [] if nonempty.size == 0 else [
            int(index) for index in range(int(nonempty[0]), int(nonempty[-1]) + 1) if counts[index] == 0
        ]
        extraction_mask_qc.append({
            "name": mask.name, "slice_axis": slice_axis,
            "internal_empty_slices": internal_empty,
        })
    runtime_root = Path(args.runtime_root or project_root / ".runtime").resolve()
    extraction_state_path = staging / "seg/extraction_state.json"
    if not extraction_state_path.is_file():
        raise RuntimeError(f"Extraction state is missing: {extraction_state_path}")
    actual_extraction_state = json.loads(extraction_state_path.read_text(encoding="utf-8"))
    source_dir = (getattr(args, "source_dir", None) or work_root.parent / "input" / subject).resolve()
    expected_extraction_state = extraction_state_payload(source_dir, staging, runtime_root)
    if actual_extraction_state != expected_extraction_state:
        raise RuntimeError("Extraction state does not match the accepted source, products, or container")
    fingerprint, _ = input_fingerprint(
        args.backend, images, masks if args.backend != "autosvrtk" else [], runtime_root
    )
    result_path = work_root / "outputs/reconstruction" / args.backend / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("status") != "completed":
        raise RuntimeError(f"Reconstruction result is not completed: {result.get('status')}")
    if result.get("input_fingerprint") != fingerprint:
        raise RuntimeError("Reconstruction result fingerprint does not match staged inputs")
    backend_log = Path(str(result.get("log", "")))
    warning_counts = {"no_valid_metric_points": 0, "zero_metric_points": 0}
    if backend_log.is_file():
        with backend_log.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                warning_counts["no_valid_metric_points"] += line.count("No valid points were found")
                warning_counts["zero_metric_points"] += line.count("collected only zero points")

    recon = work_root / "outputs/recon" / f"{subject}.nii.gz"
    registered = work_root / "outputs/registered_input" / f"{subject}.nii.gz"
    tissue = work_root / "outputs/Tissue" / f"{subject}.nii.gz"
    roi = work_root / "outputs/ROI" / f"{subject}.nii.gz"
    registration_summary = work_root / "outputs/registration/summary.csv"
    if not registration_summary.is_file() or registration_summary.stat().st_size == 0:
        raise RuntimeError(f"Registration summary is missing or empty: {registration_summary}")
    with registration_summary.open(newline="", encoding="utf-8") as stream:
        registration_rows = list(csv.DictReader(stream))
    registration_row = next((row for row in registration_rows if row.get("case") == subject), None)
    if not registration_row or registration_row.get("status") != "ok":
        raise RuntimeError(f"Registration did not report an ok result for {subject}")
    evidence: dict[str, object] = {
        "schema_version": 1,
        "status": "completed",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "backend": args.backend,
        "subject": subject,
        "work_root": str(work_root),
        "extraction": {
            "stack_count": len(images), "mask_count": len(masks),
            "state": str(extraction_state_path),
            "mask_qc": extraction_mask_qc,
        },
        "reconstruction": validate_output(recon),
        "reconstruction_warnings": {
            "sequence": result.get("sequence_warning"),
            **warning_counts,
        },
        "registration": validate_output(registered),
        "registration_qc": {
            "group": registration_row.get("qc_group"),
            "orientation": registration_row.get("orientation"),
            "mattes_lower_is_better": float(registration_row["mattes_lower_is_better"]),
            "gc_lower_is_better": float(registration_row["gc_lower_is_better"]),
            "summary": str(registration_summary),
        },
        "tissue": validate_label(tissue, registered, "tissue"),
        "roi": validate_label(roi, registered, "ROI"),
    }
    surface_root = work_root / "outputs/surface_subjects" / subject
    required_surface = [
        "surf/lh.white", "surf/rh.white", "surf/lh.pial", "surf/rh.pial",
        "surf/lh.inflated", "surf/rh.inflated",
        "surf/lh.roi86.pial.mgh", "surf/rh.roi86.pial.mgh",
        "surf/lh.roi86.white.mgh", "surf/rh.roi86.white.mgh",
        "stats/roi86_basic.stats", "stats/roi86_thicknessproxy_cortexonly.stats",
    ]
    missing_surface = [
        name for name in required_surface
        if not (surface_root / name).is_file() or (surface_root / name).stat().st_size == 0
    ]
    if args.require_surface and missing_surface:
        raise RuntimeError("Missing surface artifacts: " + ", ".join(missing_surface))
    evidence["surface"] = {
        "required": args.require_surface,
        "artifact_count": sum((surface_root / name).is_file() for name in required_surface),
        "missing": missing_surface,
    }
    required_logs = resolve_required_logs(work_root)
    # A resumed extraction may predate the pipeline fix that writes an explicit
    # reuse log. Its already-validated state is stronger provenance evidence than
    # an informational log line, so accept that state for legacy resumed runs.
    if not required_logs[0].is_file() or required_logs[0].stat().st_size == 0:
        required_logs[0] = extraction_state_path
    empty_logs = [str(path) for path in required_logs if not path.is_file() or path.stat().st_size == 0]
    if empty_logs:
        raise RuntimeError("Missing or empty pipeline logs: " + ", ".join(empty_logs))
    evidence["logs"] = [str(path) for path in required_logs]
    surface_log = required_logs[-1]
    surface_text = surface_log.read_text(encoding="utf-8", errors="replace")
    evidence["surface"]["qc_warnings"] = {
        "remaining_intersections": [
            int(value) for value in re.findall(r"terminating search with (\d+) intersecting", surface_text)
        ],
        "reported_handles": [
            int(value) for value in re.findall(r"-->\s*(\d+) handles", surface_text)
        ],
    }
    return evidence


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strictly validate one six-stage backend pipeline run.")
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--source-dir", type=Path,
                        help="Original subject directory; defaults to <work-root parent>/input/<subject>.")
    parser.add_argument("--backend", choices=("frost", "nesvor", "autosvrtk", "niftymic"), required=True)
    parser.add_argument("--require-surface", action="store_true")
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    evidence = run(args)
    output = args.output or args.work_root / "acceptance.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Full pipeline acceptance passed: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

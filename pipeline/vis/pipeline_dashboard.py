#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import shutil
import signal
import subprocess
import sys
from collections import deque
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, quote, unquote, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agentic.failure_catalog import classify_failure, incomplete_run_notice
from agentic.legacy_paths import resolve_relocated_run_file
from pipeline.vis.clinic_viewers import (
    SURFACE_MODELS,
    clinic_viewer_title,
    compose_mpr_viewer_html,
    compose_stack_viewer_html,
    compose_surface_viewer_html,
)


STEP_TITLES = [
    ("extraction", "2D extraction"),
    ("reconstruction", "3D reconstruction"),
    ("registration", "Rigid registration"),
    ("tissue", "Tissue segmentation"),
    ("roi", "ROI segmentation / warp"),
    ("surface", "Surface reconstruction"),
]

LABEL_PALETTE = (
    (62, 163, 154), (232, 132, 86), (87, 137, 199), (219, 91, 112),
    (204, 166, 72), (124, 105, 184), (82, 174, 116), (212, 111, 179),
    (92, 155, 196), (191, 121, 77), (111, 178, 170), (225, 151, 78),
    (115, 143, 193), (207, 108, 124), (183, 164, 82), (144, 119, 180),
    (100, 169, 121), (197, 126, 172), (104, 151, 181), (174, 132, 91),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_state(run_dir: Path) -> dict:
    state_path = run_dir / "run_state.json"
    if not state_path.exists():
        raise FileNotFoundError(f"Missing state file: {state_path}")
    return json.loads(state_path.read_text(encoding="utf-8"))


def save_state(run_dir: Path, state: dict) -> None:
    state["run"]["updated_at"] = utc_now()
    state_path = run_dir / "run_state.json"
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def get_step(state: dict, step_id: str) -> dict:
    for step in state["steps"]:
        if step["id"] == step_id:
            return step
    raise KeyError(f"Unknown step id: {step_id}")


def normalize_preview_path(run_dir: Path, preview: str | None) -> str | None:
    if not preview:
        return None
    preview_path = Path(preview)
    if preview_path.is_absolute():
        try:
            return preview_path.relative_to(run_dir).as_posix()
        except ValueError:
            return preview_path.as_posix()
    return preview_path.as_posix()


def parse_artifacts(values: Iterable[str]) -> list[dict]:
    artifacts: list[dict] = []
    for value in values:
        if "=" not in value:
            raise ValueError(f"Artifact must look like label=path, got: {value}")
        label, path = value.split("=", 1)
        artifacts.append({"label": label.strip(), "path": path.strip()})
    return artifacts


def append_step(run_dir: Path, step_id: str, title: str) -> None:
    state = load_state(run_dir)
    if any(step["id"] == step_id for step in state["steps"]):
        return
    state["steps"].append(
        {
            "id": step_id,
            "index": len(state["steps"]) + 1,
            "title": title,
            "status": "pending",
            "message": "",
            "started_at": None,
            "ended_at": None,
            "log_relpath": f"logs/{len(state['steps']) + 1:02d}_{step_id}.log",
            "preview_relpath": None,
            "artifacts": [],
        }
    )
    save_state(run_dir, state)


def refresh_run_status(state: dict) -> None:
    steps = state["steps"]
    statuses = {step["status"] for step in steps}
    running = next((step["id"] for step in steps if step["status"] == "running"), None)
    state["run"]["current_step"] = running
    if "failed" in statuses:
        state["run"]["status"] = "failed"
    elif running:
        state["run"]["status"] = "running"
        state["run"].pop("incomplete_notice", None)
    elif all(step["status"] in {"completed", "skipped"} for step in steps):
        state["run"]["status"] = "completed"
        state["run"].pop("incomplete_notice", None)
    elif any(step["status"] == "completed" for step in steps) and any(
        step["status"] in {"pending", "failed"} for step in steps
    ):
        state["run"]["status"] = "partial"
    else:
        state["run"]["status"] = "pending"


def init_run(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "previews").mkdir(parents=True, exist_ok=True)
    template_path = Path(__file__).with_name("pipeline_dashboard_template.html")
    target_index = run_dir / "index.html"
    if template_path.exists():
        shutil.copyfile(template_path, target_index)
    elif not target_index.exists():
        target_index.write_text("<h1>Missing dashboard template</h1>\n", encoding="utf-8")

    state = {
        "run": {
            "subject_name": args.subject_name,
            "subject_dir": args.subject_dir,
            "work_root": args.work_root,
            "dashboard_url": args.dashboard_url,
            "status": "pending",
            "message": args.message or "Pipeline initialized.",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "current_step": None,
        },
        "steps": [],
    }

    for index, (step_id, title) in enumerate(STEP_TITLES, start=1):
        state["steps"].append(
            {
                "id": step_id,
                "index": index,
                "title": title,
                "status": "pending",
                "message": "",
                "started_at": None,
                "ended_at": None,
                "log_relpath": f"logs/{index:02d}_{step_id}.log",
                "preview_relpath": None,
                "artifacts": [],
            }
        )

    save_state(run_dir, state)
    return 0


def update_step(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    state = load_state(run_dir)
    step = get_step(state, args.step_id)

    step["status"] = args.status
    if args.message is not None:
        step["message"] = args.message
        state["run"]["message"] = args.message
    if args.log_path is not None:
        step["log_relpath"] = os.path.relpath(args.log_path, run_dir)
    if args.preview is not None:
        step["preview_relpath"] = normalize_preview_path(run_dir, args.preview)
    if args.artifact:
        step["artifacts"] = parse_artifacts(args.artifact)

    if args.status == "running":
        step["started_at"] = step["started_at"] or utc_now()
        step["ended_at"] = None
    elif args.status in {"completed", "failed", "skipped"}:
        step["started_at"] = step["started_at"] or utc_now()
        step["ended_at"] = utc_now()

    refresh_run_status(state)
    save_state(run_dir, state)
    return 0


def finalize_run(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    state = load_state(run_dir)
    exit_code = getattr(args, "exit_code", None)
    if exit_code is None:
        match = re.search(r"exit code (\d+)", args.message or "")
        if match:
            exit_code = int(match.group(1))
    state["run"]["message"] = args.message
    if args.status:
        state["run"]["status"] = args.status
    else:
        refresh_run_status(state)
    if state["run"].get("status") in {"failed", "partial"} or exit_code not in (None, 0):
        failure = classify_failure(exit_code, args.message or "")
        state["run"]["failure"] = failure
        notice = incomplete_run_notice(state.get("steps") or [])
        if notice:
            state["run"]["incomplete_notice"] = notice
        state["run"]["message"] = " ".join(
            part for part in (
                failure["cause_zh"], failure["meaning_zh"], failure["next_action_zh"], notice,
            ) if part
        )
        if args.status == "completed" and notice:
            state["run"]["status"] = "partial"
    save_state(run_dir, state)
    return 0


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def first_file(paths: Iterable[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def existing_run_subject_name(existing_run_dir: Path, subject_name: str | None) -> str:
    if subject_name:
        return subject_name

    recon_dir = existing_run_dir / "outputs" / "recon"
    recon_files = sorted(recon_dir.glob("*.nii.gz"))
    if recon_files:
        name = recon_files[0].name
        return name[:-7] if name.endswith(".nii.gz") else recon_files[0].stem

    staging_dir = existing_run_dir / "staging"
    staging_subjects = sorted(path.name for path in staging_dir.iterdir() if path.is_dir()) if staging_dir.exists() else []
    if staging_subjects:
        return staging_subjects[0]

    return existing_run_dir.name


def import_existing_run(args: argparse.Namespace) -> int:
    existing_run_dir = Path(args.existing_run_dir).resolve()
    dashboard_dir = Path(args.dashboard_dir).resolve()

    if not existing_run_dir.is_dir():
        raise FileNotFoundError(f"Missing existing run directory: {existing_run_dir}")

    subject_name = existing_run_subject_name(existing_run_dir, args.subject_name)
    subject_dir = args.subject_dir or str(existing_run_dir / "staging" / subject_name)

    init_args = argparse.Namespace(
        run_dir=str(dashboard_dir),
        subject_name=subject_name,
        subject_dir=subject_dir,
        work_root=str(existing_run_dir),
        dashboard_url=args.dashboard_url or "",
        message=f"Imported from existing run: {existing_run_dir}",
    )
    init_run(init_args)

    log_dir = dashboard_dir / "logs"
    preview_dir = dashboard_dir / "previews"

    staging_subject_dir = existing_run_dir / "staging" / subject_name
    seg_dir = staging_subject_dir / "seg"
    recon_file = existing_run_dir / "outputs" / "recon" / f"{subject_name}.nii.gz"
    tissue_file = existing_run_dir / "outputs" / "Tissue" / f"{subject_name}.nii.gz"
    roi_file = existing_run_dir / "outputs" / "ROI" / f"{subject_name}.nii.gz"
    registration_dir = existing_run_dir / "outputs" / "registration"
    registered_file = first_file(
        [
            registration_dir / "best" / f"{subject_name}_best_Warped.nii.gz",
            registration_dir / "acceptable_cases" / "best" / f"{subject_name}_best_Warped.nii.gz",
            registration_dir / "suspicious_cases" / "best" / f"{subject_name}_best_Warped.nii.gz",
        ]
    )
    sample_input = first_file(sorted(staging_subject_dir.glob("BTFE_*.nii.gz"))) if staging_subject_dir.exists() else None
    sample_seg = seg_dir / sample_input.name if sample_input else None
    surface_dir = existing_run_dir / "outputs" / "surface_subjects" / subject_name
    surface_surf_dir = surface_dir / "surf"
    surface_stats_dir = surface_dir / "stats"
    surface_exists = any(
        (surface_surf_dir / relpath).exists()
        for relpath in ("lh.white", "rh.white", "lh.pial", "rh.pial")
    )

    steps = [
        {
            "id": "extraction",
            "status": "completed" if sample_input and sample_seg and sample_seg.exists() else "skipped",
            "message": "Imported existing extraction output." if sample_input and sample_seg and sample_seg.exists() else "No staging extraction output found.",
            "preview_image": sample_input,
            "preview_overlay": sample_seg if sample_seg and sample_seg.exists() else None,
            "preview_mode": "mask",
            "artifacts": [
                ("Staging subject", staging_subject_dir),
                ("Extraction seg", seg_dir),
            ],
        },
        {
            "id": "reconstruction",
            "status": "completed" if recon_file.exists() else "skipped",
            "message": "Imported existing reconstruction result." if recon_file.exists() else "No reconstruction output found.",
            "preview_image": recon_file if recon_file.exists() else None,
            "preview_overlay": None,
            "preview_mode": "label",
            "artifacts": [("Recon output", recon_file)],
        },
        {
            "id": "registration",
            "status": "completed" if registered_file else "skipped",
            "message": "Imported existing registration result." if registered_file else "No registered volume found.",
            "preview_image": registered_file,
            "preview_overlay": None,
            "preview_mode": "label",
            "artifacts": [
                ("Registration root", registration_dir),
                ("Registered image", registered_file or registration_dir),
            ],
        },
        {
            "id": "tissue",
            "status": "completed" if recon_file.exists() and tissue_file.exists() else "skipped",
            "message": "Imported existing tissue segmentation." if tissue_file.exists() else "No tissue output found.",
            "preview_image": recon_file if recon_file.exists() else tissue_file,
            "preview_overlay": tissue_file if tissue_file.exists() else None,
            "preview_mode": "label",
            "artifacts": [("Tissue output", tissue_file)],
        },
        {
            "id": "roi",
            "status": "completed" if recon_file.exists() and roi_file.exists() else "skipped",
            "message": "Imported existing ROI output." if roi_file.exists() else "No ROI output found.",
            "preview_image": recon_file if recon_file.exists() else roi_file,
            "preview_overlay": roi_file if roi_file.exists() else None,
            "preview_mode": "label",
            "artifacts": [
                ("ROI output", roi_file),
                ("Surface subject", surface_dir),
            ],
        },
        {
            "id": "surface",
            "status": "completed" if surface_exists else "skipped",
            "message": "Imported existing surface reconstruction." if surface_exists else "No surface reconstruction output found.",
            "preview_image": surface_dir if surface_exists else None,
            "preview_overlay": None,
            "preview_mode": "surface",
            "artifacts": [
                ("Surface subject", surface_dir),
                ("Surface surf", surface_surf_dir),
                ("Surface stats", surface_stats_dir),
                ("Basic stats", surface_stats_dir / "roi86_basic.stats"),
                ("Thickness stats", surface_stats_dir / "roi86_thicknessproxy_cortexonly.stats"),
            ],
        },
    ]

    for index, step in enumerate(steps, start=1):
        step_id = step["id"]
        log_path = log_dir / f"{index:02d}_{step_id}.log"
        artifacts_text = "\n".join(
            f"- {label}: {path}" for label, path in step["artifacts"] if path and Path(path).exists()
        )
        write_text(
            log_path,
            (
                f"Imported existing run\n"
                f"step={step_id}\n"
                f"status={step['status']}\n"
                f"source_run={existing_run_dir}\n"
                f"{artifacts_text}\n"
            ),
        )

        preview_path = None
        generated_artifacts: list[tuple[str, Path]] = []
        if step["status"] == "completed" and step["preview_image"] and Path(step["preview_image"]).exists():
            preview_path = preview_dir / f"{index:02d}_{step_id}.png"
            if step["preview_mode"] == "surface":
                render_args = argparse.Namespace(
                    surface_subject_dir=str(step["preview_image"]),
                    output=str(preview_path),
                    title=clinic_viewer_title(subject_name, step_id),
                )
                render_surface_preview(render_args)
                interactive_path = preview_dir / f"{index:02d}_{step_id}_interactive.html"
                interactive_args = argparse.Namespace(
                    surface_subject_dir=str(step["preview_image"]),
                    output=str(interactive_path),
                    title=clinic_viewer_title(subject_name, step_id),
                )
                render_surface_interactive_html(interactive_args)
                if interactive_path.exists():
                    generated_artifacts.append(("表面重建交互查看", interactive_path))
            else:
                render_args = argparse.Namespace(
                    image=str(step["preview_image"]),
                    output=str(preview_path),
                    overlay=str(step["preview_overlay"]) if step["preview_overlay"] else None,
                    title=f"{subject_name}: {step_id}",
                    overlay_mode=step["preview_mode"],
                )
                render_preview(render_args)
                if step_id == "extraction":
                    interactive_path = preview_dir / f"{index:02d}_{step_id}_interactive.html"
                    stack_args = argparse.Namespace(
                        image_dir=str(staging_subject_dir),
                        overlay_dir=str(seg_dir),
                        pattern="BTFE_*.nii.gz",
                        output=str(interactive_path),
                        title=clinic_viewer_title(subject_name, "extraction"),
                    )
                    render_stack_viewer(stack_args)
                    if interactive_path.exists():
                        generated_artifacts.append(("脑提取交互查看", interactive_path))
                elif step_id == "reconstruction":
                    interactive_path = preview_dir / f"{index:02d}_{step_id}_interactive.html"
                    mpr_args = argparse.Namespace(
                        image=str(step["preview_image"]),
                        overlay=None,
                        overlay_label="",
                        output=str(interactive_path),
                        title=clinic_viewer_title(subject_name, "reconstruction"),
                    )
                    render_mpr_viewer(mpr_args)
                    if interactive_path.exists():
                        generated_artifacts.append(("三维重建交互查看", interactive_path))
                elif step_id == "registration":
                    interactive_path = preview_dir / f"{index:02d}_{step_id}_interactive.html"
                    mpr_args = argparse.Namespace(
                        image=str(step["preview_image"]),
                        overlay=None,
                        overlay_label="",
                        output=str(interactive_path),
                        title=clinic_viewer_title(subject_name, "registration"),
                    )
                    render_mpr_viewer(mpr_args)
                    if interactive_path.exists():
                        generated_artifacts.append(("图像配准交互查看", interactive_path))
                elif step_id == "tissue":
                    interactive_path = preview_dir / f"{index:02d}_{step_id}_interactive.html"
                    mpr_args = argparse.Namespace(
                        image=str(step["preview_image"]),
                        overlay=str(step["preview_overlay"]) if step["preview_overlay"] else None,
                        overlay_label="组织标签",
                        output=str(interactive_path),
                        title=clinic_viewer_title(subject_name, "tissue"),
                    )
                    render_mpr_viewer(mpr_args)
                    if interactive_path.exists():
                        generated_artifacts.append(("组织分割交互查看", interactive_path))
                elif step_id == "roi":
                    interactive_path = preview_dir / f"{index:02d}_{step_id}_interactive.html"
                    mpr_args = argparse.Namespace(
                        image=str(step["preview_image"]),
                        overlay=str(step["preview_overlay"]) if step["preview_overlay"] else None,
                        overlay_label="脑区标签",
                        output=str(interactive_path),
                        title=clinic_viewer_title(subject_name, "roi"),
                    )
                    render_mpr_viewer(mpr_args)
                    if interactive_path.exists():
                        generated_artifacts.append(("脑区分割交互查看", interactive_path))

        update_args = argparse.Namespace(
            run_dir=str(dashboard_dir),
            step_id=step_id,
            status=step["status"],
            message=step["message"],
            log_path=str(log_path),
            preview=str(preview_path) if preview_path and preview_path.exists() else None,
            artifact=[
                *[f"{label}={path}" for label, path in step["artifacts"] if path and Path(path).exists()],
                *[f"{label}={path}" for label, path in generated_artifacts if path.exists()],
            ],
        )
        update_step(update_args)

    state = load_state(dashboard_dir)
    refresh_run_status(state)
    state["run"]["message"] = f"Imported existing run from {existing_run_dir}"
    save_state(dashboard_dir, state)
    return 0


def render_preview(args: argparse.Namespace) -> int:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        import SimpleITK as sitk
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"Preview rendering dependencies are unavailable: {exc}", file=sys.stderr)
        return 2

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"Missing image: {image_path}", file=sys.stderr)
        return 2

    image = sitk.ReadImage(str(image_path))
    image_arr = sitk.GetArrayFromImage(image).astype("float32")

    overlay_arr = None
    if args.overlay:
        overlay_path = Path(args.overlay)
        if overlay_path.exists():
            overlay_arr = sitk.GetArrayFromImage(sitk.ReadImage(str(overlay_path))).astype("int32")

    if image_arr.ndim == 4:
        image_arr = image_arr[0]
    if overlay_arr is not None and overlay_arr.ndim == 4:
        overlay_arr = overlay_arr[0]
    if image_arr.ndim != 3:
        print(f"Expected 3D volume, got shape {image_arr.shape} from {image_path}", file=sys.stderr)
        return 2

    center = pick_center(image_arr, overlay_arr)

    title = args.title or image_path.name
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2), facecolor="#fbf7ef")
    planes = [
        ("Sagittal", np.flipud(image_arr[:, :, center[2]].T)),
        ("Coronal", np.flipud(image_arr[:, center[1], :].T)),
        ("Axial", np.flipud(image_arr[center[0], :, :].T)),
    ]

    overlay_planes = None
    if overlay_arr is not None:
        overlay_planes = [
            np.flipud(overlay_arr[:, :, center[2]].T),
            np.flipud(overlay_arr[:, center[1], :].T),
            np.flipud(overlay_arr[center[0], :, :].T),
        ]

    for idx, ax in enumerate(axes):
        plane_name, plane_img_raw = planes[idx]
        overlay_plane = overlay_planes[idx] if overlay_planes is not None else None
        plane_img, overlay_plane = crop_plane_pair(plane_img_raw, overlay_plane)
        plane_img = normalize_plane(plane_img)
        render_rgb = gray_to_rgb(plane_img)
        if overlay_plane is not None:
            overlay_rgb, overlay_alpha = make_overlay(overlay_plane, args.overlay_mode)
            render_rgb = composite_overlay(render_rgb, overlay_rgb, overlay_alpha)
        render_rgb = render_rgb.clip(0.0, 1.0)
        ax.imshow(render_rgb, interpolation="nearest", vmin=0.0, vmax=1.0)
        ax.set_title(plane_name, fontsize=11, color="#4b4338")
        ax.axis("off")

    fig.suptitle(title, fontsize=14, color="#201c17")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return 0


def pick_center(image_arr, overlay_arr):
    import numpy as np

    if overlay_arr is not None:
        coords = np.argwhere(overlay_arr > 0)
        if coords.size:
            return tuple(int(v) for v in coords.mean(axis=0))
    coords = np.argwhere(image_arr > 0)
    if coords.size:
        return tuple(int(v) for v in coords.mean(axis=0))
    return tuple(int(s // 2) for s in image_arr.shape)


def normalize_image(image_arr):
    import numpy as np

    mask = np.isfinite(image_arr)
    values = image_arr[mask]
    if values.size == 0:
        return np.zeros_like(image_arr, dtype="float32")
    nonzero = values[np.abs(values) > 1e-6]
    sample = nonzero if nonzero.size else values
    lo, hi = np.percentile(sample, [1, 99])
    if hi <= lo:
        hi = lo + 1.0
    clipped = np.clip(image_arr, lo, hi)
    return ((clipped - lo) / (hi - lo)).astype("float32")


def normalize_plane(plane_arr):
    import numpy as np

    values = plane_arr[np.isfinite(plane_arr)]
    if values.size == 0:
        return np.zeros_like(plane_arr, dtype="float32")
    nonzero = values[np.abs(values) > 1e-6]
    sample = nonzero if nonzero.size else values
    lo, hi = np.percentile(sample, [1, 99])
    if hi <= lo:
        hi = lo + 1.0
    clipped = np.clip(plane_arr, lo, hi)
    return ((clipped - lo) / (hi - lo)).astype("float32")


def gray_to_rgb(plane_img):
    import numpy as np

    rgb = np.repeat(plane_img[..., None], 3, axis=2)
    return rgb.astype("float32")


def composite_overlay(base_rgb, overlay_rgb, overlay_alpha):
    import numpy as np

    alpha = overlay_alpha[..., None].astype("float32")
    blended = base_rgb * (1.0 - alpha) + overlay_rgb * alpha
    return np.clip(blended, 0.0, 1.0).astype("float32")


def crop_plane_pair(plane_img, overlay_plane=None, pad=12):
    import numpy as np

    if overlay_plane is not None and np.any(overlay_plane > 0):
        coords = np.argwhere(overlay_plane > 0)
    else:
        coords = np.argwhere(np.abs(plane_img) > 1e-6)

    if coords.size == 0:
        return plane_img, overlay_plane

    r0, c0 = coords.min(axis=0)
    r1, c1 = coords.max(axis=0)
    r0 = max(0, int(r0) - pad)
    c0 = max(0, int(c0) - pad)
    r1 = min(plane_img.shape[0], int(r1) + pad + 1)
    c1 = min(plane_img.shape[1], int(c1) + pad + 1)

    cropped_img = plane_img[r0:r1, c0:c1]
    cropped_overlay = overlay_plane[r0:r1, c0:c1] if overlay_plane is not None else None
    return cropped_img, cropped_overlay


def make_overlay(overlay_plane, mode):
    import matplotlib.pyplot as plt
    import numpy as np

    overlay_plane = overlay_plane.astype("int32")
    rgb = np.zeros((*overlay_plane.shape, 3), dtype="float32")
    alpha = np.zeros(overlay_plane.shape, dtype="float32")
    labels = [int(v) for v in np.unique(overlay_plane) if v > 0]
    if not labels:
        return rgb, alpha

    cmap = plt.get_cmap("turbo") if mode == "heatmap" else None
    max_label = max(labels)
    for label in labels:
        mask = overlay_plane == label
        if mode == "contour":
            mask = contour_mask(mask)
        if mode == "heatmap":
            color = cmap(label / max_label)[:3]
        elif mode == "mask":
            color = np.asarray((105, 218, 119), dtype="float32") / 255.0
        else:
            color = np.asarray(LABEL_PALETTE[(label - 1) % len(LABEL_PALETTE)], dtype="float32") / 255.0
        rgb[mask] = color
        if mode == "mask":
            alpha[mask] = 0.6
        elif mode == "contour":
            alpha[mask] = 0.95
        else:
            alpha[mask] = 0.28
    return rgb, alpha


def contour_mask(mask_2d):
    import numpy as np

    padded = np.pad(mask_2d.astype(bool), 1, mode="constant", constant_values=False)
    center = padded[1:-1, 1:-1]
    neighbors = [
        padded[:-2, 1:-1],
        padded[2:, 1:-1],
        padded[1:-1, :-2],
        padded[1:-1, 2:],
    ]
    interior = center.copy()
    for neighbor in neighbors:
        interior &= neighbor
    boundary = center & ~interior
    return boundary


def api_file_url(path: Path) -> str:
    return f"/api/file?path={quote(str(path.resolve()), safe='')}"


def prepare_viewer_assets(output_path: Path) -> Path:
    assets_dir = output_path.with_name(f"{output_path.stem}_assets")
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return assets_dir


def save_gray_png(path: Path, plane, alpha_mask=None) -> None:
    import numpy as np
    from PIL import Image

    gray = plane.astype("uint8")
    if alpha_mask is None:
        Image.fromarray(gray, mode="L").save(path, compress_level=4)
        return
    rgba = np.empty((*gray.shape, 4), dtype="uint8")
    rgba[..., :3] = gray[..., None]
    rgba[..., 3] = np.where(alpha_mask, 255, 0).astype("uint8")
    Image.fromarray(rgba, mode="RGBA").save(path, compress_level=4)


def save_mask_png(path: Path, mask) -> None:
    import numpy as np
    from PIL import Image

    rgba = np.zeros((*mask.shape, 4), dtype="uint8")
    rgba[mask > 0] = (105, 218, 119, 255)
    Image.fromarray(rgba, mode="RGBA").save(path, compress_level=4)


def save_label_png(path: Path, labels) -> None:
    import numpy as np
    from PIL import Image

    palette = np.asarray(LABEL_PALETTE, dtype="uint8")
    rgba = np.zeros((*labels.shape, 4), dtype="uint8")
    for label in np.unique(labels):
        label = int(label)
        if label <= 0:
            continue
        rgba[labels == label, :3] = palette[(label - 1) % len(palette)]
        rgba[labels == label, 3] = 255
    Image.fromarray(rgba, mode="RGBA").save(path, compress_level=4)


def stack_crop_slices(image_arr, overlay_arr=None, pad=12):
    import numpy as np

    support = overlay_arr > 0 if overlay_arr is not None and np.any(overlay_arr > 0) else np.abs(image_arr) > 1e-6
    projection = np.any(support, axis=0)
    coords = np.argwhere(projection)
    if not coords.size:
        return slice(0, image_arr.shape[1]), slice(0, image_arr.shape[2])
    y0, x0 = coords.min(axis=0)
    y1, x1 = coords.max(axis=0) + 1
    return (
        slice(max(0, int(y0) - pad), min(image_arr.shape[1], int(y1) + pad)),
        slice(max(0, int(x0) - pad), min(image_arr.shape[2], int(x1) + pad)),
    )


def render_stack_viewer(args: argparse.Namespace) -> int:
    try:
        import numpy as np
        import SimpleITK as sitk
        from PIL import Image  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"Stack viewer dependencies are unavailable: {exc}", file=sys.stderr)
        return 2

    image_dir = Path(args.image_dir).resolve()
    overlay_dir = Path(args.overlay_dir).resolve() if args.overlay_dir else None
    image_paths = sorted(image_dir.glob(args.pattern))
    if not image_paths:
        print(f"No files matched {args.pattern!r} under {image_dir}", file=sys.stderr)
        return 2

    output_path = Path(args.output).resolve()
    assets_dir = prepare_viewer_assets(output_path)
    sequences = []

    for sequence_index, image_path in enumerate(image_paths):
        image_arr = sitk.GetArrayFromImage(sitk.ReadImage(str(image_path))).astype("float32")
        if image_arr.ndim == 4:
            image_arr = image_arr[0]
        if image_arr.ndim != 3:
            continue

        overlay_arr = None
        if overlay_dir:
            overlay_path = overlay_dir / image_path.name
            if overlay_path.exists():
                candidate = sitk.GetArrayFromImage(sitk.ReadImage(str(overlay_path)))
                if candidate.ndim == 4:
                    candidate = candidate[0]
                if candidate.shape == image_arr.shape:
                    overlay_arr = candidate

        normalized = np.round(normalize_image(image_arr) * 255.0).astype("uint8")
        y_slice, x_slice = stack_crop_slices(image_arr, overlay_arr)
        sequence_dir = assets_dir / f"sequence_{sequence_index:02d}"
        sequence_dir.mkdir(parents=True, exist_ok=True)
        raw_urls = []
        mask_urls = []

        for slice_index in range(image_arr.shape[0]):
            raw_path = sequence_dir / f"raw_{slice_index:04d}.png"
            save_gray_png(
                raw_path,
                normalized[slice_index, y_slice, x_slice],
                np.abs(image_arr[slice_index, y_slice, x_slice]) > 1e-6,
            )
            raw_urls.append(api_file_url(raw_path))

            if overlay_arr is not None:
                mask_path = sequence_dir / f"mask_{slice_index:04d}.png"
                save_mask_png(mask_path, overlay_arr[slice_index, y_slice, x_slice])
                mask_urls.append(api_file_url(mask_path))
            else:
                mask_urls.append("")

        sequences.append(
            {
                "name": image_path.name,
                "count": int(image_arr.shape[0]),
                "raw": raw_urls,
                "mask": mask_urls,
                "has_mask": overlay_arr is not None,
            }
        )

    if not sequences:
        print(f"No readable 3D stacks found under {image_dir}", file=sys.stderr)
        return 2

    sequences_json = json.dumps(sequences, ensure_ascii=False, separators=(",", ":"))
    html = compose_stack_viewer_html(args.title or image_dir.name, sequences_json, output_path)
    output_path.write_text(html, encoding="utf-8")
    return 0


def volume_crop_slices(image_arr, pad=8):
    import numpy as np

    coords = np.argwhere(np.abs(image_arr) > 1e-6)
    if not coords.size:
        return tuple(slice(0, size) for size in image_arr.shape)
    lower = np.maximum(coords.min(axis=0) - pad, 0)
    upper = np.minimum(coords.max(axis=0) + pad + 1, image_arr.shape)
    return tuple(slice(int(lower[axis]), int(upper[axis])) for axis in range(3))


def render_mpr_viewer(args: argparse.Namespace) -> int:
    try:
        import numpy as np
        import SimpleITK as sitk
        from PIL import Image  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"MPR viewer dependencies are unavailable: {exc}", file=sys.stderr)
        return 2

    image_path = Path(args.image).resolve()
    if not image_path.exists():
        print(f"Missing image: {image_path}", file=sys.stderr)
        return 2

    image = sitk.ReadImage(str(image_path))
    image_arr = sitk.GetArrayFromImage(image).astype("float32")
    if image_arr.ndim == 4:
        image_arr = image_arr[0]
    if image_arr.ndim != 3:
        print(f"Expected 3D volume, got shape {image_arr.shape} from {image_path}", file=sys.stderr)
        return 2

    crop_slices = volume_crop_slices(image_arr)
    volume = image_arr[crop_slices]
    overlay = None
    if args.overlay:
        overlay_path = Path(args.overlay).resolve()
        if overlay_path.exists():
            overlay_arr = sitk.GetArrayFromImage(sitk.ReadImage(str(overlay_path)))
            if overlay_arr.ndim == 4:
                overlay_arr = overlay_arr[0]
            if overlay_arr.shape == image_arr.shape:
                overlay = overlay_arr[crop_slices].astype("int32")
            else:
                print(
                    f"Ignoring overlay with mismatched shape {overlay_arr.shape}; expected {image_arr.shape}: {overlay_path}",
                    file=sys.stderr,
                )
    normalized = np.round(normalize_image(volume) * 255.0).astype("uint8")
    support = np.abs(volume) > 1e-6
    output_path = Path(args.output).resolve()
    assets_dir = prepare_viewer_assets(output_path)
    z_size, y_size, x_size = normalized.shape
    planes = {}

    plane_specs = {
        "sagittal": (
            x_size,
            lambda index: np.flipud(normalized[:, :, index].T),
            lambda index: np.flipud(support[:, :, index].T),
            (lambda index: np.flipud(overlay[:, :, index].T)) if overlay is not None else None,
        ),
        "coronal": (
            y_size,
            lambda index: np.flipud(normalized[:, index, :].T),
            lambda index: np.flipud(support[:, index, :].T),
            (lambda index: np.flipud(overlay[:, index, :].T)) if overlay is not None else None,
        ),
        "axial": (
            z_size,
            lambda index: np.flipud(normalized[index, :, :]),
            lambda index: np.flipud(support[index, :, :]),
            (lambda index: np.flipud(overlay[index, :, :])) if overlay is not None else None,
        ),
    }
    for plane_name, (count, plane_getter, support_getter, overlay_getter) in plane_specs.items():
        plane_dir = assets_dir / plane_name
        plane_dir.mkdir(parents=True, exist_ok=True)
        urls = []
        overlay_urls = []
        width = height = 0
        for index in range(count):
            plane = plane_getter(index)
            height, width = plane.shape
            plane_path = plane_dir / f"{index:04d}.png"
            save_gray_png(plane_path, plane, support_getter(index))
            urls.append(api_file_url(plane_path))
            if overlay_getter is not None:
                overlay_plane_path = plane_dir / f"overlay_{index:04d}.png"
                save_label_png(overlay_plane_path, overlay_getter(index))
                overlay_urls.append(api_file_url(overlay_plane_path))
        planes[plane_name] = {
            "images": urls,
            "overlays": overlay_urls,
            "width": width,
            "height": height,
        }

    manifest = {
        "dims": {"x": x_size, "y": y_size, "z": z_size},
        "spacing": list(image.GetSpacing()),
        "has_overlay": overlay is not None,
        "overlay_label": args.overlay_label or "标签",
        "planes": planes,
    }
    manifest_json = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
    html = compose_mpr_viewer_html(args.title or image_path.name, manifest_json, output_path)
    output_path.write_text(html, encoding="utf-8")
    return 0



def render_surface_preview(args: argparse.Namespace) -> int:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import nibabel as nib
        import numpy as np
        from nibabel.freesurfer import read_geometry
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"Surface preview dependencies are unavailable: {exc}", file=sys.stderr)
        return 2

    surface_subject_dir = Path(args.surface_subject_dir)
    surf_dir = surface_subject_dir / "surf"
    if not surf_dir.exists():
        print(f"Missing surf directory: {surf_dir}", file=sys.stderr)
        return 2

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(12.5, 8.8), facecolor="#fbf7ef")

    specs = [
        ("lh", "white", "LH white", 10, 180),
        ("rh", "white", "RH white", 10, 0),
        ("lh", "pial", "LH pial", 18, 180),
        ("rh", "pial", "RH pial", 18, 0),
    ]

    for panel_index, (hemi, surface_name, panel_title, elev, azim) in enumerate(specs, start=1):
        ax = fig.add_subplot(2, 2, panel_index, projection="3d")
        surf_path = surf_dir / f"{hemi}.{surface_name}"
        roi_path = surf_dir / f"{hemi}.roi86.{surface_name}.mgh"

        if not surf_path.exists():
            ax.text2D(0.5, 0.5, f"Missing {surf_path.name}", transform=ax.transAxes, ha="center", va="center")
            ax.set_axis_off()
            continue

        coords, faces = read_geometry(str(surf_path))
        mesh_coords, mesh_faces, mesh_vertex_ids = decimate_surface(coords, faces, max_faces=40000)
        mesh_normals = compute_vertex_normals(mesh_coords, mesh_faces)
        ax.plot_trisurf(
            mesh_coords[:, 0],
            mesh_coords[:, 1],
            mesh_coords[:, 2],
            triangles=mesh_faces,
            color="#d7d0c5",
            linewidth=0.0,
            antialiased=False,
            shade=True,
            alpha=1.0,
        )

        if roi_path.exists():
            roi_values = nib.load(str(roi_path)).get_fdata().reshape(-1).astype("int32")
            mesh_labels = roi_values[mesh_vertex_ids]
            face_labels = face_majority_labels(mesh_labels, mesh_faces)
            colored_face_ids = np.flatnonzero(face_labels > 0)
            if colored_face_ids.size:
                overlay_offset = float(np.max(np.ptp(mesh_coords, axis=0)) * 0.0015)
                overlay_coords = mesh_coords + mesh_normals * overlay_offset
                overlay = ax.plot_trisurf(
                    overlay_coords[:, 0],
                    overlay_coords[:, 1],
                    overlay_coords[:, 2],
                    triangles=mesh_faces[colored_face_ids],
                    color="#ffffff",
                    linewidth=0.0,
                    antialiased=False,
                    shade=False,
                    alpha=1.0,
                )
                overlay.set_facecolors(roi_label_rgba(face_labels[colored_face_ids], alpha=0.82))

        set_equal_aspect(ax, mesh_coords)
        ax.view_init(elev=elev, azim=azim)
        ax.set_axis_off()
        ax.set_title(panel_title, fontsize=11, color="#4b4338", pad=2)

    fig.suptitle(args.title or surface_subject_dir.name, fontsize=14, color="#201c17")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return 0


def render_surface_interactive_html(args: argparse.Namespace) -> int:
    try:
        import nibabel as nib
        import numpy as np
        from nibabel.freesurfer import read_geometry
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"Surface HTML dependencies are unavailable: {exc}", file=sys.stderr)
        return 2

    surface_subject_dir = Path(args.surface_subject_dir)
    surf_dir = surface_subject_dir / "surf"
    if not surf_dir.exists():
        print(f"Missing surf directory: {surf_dir}", file=sys.stderr)
        return 2

    models = []
    for hemi, surface_name, label in SURFACE_MODELS:
        surf_path = surf_dir / f"{hemi}.{surface_name}"
        roi_path = surf_dir / f"{hemi}.roi86.{surface_name}.mgh"
        if not surf_path.exists():
            continue

        coords, faces = read_geometry(str(surf_path))
        mesh_coords = normalize_surface_coords(coords)
        mesh_faces = faces
        mesh_normals = compute_vertex_normals(mesh_coords, mesh_faces)

        roi_vertex_colors = np.zeros((mesh_coords.shape[0], 3), dtype="float32")
        roi_vertex_mask = np.zeros(mesh_coords.shape[0], dtype="float32")
        if roi_path.exists():
            roi_values = nib.load(str(roi_path)).get_fdata().reshape(-1).astype("int32")
            colored_ids = np.flatnonzero(roi_values > 0)
            if colored_ids.size:
                roi_vertex_colors[colored_ids] = roi_label_colors(roi_values[colored_ids])
                roi_vertex_mask[colored_ids] = 1.0

        vertices = np.ascontiguousarray(mesh_coords, dtype="<f4").reshape(-1)
        normals = np.ascontiguousarray(mesh_normals, dtype="<f4").reshape(-1)
        face_indices = np.ascontiguousarray(mesh_faces, dtype="<u4").reshape(-1)
        vertex_colors = np.ascontiguousarray(roi_vertex_colors, dtype="<f4").reshape(-1)
        vertex_mask = np.ascontiguousarray(roi_vertex_mask, dtype="<f4")

        models.append(
            {
                "id": f"{hemi}_{surface_name}",
                "label": label,
                "vertices": base64.b64encode(vertices.tobytes()).decode("ascii"),
                "normals": base64.b64encode(normals.tobytes()).decode("ascii"),
                "faces": base64.b64encode(face_indices.tobytes()).decode("ascii"),
                "roi_vertex_colors": base64.b64encode(vertex_colors.tobytes()).decode("ascii"),
                "roi_vertex_mask": base64.b64encode(vertex_mask.tobytes()).decode("ascii"),
                "index_count": int(face_indices.size),
            }
        )

    if not models:
        print(f"No readable surfaces found under: {surf_dir}", file=sys.stderr)
        return 2

    models_json = json.dumps(models, ensure_ascii=False, separators=(",", ":"))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    html = compose_surface_viewer_html(args.title or surface_subject_dir.name, models_json, output_path)
    output_path.write_text(html, encoding="utf-8")
    return 0


def decimate_surface(coords, faces, max_faces=40000):
    import numpy as np

    if len(faces) > max_faces:
        stride = max(1, len(faces) // max_faces)
        faces = faces[::stride]

    vertex_ids = np.unique(faces.reshape(-1))
    remap = np.full(len(coords), -1, dtype=np.int32)
    remap[vertex_ids] = np.arange(len(vertex_ids), dtype=np.int32)
    mesh_coords = coords[vertex_ids]
    mesh_faces = remap[faces]
    return mesh_coords, mesh_faces, vertex_ids


def sample_indices(indices, max_points=22000):
    import numpy as np

    if len(indices) <= max_points:
        return indices
    picked = np.linspace(0, len(indices) - 1, max_points, dtype=np.int64)
    return indices[picked]


def normalize_surface_coords(coords):
    import numpy as np

    coords = np.asarray(coords, dtype="float32")
    mins = coords.min(axis=0)
    maxs = coords.max(axis=0)
    center = (mins + maxs) / 2.0
    radius = float(np.max(maxs - mins) / 2.0)
    if radius <= 0:
        radius = 1.0
    return (coords - center) / radius


def compute_vertex_normals(coords, faces):
    import numpy as np

    normals = np.zeros_like(coords, dtype="float32")
    v0 = coords[faces[:, 0]]
    v1 = coords[faces[:, 1]]
    v2 = coords[faces[:, 2]]
    face_normals = np.cross(v1 - v0, v2 - v0).astype("float32")
    for axis in range(3):
        np.add.at(normals[:, axis], faces[:, 0], face_normals[:, axis])
        np.add.at(normals[:, axis], faces[:, 1], face_normals[:, axis])
        np.add.at(normals[:, axis], faces[:, 2], face_normals[:, axis])
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    lengths[lengths == 0] = 1.0
    return normals / lengths


def roi_label_colors(values):
    import numpy as np

    values = np.asarray(values, dtype=np.int32)
    colors = np.zeros((len(values), 3), dtype="float32")
    positive = values > 0
    if np.any(positive):
        palette = np.asarray(LABEL_PALETTE, dtype="float32") / 255.0
        colors[positive] = palette[(values[positive] - 1) % len(palette)]
    return colors


def roi_label_rgba(values, alpha=1.0):
    import numpy as np

    rgb = roi_label_colors(values)
    rgba = np.zeros((len(rgb), 4), dtype="float32")
    rgba[:, :3] = rgb
    rgba[:, 3] = alpha
    return rgba


def face_majority_labels(vertex_labels, faces):
    import numpy as np

    face_vertex_labels = np.asarray(vertex_labels, dtype=np.int32)[faces]
    face_labels = np.zeros(face_vertex_labels.shape[0], dtype=np.int32)
    for index, labels in enumerate(face_vertex_labels):
        positive = labels[labels > 0]
        if positive.size == 0:
            continue
        values, counts = np.unique(positive, return_counts=True)
        face_labels[index] = int(values[np.argmax(counts)])
    return face_labels


def roi_to_colors(values):
    return roi_label_rgba(values, alpha=1.0)


def set_equal_aspect(ax, coords):
    import numpy as np

    mins = coords.min(axis=0)
    maxs = coords.max(axis=0)
    center = (mins + maxs) / 2.0
    radius = float(np.max(maxs - mins) / 2.0)
    if radius <= 0:
        radius = 1.0
    ax.set_xlim(center[0] - radius, center[0] + radius)
    ax.set_ylim(center[1] - radius, center[1] + radius)
    ax.set_zlim(center[2] - radius, center[2] + radius)


def tail_file(path: Path, max_lines: int = 100) -> str:
    if not path.exists():
        return ""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return "".join(deque(handle, maxlen=max_lines))


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, run_dir: Path | None = None, **kwargs):
        self.run_dir = run_dir or Path(directory or ".").resolve()
        super().__init__(*args, directory=str(self.run_dir), **kwargs)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self.serve_json(self.load_state())
            return
        if parsed.path == "/api/log":
            query = parse_qs(parsed.query)
            step_id = query.get("step", [""])[0]
            lines = int(query.get("lines", ["120"])[0])
            self.serve_log(step_id, lines)
            return
        if parsed.path == "/api/file":
            query = parse_qs(parsed.query)
            raw_path = query.get("path", [""])[0]
            self.serve_file_path(raw_path)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def load_state(self) -> dict:
        return load_state(self.run_dir)

    def serve_json(self, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_log(self, step_id: str, lines: int) -> None:
        try:
            state = self.load_state()
            step = get_step(state, step_id)
            log_path = self.run_dir / step["log_relpath"]
            body = tail_file(log_path, max_lines=max(10, min(lines, 400))).encode("utf-8", errors="replace")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, str(exc))

    def serve_file_path(self, raw_path: str) -> None:
        candidate = resolve_relocated_run_file(Path(unquote(raw_path)))
        if candidate.is_dir():
            entries = []
            for child in sorted(candidate.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower())):
                href = f"/api/file?path={quote(str(child))}"
                suffix = "/" if child.is_dir() else ""
                entries.append(f'<li><a href="{href}">{child.name}{suffix}</a></li>')
            body = (
                "<!doctype html><meta charset='utf-8'>"
                f"<title>{candidate}</title>"
                f"<h1>{candidate}</h1><ul>{''.join(entries) or '<li>(empty)</li>'}</ul>"
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, f"Missing file: {candidate}")
            return
        content_type, _ = mimetypes.guess_type(candidate.name)
        content_type = content_type or "application/octet-stream"
        try:
            data = candidate.read_bytes()
        except Exception as exc:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'inline; filename="{candidate.name}"')
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):  # noqa: A003
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (self.address_string(), self.log_date_time_string(), format % args)
        )


def drop_inherited_pipeline_lock() -> None:
    """Close inherited .pipeline.lock fds so --resume is not blocked (exit 75)."""
    fd_dir = Path("/proc/self/fd")
    if not fd_dir.is_dir():
        try:
            os.close(9)
        except OSError:
            pass
        return
    for entry in fd_dir.iterdir():
        try:
            fd = int(entry.name)
        except ValueError:
            continue
        if fd < 3:
            continue
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if Path(target).name == ".pipeline.lock":
            try:
                os.close(fd)
            except OSError:
                pass


def serve_dashboard(args: argparse.Namespace) -> int:
    drop_inherited_pipeline_lock()
    run_dir = Path(args.run_dir).resolve()
    if args.replace:
        replaced = replace_listener(args.host, args.port)
        if replaced:
            print(f"Replaced existing listener on {args.host}:{args.port}: {', '.join(str(pid) for pid in replaced)}", flush=True)
    handler = lambda *handler_args, **handler_kwargs: DashboardHandler(  # noqa: E731
        *handler_args,
        directory=str(run_dir),
        run_dir=run_dir,
        **handler_kwargs,
    )
    with ThreadingHTTPServer((args.host, args.port), handler) as httpd:
        print(f"Serving dashboard at http://{args.host}:{args.port}", flush=True)
        httpd.serve_forever()
    return 0


def listener_pids(host: str, port: int) -> list[int]:
    cmd = ["ss", "-ltnp", f"( sport = :{port} )"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return []

    pids: list[int] = []
    for line in result.stdout.splitlines():
        if host not in line and port and f":{port}" not in line:
            continue
        for match in re.finditer(r"pid=(\d+)", line):
            pid = int(match.group(1))
            if pid not in pids:
                pids.append(pid)
    return pids


def owned_by_current_user(pid: int) -> bool:
    try:
        return os.stat(f"/proc/{pid}").st_uid == os.getuid()
    except FileNotFoundError:
        return False


def terminate_pid(pid: int) -> bool:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False

    for _ in range(20):
        if not Path(f"/proc/{pid}").exists():
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        import time

        time.sleep(0.1)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return True


def replace_listener(host: str, port: int) -> list[int]:
    replaced: list[int] = []
    for pid in listener_pids(host, port):
        if pid == os.getpid():
            continue
        if not owned_by_current_user(pid):
            continue
        if terminate_pid(pid):
            replaced.append(pid)
    return replaced


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve and update a lightweight pipeline dashboard.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a dashboard run directory.")
    init_parser.add_argument("--run-dir", required=True)
    init_parser.add_argument("--subject-name", required=True)
    init_parser.add_argument("--subject-dir", required=True)
    init_parser.add_argument("--work-root", required=True)
    init_parser.add_argument("--dashboard-url", default="")
    init_parser.add_argument("--message", default="")
    init_parser.set_defaults(func=init_run)

    update_parser = subparsers.add_parser("update-step", help="Update one step in the dashboard state.")
    update_parser.add_argument("--run-dir", required=True)
    update_parser.add_argument("--step-id", required=True)
    update_parser.add_argument(
        "--status",
        required=True,
        choices=["pending", "running", "completed", "failed", "skipped"],
    )
    update_parser.add_argument("--message")
    update_parser.add_argument("--log-path")
    update_parser.add_argument("--preview")
    update_parser.add_argument("--artifact", action="append", default=[])
    update_parser.set_defaults(func=update_step)

    finalize_parser = subparsers.add_parser("finalize", help="Set a final dashboard message/status.")
    finalize_parser.add_argument("--run-dir", required=True)
    finalize_parser.add_argument("--message", required=True)
    finalize_parser.add_argument("--status", choices=["pending", "running", "completed", "failed", "partial"])
    finalize_parser.add_argument("--exit-code", type=int)
    finalize_parser.set_defaults(func=finalize_run)

    import_parser = subparsers.add_parser("import-existing", help="Build dashboard assets from an existing run directory.")
    import_parser.add_argument("--existing-run-dir", required=True)
    import_parser.add_argument("--dashboard-dir", required=True)
    import_parser.add_argument("--subject-name")
    import_parser.add_argument("--subject-dir")
    import_parser.add_argument("--dashboard-url", default="")
    import_parser.set_defaults(func=import_existing_run)

    preview_parser = subparsers.add_parser("render-preview", help="Render a preview image from NIfTI volumes.")
    preview_parser.add_argument("--image", required=True)
    preview_parser.add_argument("--output", required=True)
    preview_parser.add_argument("--overlay")
    preview_parser.add_argument("--title", default="")
    preview_parser.add_argument("--overlay-mode", choices=["label", "mask", "heatmap", "contour"], default="label")
    preview_parser.set_defaults(func=render_preview)

    stack_viewer_parser = subparsers.add_parser("render-stack-viewer", help="Render an interactive multi-stack slice viewer.")
    stack_viewer_parser.add_argument("--image-dir", required=True)
    stack_viewer_parser.add_argument("--overlay-dir")
    stack_viewer_parser.add_argument("--pattern", default="BTFE_*.nii.gz")
    stack_viewer_parser.add_argument("--output", required=True)
    stack_viewer_parser.add_argument("--title", default="")
    stack_viewer_parser.set_defaults(func=render_stack_viewer)

    mpr_viewer_parser = subparsers.add_parser("render-mpr-viewer", help="Render an interactive orthogonal MPR viewer.")
    mpr_viewer_parser.add_argument("--image", required=True)
    mpr_viewer_parser.add_argument("--overlay")
    mpr_viewer_parser.add_argument("--overlay-label", default="Labels")
    mpr_viewer_parser.add_argument("--output", required=True)
    mpr_viewer_parser.add_argument("--title", default="")
    mpr_viewer_parser.set_defaults(func=render_mpr_viewer)

    surface_preview_parser = subparsers.add_parser("render-surface-preview", help="Render a preview image from FreeSurfer-style surface outputs.")
    surface_preview_parser.add_argument("--surface-subject-dir", required=True)
    surface_preview_parser.add_argument("--output", required=True)
    surface_preview_parser.add_argument("--title", default="")
    surface_preview_parser.set_defaults(func=render_surface_preview)

    surface_html_parser = subparsers.add_parser("render-surface-html", help="Render an interactive HTML viewer from FreeSurfer-style surface outputs.")
    surface_html_parser.add_argument("--surface-subject-dir", required=True)
    surface_html_parser.add_argument("--output", required=True)
    surface_html_parser.add_argument("--title", default="")
    surface_html_parser.set_defaults(func=render_surface_interactive_html)

    serve_parser = subparsers.add_parser("serve", help="Serve dashboard files and API endpoints.")
    serve_parser.add_argument("--run-dir", required=True)
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--replace", action="store_true", help="Terminate an existing listener on the same port owned by the current user.")
    serve_parser.set_defaults(func=serve_dashboard)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

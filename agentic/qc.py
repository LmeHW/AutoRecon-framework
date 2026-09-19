from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np


STEP_ORDER = ["extraction", "reconstruction", "registration", "tissue", "roi", "surface"]
DEFAULT_PREREQ = {
    "reconstruction": "extraction",
    "registration": "reconstruction",
    "tissue": "registration",
    "roi": "registration",
    "surface": "roi",
}
GEOM_ATOL = 1e-3


def metric(
    name: str,
    label: str,
    value: Any,
    unit: str,
    criterion: str,
    status: str,
    source: str,
    contract_level: str = "l1",
) -> dict:
    return {
        "name": name, "label": label, "value": value, "unit": unit,
        "criterion": criterion, "status": status, "source": source,
        "contract_level": contract_level,
    }


def _image(path: Path) -> tuple[np.ndarray, nib.Nifti1Image]:
    image = nib.load(str(path))
    return np.asarray(image.dataobj), image


def _fraction(value: float) -> float:
    return round(float(value), 6)


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _contract_status(metrics: list[dict]) -> str:
    if not metrics:
        return "unavailable"
    l0 = [item for item in metrics if item.get("contract_level") == "l0"]
    if any(item.get("status") == "fail" for item in l0):
        return "fail"
    if any(item.get("status") in {"review", "fail"} for item in metrics if item.get("contract_level") != "l0"):
        return "review"
    return "pass"


def _step(step_id: str, metrics: list[dict], sources: list[str], limitations: list[str] | None = None) -> dict:
    states = {item["status"] for item in metrics}
    status = "fail" if "fail" in states else "review" if "review" in states else "pass" if metrics else "unavailable"
    return {
        "step_id": step_id, "status": status, "contract_status": _contract_status(metrics),
        "metrics": metrics, "sources": sources, "limitations": limitations or [],
    }


def _geometry_match(left: nib.Nifti1Image, right: nib.Nifti1Image) -> bool:
    return left.shape == right.shape and np.allclose(left.affine, right.affine, atol=GEOM_ATOL)


def _l0_reasons(step: dict) -> list[dict]:
    return [
        item for item in (step.get("metrics") or [])
        if item.get("contract_level") == "l0" and item.get("status") == "fail"
    ]


def _reason_message(step_id: str, reasons: list[dict]) -> str:
    if not reasons:
        return f"{step_id} L0 合同失败"
    parts = []
    for item in reasons:
        parts.append(f"{item.get('label') or item.get('name')}={item.get('value')}")
    return f"{step_id} L0 合同失败，下游不启动：" + "；".join(parts)


def _extraction_fingerprint(work_root: Path, subject: str) -> dict | None:
    state_path = work_root / "staging" / subject / "seg" / "extraction_state.json"
    if not state_path.is_file():
        return None
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return metric(
            "source_fingerprint_match", "提取输入指纹一致", False, "boolean", "= true",
            "fail", str(state_path), "l0",
        )
    mismatches: list[str] = []
    for record in payload.get("inputs") or []:
        name = str(record.get("name") or "")
        expected = record.get("sha256")
        staged = work_root / "staging" / subject / name
        if not name or not expected:
            continue
        if not staged.is_file() or _digest(staged) != expected:
            mismatches.append(name)
    ok = not mismatches
    detail = "unchanged" if ok else "changed:" + ",".join(mismatches[:6])
    return metric(
        "source_fingerprint_match", "提取输入指纹一致", ok, "boolean", "= true",
        "pass" if ok else "fail", f"{state_path}; {detail}", "l0",
    )


def _reconstruction_fingerprint(work_root: Path, subject: str, recon_path: Path) -> list[dict]:
    metrics: list[dict] = []
    result_paths = sorted((work_root / "outputs" / "reconstruction").glob("*/result.json"))
    if not result_paths:
        return metrics
    payload: dict[str, Any] = {}
    chosen = result_paths[0]
    for path in result_paths:
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if candidate.get("status") == "completed":
            payload, chosen = candidate, path
            break
        payload, chosen = candidate, path
    records = payload.get("input_records") or []
    if records:
        staging = work_root / "staging" / subject
        mismatches: list[str] = []
        for record in records:
            name = str(record.get("name") or "")
            expected = record.get("sha256")
            role = str(record.get("role") or "image")
            current = staging / "seg" / name if role == "mask" else staging / name
            if not name or not expected:
                continue
            if not current.is_file() or _digest(current) != expected:
                mismatches.append(f"{role}:{name}")
        ok = not mismatches
        metrics.append(metric(
            "input_fingerprint_match", "重建输入指纹一致", ok, "boolean", "= true",
            "pass" if ok else "fail",
            f"{chosen}; changed={','.join(mismatches[:6]) if mismatches else 'none'}",
            "l0",
        ))
    output_sha = payload.get("output_sha256") or payload.get("canonical_sha256")
    if output_sha and recon_path.is_file():
        ok = _digest(recon_path) == output_sha
        metrics.append(metric(
            "output_fingerprint_match", "重建产物指纹未被替换", ok, "boolean", "= true",
            "pass" if ok else "fail", str(recon_path), "l0",
        ))
    return metrics


def _extraction(work_root: Path, subject: str) -> dict:
    root = work_root / "staging" / subject
    inputs = sorted(root.glob("BTFE_*.nii.gz"))
    masks = root / "seg"
    valid, fractions, covered = 0, [], []
    geometry_ok = True
    sources = [str(path) for path in inputs]
    for path in inputs:
        mask_path = masks / path.name
        if not mask_path.is_file():
            continue
        try:
            array, mask_image = _image(mask_path)
            _, source_image = _image(path)
            if not _geometry_match(mask_image, source_image):
                geometry_ok = False
            if not np.isfinite(array).all():
                geometry_ok = False
                continue
            foreground = array > 0
            valid += 1
            fractions.append(float(foreground.mean()))
            axes = tuple(range(1, foreground.ndim))
            covered.append(float(np.any(foreground, axis=axes).mean()) if axes else float(foreground.any()))
            sources.append(str(mask_path))
        except Exception:
            continue
    count = len(inputs)
    success = valid / count if count else 0.0
    median_fraction = float(np.median(fractions)) if fractions else 0.0
    median_coverage = float(np.median(covered)) if covered else 0.0
    metrics = [
        metric("mask_success_rate", "有效脑掩膜比例", _fraction(success), "ratio", "= 1.0", "pass" if success == 1 else "fail", str(masks), "l0"),
        metric(
            "mask_geometry_match", "掩膜与输入栈几何一致", bool(inputs) and geometry_ok and success == 1,
            "boolean", "= true",
            "pass" if inputs and geometry_ok and success == 1 else "fail",
            str(masks), "l0",
        ),
        metric("median_foreground_fraction", "中位掩膜体素占比", _fraction(median_fraction), "ratio", "technical heuristic: 0.005–0.80", "pass" if 0.005 <= median_fraction <= 0.80 else "review", str(masks), "l1"),
        metric("median_slice_coverage", "中位有效切片覆盖率", _fraction(median_coverage), "ratio", "technical heuristic: > 0.10", "pass" if median_coverage > 0.10 else "review", str(masks), "l1"),
    ]
    fingerprint = _extraction_fingerprint(work_root, subject)
    if fingerprint:
        metrics.append(fingerprint)
    return _step("extraction", metrics, sources, ["Thresholds are technical completeness heuristics, not fetal-development reference ranges."])


def _volume_qc(step_id: str, path: Path, extra: list[dict] | None = None) -> dict:
    extras = list(extra or [])
    if not path.is_file():
        missing = [
            metric("output_present", "输出 NIfTI 存在", False, "boolean", "= true", "fail", str(path), "l0"),
        ]
        return _step(step_id, missing + extras, [str(path)], ["Expected NIfTI output is missing."])
    try:
        array, image = _image(path)
        finite = np.isfinite(array)
        finite_fraction = float(finite.mean())
        values = array[finite]
        nonzero_fraction = float(np.count_nonzero(values) / values.size) if values.size else 0.0
        positive = values[values != 0]
        contrast = float(np.percentile(positive, 95) - np.percentile(positive, 5)) if positive.size else 0.0
        return _step(step_id, [
            metric("output_present", "输出 NIfTI 存在", True, "boolean", "= true", "pass", str(path), "l0"),
            metric("finite_voxel_fraction", "有限值体素比例", _fraction(finite_fraction), "ratio", ">= 0.999", "pass" if finite_fraction >= 0.999 else "fail", str(path), "l0"),
            metric("nonzero_voxel_fraction", "非零体素比例", _fraction(nonzero_fraction), "ratio", "technical heuristic: 0.005–0.95", "pass" if 0.005 <= nonzero_fraction <= 0.95 else "review", str(path), "l1"),
            metric("robust_intensity_range", "稳健强度范围 P95-P5", round(contrast, 4), "a.u.", "> 0", "pass" if contrast > 0 else "fail", str(path), "l0"),
            metric("voxel_count", "体素数", int(np.prod(image.shape)), "voxels", "> 0", "pass" if np.prod(image.shape) > 0 else "fail", str(path), "l0"),
            *extras,
        ], [str(path)], ["Intensity metrics assess technical readability, not anatomy or diagnosis."])
    except Exception as exc:
        return _step(step_id, [
            metric("output_present", "输出 NIfTI 可读", False, "boolean", "= true", "fail", str(path), "l0"),
            *extras,
        ], [str(path)], [f"Cannot read NIfTI: {exc}"])


def _registration(work_root: Path, subject: str) -> dict:
    summary = work_root / "outputs" / "registration" / "summary.csv"
    rows: list[dict[str, str]] = []
    if summary.is_file():
        with summary.open(encoding="utf-8", errors="replace", newline="") as handle:
            rows = list(csv.DictReader(handle))
    row = rows[0] if rows else {}
    def number(key: str) -> float | None:
        try: return float(row[key])
        except (KeyError, TypeError, ValueError): return None
    mattes, gc = number("mattes_lower_is_better"), number("gc_lower_is_better")
    warped = Path(row.get("warped") or work_root / "outputs" / "registered_input" / f"{subject}.nii.gz")
    metrics = [
        metric("mattes", "Mattes 互信息（越低越好）", mattes, "score", "<= -0.25 acceptable", "pass" if mattes is not None and mattes <= -0.25 else "review" if mattes is not None else "fail", str(summary), "l1"),
        metric("global_correlation", "GC 全局相关指标（越低越好）", gc, "score", "<= -0.40 acceptable", "pass" if gc is not None and gc <= -0.40 else "review" if gc is not None else "fail", str(summary), "l1"),
        metric("registered_image_present", "规范化配准图像存在", bool(warped.is_file()), "boolean", "= true", "pass" if warped.is_file() else "fail", str(warped), "l0"),
    ]
    if warped.is_file():
        try:
            array, _ = _image(warped)
            finite = bool(np.isfinite(array).mean() >= 0.999)
            metrics.append(metric(
                "registered_finite", "配准图像有限值", finite, "boolean", "= true",
                "pass" if finite else "fail", str(warped), "l0",
            ))
        except Exception as exc:
            metrics.append(metric(
                "registered_finite", "配准图像可读", False, "boolean", "= true",
                "fail", f"{warped}; {exc}", "l0",
            ))
    return _step("registration", metrics, [str(summary), str(warped)], ["Thresholds come from the registration CLI QC configuration; visual overlay review remains required."])


def _label_qc(step_id: str, path: Path, reference: Path) -> dict:
    if not path.is_file():
        return _step(step_id, [
            metric("output_present", "标签图存在", False, "boolean", "= true", "fail", str(path), "l0"),
        ], [str(path)], ["Expected label image is missing."])
    try:
        labels, image = _image(path)
        unique = np.unique(labels[np.isfinite(labels)])
        foreground = float(np.count_nonzero(labels) / labels.size)
        geometry_match = False
        if reference.is_file():
            _, ref = _image(reference)
            geometry_match = _geometry_match(image, ref)
        finite = bool(np.isfinite(labels).all())
        return _step(step_id, [
            metric("output_present", "标签图存在", True, "boolean", "= true", "pass", str(path), "l0"),
            metric("label_finite", "标签图有限值", finite, "boolean", "= true", "pass" if finite else "fail", str(path), "l0"),
            metric("label_count", "标签数量（含背景）", int(unique.size), "labels", ">= 2", "pass" if unique.size >= 2 else "fail", str(path), "l0"),
            metric("foreground_fraction", "前景体素比例", _fraction(foreground), "ratio", "technical heuristic: 0.005–0.95", "pass" if 0.005 <= foreground <= 0.95 else "review", str(path), "l1"),
            metric("registered_geometry_match", "与配准 MRI 几何一致", geometry_match, "boolean", "= true", "pass" if geometry_match else "fail", f"{path}; {reference}", "l0"),
        ], [str(path), str(reference)], ["Label completeness does not establish anatomical correctness."])
    except Exception as exc:
        return _step(step_id, [
            metric("output_present", "标签图可读", False, "boolean", "= true", "fail", str(path), "l0"),
        ], [str(path)], [f"Cannot read label image: {exc}"])


def _surface(work_root: Path, subject: str) -> dict:
    root = work_root / "outputs" / "surface_subjects" / subject
    expected = ["lh.white", "rh.white", "lh.pial", "rh.pial", "lh.inflated", "rh.inflated"]
    present = [name for name in expected if (root / "surf" / name).is_file()]
    stats = [name for name in ("roi86_basic.stats", "roi86_thicknessproxy_cortexonly.stats") if (root / "stats" / name).is_file()]
    return _step("surface", [
        metric("required_surface_files", "必需表面文件完整度", len(present), "of 6", "= 6", "pass" if len(present) == 6 else "fail", str(root / "surf"), "l0"),
        metric("required_stats_files", "必需统计文件完整度", len(stats), "of 2", "= 2", "pass" if len(stats) == 2 else "fail", str(root / "stats"), "l0"),
    ], [str(root / "surf"), str(root / "stats")], ["File completeness does not replace topology and anatomical surface review."])


def _prereq_step(next_step: str, steps_by_id: dict[str, dict]) -> str | None:
    if next_step not in DEFAULT_PREREQ:
        return None
    if next_step in {"tissue", "roi"}:
        registration = steps_by_id.get("registration") or {}
        if registration.get("status") == "skipped":
            return "reconstruction"
    return DEFAULT_PREREQ[next_step]


def gate_decision(
    qc: dict,
    next_step: str | None = None,
    enforce_step: str | None = None,
) -> dict:
    steps_by_id = {str(item.get("step_id")): item for item in qc.get("steps") or []}
    target_id = enforce_step
    if next_step and not enforce_step:
        target_id = _prereq_step(next_step, steps_by_id)
        if target_id is None:
            return {"allowed": True, "blocked_by": None, "reasons": [], "message": ""}
    if not target_id:
        return {"allowed": True, "blocked_by": None, "reasons": [], "message": ""}
    step = steps_by_id.get(target_id) or {}
    if step.get("status") in {"pending"}:
        return {"allowed": True, "blocked_by": None, "reasons": [], "message": ""}
    reasons = _l0_reasons(step)
    if step.get("contract_status") == "fail" or reasons:
        return {
            "allowed": False,
            "blocked_by": target_id,
            "next_step": next_step,
            "reasons": reasons,
            "message": _reason_message(target_id, reasons),
        }
    return {"allowed": True, "blocked_by": None, "reasons": [], "message": "", "next_step": next_step}


def evaluate_run(work_root: Path, subject: str, selected_steps: list[str] | None = None) -> dict:
    work_root = work_root.resolve()
    registered = work_root / "outputs" / "registered_input" / f"{subject}.nii.gz"
    recon_path = work_root / "outputs" / "recon" / f"{subject}.nii.gz"
    steps = [
        _extraction(work_root, subject),
        _volume_qc("reconstruction", recon_path, _reconstruction_fingerprint(work_root, subject, recon_path)),
        _registration(work_root, subject),
        _label_qc("tissue", work_root / "outputs" / "Tissue" / f"{subject}.nii.gz", registered),
        _label_qc("roi", work_root / "outputs" / "ROI" / f"{subject}.nii.gz", registered),
        _surface(work_root, subject),
    ]
    dashboard_state = work_root / "dashboard" / "run_state.json"
    pipeline_status: dict[str, str] = {}
    if dashboard_state.is_file():
        try:
            data = json.loads(dashboard_state.read_text(encoding="utf-8"))
            pipeline_status = {str(item.get("id")): str(item.get("status")) for item in data.get("steps", [])}
        except (OSError, ValueError):
            pass
    selected = set(selected_steps or [])
    for item in steps:
        step_id = item["step_id"]
        runtime_status = pipeline_status.get(step_id)
        if runtime_status == "skipped":
            item["status"] = "skipped"
        elif runtime_status in {"pending", "running"}:
            item["status"] = "pending"
            item["contract_status"] = "pending"
            for value in item["metrics"]:
                if value["status"] == "fail":
                    value["status"] = "pending"
        elif selected and step_id not in selected:
            # Keep L0 metrics so a later requested step can still be gated on
            # existing artifacts, even when this step was not in --steps.
            pass
    return {
        "schema_version": "1.1", "subject": subject, "work_root": str(work_root),
        "steps": steps,
        "summary": {
            "pass": sum(item["status"] == "pass" for item in steps),
            "review": sum(item["status"] == "review" for item in steps),
            "fail": sum(item["status"] == "fail" for item in steps),
            "unavailable": sum(item["status"] == "unavailable" for item in steps),
            "pending": sum(item["status"] == "pending" for item in steps),
            "skipped": sum(item["status"] == "skipped" for item in steps),
            "l0_fail": sum(item.get("contract_status") == "fail" for item in steps),
            "l1_review": sum(item.get("contract_status") == "review" for item in steps),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build per-step AutoRecon QC evidence.")
    parser.add_argument("--work-root", required=True, type=Path)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--steps", default="")
    parser.add_argument("--gate-next", default="", help="Exit 2 if this step's L0 prerequisite failed.")
    parser.add_argument("--enforce-step", default="", help="Exit 2 if this completed step's L0 contract failed.")
    parser.add_argument("--gate-output", type=Path, help="Write the gate decision JSON.")
    args = parser.parse_args()
    selected = [item for item in args.steps.split(",") if item]
    result = evaluate_run(args.work_root, args.subject, selected or None)
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    elif not args.gate_next and not args.enforce_step:
        print(text, end="")
    decision = gate_decision(result, next_step=args.gate_next or None, enforce_step=args.enforce_step or None)
    if args.gate_output:
        args.gate_output.parent.mkdir(parents=True, exist_ok=True)
        args.gate_output.write_text(json.dumps(decision, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if (args.gate_next or args.enforce_step) and not decision.get("allowed", True):
        print(decision.get("message") or "L0 contract failed", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Automatic reconstruction comparison scoring and ranking (no clinical claim)."""

from __future__ import annotations

from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import random
from typing import Any

import nibabel as nib
import numpy as np


BACKENDS = ("frost", "nesvor", "autosvrtk", "niftymic")
AUTOMATIC_WEIGHT = 0.60
EXPERT_WEIGHT = 0.40
METRIC_SPECS = (
    ("sharpness", True, "Laplacian variance in foreground; higher is sharper."),
    ("intensity_stability", True, "1 - coefficient of variation in foreground."),
    ("low_background_artifact", True, "Inverted background-to-foreground mean ratio."),
    ("coverage", True, "Foreground voxel fraction."),
    ("registration_mattes", False, "ANTs Mattes; more negative is better."),
    ("registration_gc", False, "ANTs global correlation; more negative is better."),
    ("atlas_overlap", True, "Foreground overlap with atlas after registration."),
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _load_volume(path: Path) -> tuple[np.ndarray, np.ndarray, tuple[float, ...]]:
    image = nib.load(str(path))
    data = np.asarray(image.dataobj, dtype=np.float32)
    spacing = tuple(float(v) for v in image.header.get_zooms()[:3])
    return data, np.asarray(image.affine, dtype=np.float64), spacing


def hard_gate(path: Path | None) -> dict[str, Any]:
    result = {"passed": False, "reasons": [], "path": str(path) if path else None}
    if path is None or not path.is_file():
        result["reasons"].append("missing_nifti")
        return result
    try:
        data, affine, spacing = _load_volume(path)
    except Exception as exc:
        result["reasons"].append(f"unreadable:{type(exc).__name__}:{exc}")
        return result
    if data.ndim != 3 or any(dim <= 16 for dim in data.shape):
        result["reasons"].append("illegal_shape")
    if not np.isfinite(data).all():
        result["reasons"].append("non_finite")
    if int(np.count_nonzero(data)) == 0:
        result["reasons"].append("empty_volume")
    if not np.isfinite(affine).all() or not all(np.isfinite(spacing)):
        result["reasons"].append("illegal_affine_or_spacing")
    coverage = float(np.count_nonzero(data) / data.size)
    if coverage < 0.01:
        result["reasons"].append("severe_coverage_loss")
    result["passed"] = not result["reasons"]
    result.update({"shape": list(data.shape), "spacing": list(spacing), "coverage": coverage})
    return result


def image_metrics(path: Path) -> dict[str, float]:
    data, _affine, _spacing = _load_volume(path)
    finite = np.isfinite(data)
    foreground = finite & (data > 0)
    background = finite & ~foreground
    values = data[foreground]
    if values.size == 0:
        return {"sharpness": 0.0, "intensity_stability": 0.0, "low_background_artifact": 0.0, "coverage": 0.0}
    padded = np.pad(np.where(foreground, data, 0.0), 1, mode="edge")
    lap = (
        padded[2:, 1:-1, 1:-1] + padded[:-2, 1:-1, 1:-1]
        + padded[1:-1, 2:, 1:-1] + padded[1:-1, :-2, 1:-1]
        + padded[1:-1, 1:-1, 2:] + padded[1:-1, 1:-1, :-2]
        - 6.0 * padded[1:-1, 1:-1, 1:-1]
    )
    sharpness = float(np.var(lap[foreground]))
    mean = float(np.mean(values))
    std = float(np.std(values))
    stability = float(1.0 / (1.0 + (std / mean if mean else 0.0)))
    bg_mean = float(np.mean(np.abs(data[background]))) if np.any(background) else 0.0
    artifact = float(1.0 / (1.0 + (bg_mean / mean if mean else 0.0)))
    coverage = float(np.count_nonzero(foreground) / data.size)
    return {
        "sharpness": sharpness,
        "intensity_stability": stability,
        "low_background_artifact": artifact,
        "coverage": coverage,
    }


def atlas_overlap(registered: Path, atlas: Path) -> float:
    moving, *_ = _load_volume(registered)
    fixed, *_ = _load_volume(atlas)
    if moving.shape != fixed.shape:
        return 0.0
    a = moving > 0
    b = fixed > 0
    intersection = float(np.logical_and(a, b).sum())
    union = float(np.logical_or(a, b).sum())
    return intersection / union if union else 0.0


def _normalize(values: list[float | None], higher_is_better: bool) -> list[float | None]:
    present = [value for value in values if value is not None and np.isfinite(value)]
    if not present:
        return [None for _ in values]
    lo, hi = min(present), max(present)
    out: list[float | None] = []
    for value in values:
        if value is None or not np.isfinite(value):
            out.append(None)
            continue
        if hi == lo:
            scaled = 1.0
        else:
            scaled = (value - lo) / (hi - lo)
        out.append(scaled if higher_is_better else 1.0 - scaled)
    return out


def _parse_registration(summary_csv: Path | None) -> dict[str, Any]:
    if summary_csv is None or not summary_csv.is_file():
        return {"status": "missing"}
    with summary_csv.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        return {"status": "empty"}
    row = rows[0]
    try:
        mattes = float(row.get("mattes_lower_is_better") or "nan")
        gc = float(row.get("gc_lower_is_better") or "nan")
    except ValueError:
        return {"status": "unparseable", "row": row}
    qc_group = str(row.get("qc_group") or "")
    status = str(row.get("status") or "")
    passed = status == "ok" and qc_group in {"acceptable", "suspicious"}
    return {
        "status": "completed" if passed else "failed",
        "qc_group": qc_group,
        "mattes": mattes,
        "gc": gc,
        "warped": row.get("warped"),
        "row": row,
    }


def discover_backend_outputs(work_root: Path, subject: str) -> dict[str, dict[str, Path | None]]:
    recon_root = work_root / "outputs" / "reconstruction"
    found: dict[str, dict[str, Path | None]] = {}
    for backend in BACKENDS:
        recon = recon_root / backend / f"{subject}.nii.gz"
        result = recon_root / backend / "result.json"
        candidate = work_root / "outputs" / "recon_candidates" / backend / f"{subject}.nii.gz"
        image = recon if recon.is_file() else (candidate if candidate.is_file() else None)
        found[backend] = {
            "image": image,
            "result_json": result if result.is_file() else None,
            "registration_csv": None,
            "warped": None,
        }
    canonical_csv = work_root / "outputs" / "registration" / "summary.csv"
    if canonical_csv.is_file():
        selected = "frost"
        selected_result = recon_root / "frost" / "result.json"
        if selected_result.is_file():
            selected = json.loads(selected_result.read_text(encoding="utf-8")).get("backend", "frost")
        found.setdefault(selected, {})
        found[selected]["registration_csv"] = canonical_csv
        warped = work_root / "outputs" / "registration" / "acceptable_cases" / "best"
        if not warped.is_dir():
            warped = work_root / "outputs" / "registration" / "suspicious_cases" / "best"
        if warped.is_dir():
            niftis = sorted(warped.glob("*.nii.gz"))
            found[selected]["warped"] = niftis[0] if niftis else None
    for backend in BACKENDS:
        extra_csv = work_root / "outputs" / "reconstruction" / "comparison" / backend / "registration" / "summary.csv"
        if extra_csv.is_file():
            found[backend]["registration_csv"] = extra_csv
            extra_best = extra_csv.parent / "acceptable_cases" / "best"
            if extra_best.is_dir():
                niftis = sorted(extra_best.glob("*.nii.gz"))
                found[backend]["warped"] = niftis[0] if niftis else found[backend].get("warped")
    return found


def score_candidates(
    work_root: Path,
    subject: str,
    atlas: Path,
    *,
    expert_review: Path | None = None,
    seed: int = 29,
) -> dict[str, Any]:
    comparison_dir = work_root / "outputs" / "reconstruction" / "comparison"
    comparison_dir.mkdir(parents=True, exist_ok=True)
    discovered = discover_backend_outputs(work_root, subject)
    rng = random.Random(seed)
    labels = list("ABCD")
    rng.shuffle(labels)
    blind_mapping = {label: backend for label, backend in zip(labels, BACKENDS)}
    write_json(comparison_dir / "blind_mapping.json", {
        "schema_version": 1, "generated_at": now(), "mapping": blind_mapping,
        "note": "Blind labels are for reviewer UI only. Ranking files keep backend ids for audit.",
    })

    rows: list[dict[str, Any]] = []
    for backend in BACKENDS:
        paths = discovered.get(backend) or {}
        image = paths.get("image")
        gate = hard_gate(image if isinstance(image, Path) else None)
        registration = _parse_registration(paths.get("registration_csv") if isinstance(paths.get("registration_csv"), Path) else None)
        metrics = image_metrics(image) if gate["passed"] and isinstance(image, Path) else {
            "sharpness": None, "intensity_stability": None, "low_background_artifact": None, "coverage": None,
        }
        overlap = None
        warped = paths.get("warped")
        if isinstance(warped, Path) and warped.is_file() and atlas.is_file():
            try:
                overlap = atlas_overlap(warped, atlas)
            except Exception:
                overlap = None
        if registration.get("status") != "completed":
            gate["passed"] = False
            if "registration_failed" not in gate["reasons"]:
                gate["reasons"].append("registration_failed")
        result_json = paths.get("result_json")
        backend_result = {}
        if isinstance(result_json, Path) and result_json.is_file():
            backend_result = json.loads(result_json.read_text(encoding="utf-8"))
        rows.append({
            "backend": backend,
            "blind_label": next(label for label, name in blind_mapping.items() if name == backend),
            "gate": gate,
            "eligible": gate["passed"],
            "image": str(image) if image else None,
            "metrics": {
                **metrics,
                "registration_mattes": registration.get("mattes"),
                "registration_gc": registration.get("gc"),
                "atlas_overlap": overlap,
            },
            "registration": {key: value for key, value in registration.items() if key != "row"},
            "backend_result": {
                "status": backend_result.get("status"),
                "error": backend_result.get("error"),
                "input_fingerprint": backend_result.get("input_fingerprint"),
                "started_at": backend_result.get("started_at"),
                "finished_at": backend_result.get("finished_at"),
            },
        })

    for name, higher, _help in METRIC_SPECS:
        raw = [row["metrics"].get(name) for row in rows]
        normalized = _normalize(raw, higher)
        for row, value in zip(rows, normalized):
            row.setdefault("normalized", {})[name] = value

    for row in rows:
        available = [value for value in row.get("normalized", {}).values() if value is not None]
        row["automatic_score"] = float(sum(available) / len(available)) if row["eligible"] and available else None

    expert_scores = _load_expert_scores(expert_review or comparison_dir / "expert_review.csv")
    expert_complete = bool(expert_scores) and all(backend in expert_scores for backend in BACKENDS if any(row["backend"] == backend and row["eligible"] for row in rows))
    ranking_rows = []
    for row in rows:
        expert = expert_scores.get(row["backend"])
        final = None
        if row["automatic_score"] is not None and expert_complete and expert is not None:
            final = AUTOMATIC_WEIGHT * row["automatic_score"] + EXPERT_WEIGHT * (expert / 5.0)
        ranking_rows.append({
            **row,
            "expert_score": expert,
            "final_score": final,
            "normalized": row.get("normalized", {}),
        })

    eligible = [row for row in ranking_rows if row["eligible"] and row["automatic_score"] is not None]
    if expert_complete:
        eligible.sort(key=lambda row: (
            -(row["final_score"] or -1),
            -(row["expert_score"] or -1),
            -(row["normalized"].get("registration_mattes") or -1),
            -(row["normalized"].get("low_background_artifact") or -1),
        ))
        mode = "final_with_expert"
    else:
        eligible.sort(key=lambda row: (
            -(row["automatic_score"] or -1),
            -(row["normalized"].get("registration_mattes") or -1),
            -(row["normalized"].get("low_background_artifact") or -1),
        ))
        mode = "automatic_only"

    for index, row in enumerate(eligible, 1):
        row["rank"] = index
    for row in ranking_rows:
        row.setdefault("rank", None)

    recommended = eligible[0]["backend"] if eligible and mode == "final_with_expert" else None
    payload = {
        "schema_version": 1,
        "generated_at": now(),
        "subject": subject,
        "work_root": str(work_root),
        "ranking_mode": mode,
        "recommended_backend": recommended,
        "recommendation_statement": (
            f"{subject} 本病例、当前指标和当前评审条件下的推荐方法是 {recommended}。"
            if recommended else
            "缺少完整盲评，仅输出自动技术排名，不得宣称最终最佳方法。"
        ),
        "disclaimer": "技术排名不代表胎儿医学正常，也不代表该方法在其他病例或临床场景中普遍最优。",
        "weights": {"automatic": AUTOMATIC_WEIGHT, "expert": EXPERT_WEIGHT},
        "metric_specs": [{"name": name, "higher_is_better": higher, "description": help_} for name, higher, help_ in METRIC_SPECS],
        "candidates": ranking_rows,
        "hidden_failures_forbidden": True,
    }
    write_json(comparison_dir / "ranking.json", payload)
    _write_metrics_csv(comparison_dir / "automatic_metrics.csv", ranking_rows)
    if not (comparison_dir / "expert_review.csv").is_file():
        (comparison_dir / "expert_review.csv").write_text(
            "backend,blind_label,residual_motion,anatomy_clarity,tissue_boundary,coverage,artifact,reviewer,notes\n",
            encoding="utf-8",
        )
    report = _comparison_report(payload)
    (comparison_dir / "comparison_report.md").write_text(report, encoding="utf-8")
    return payload


def _load_expert_scores(path: Path) -> dict[str, float]:
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    scores: dict[str, float] = {}
    fields = ("residual_motion", "anatomy_clarity", "tissue_boundary", "coverage", "artifact")
    for row in rows:
        backend = (row.get("backend") or "").strip()
        if not backend:
            continue
        try:
            values = [float(row[field]) for field in fields]
        except (KeyError, TypeError, ValueError):
            continue
        if any(not 1 <= value <= 5 for value in values):
            continue
        scores[backend] = float(sum(values) / len(values))
    return scores


def _write_metrics_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = ["backend", "blind_label", "eligible", "automatic_score", "expert_score", "final_score", "rank"]
    fieldnames += [name for name, _higher, _help in METRIC_SPECS]
    fieldnames += [f"{name}_norm" for name, _higher, _help in METRIC_SPECS]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            item = {
                "backend": row["backend"],
                "blind_label": row["blind_label"],
                "eligible": row["eligible"],
                "automatic_score": row.get("automatic_score"),
                "expert_score": row.get("expert_score"),
                "final_score": row.get("final_score"),
                "rank": row.get("rank"),
            }
            for name, _higher, _help in METRIC_SPECS:
                item[name] = row["metrics"].get(name)
                item[f"{name}_norm"] = (row.get("normalized") or {}).get(name)
            writer.writerow(item)


def _comparison_report(payload: dict[str, Any]) -> str:
    lines = [
        f"# {payload['subject']} 四后端比较",
        "",
        payload["recommendation_statement"],
        "",
        payload["disclaimer"],
        "",
        f"排名模式：`{payload['ranking_mode']}`",
        "",
        "| 方法 | 盲评标签 | 门禁 | 自动分 | 人工分 | 最终分 | 名次 | 失败原因 |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for row in payload["candidates"]:
        reasons = ",".join(row["gate"].get("reasons") or []) or "-"
        lines.append(
            f"| {row['backend']} | {row['blind_label']} | {'PASS' if row['eligible'] else 'FAIL'} | "
            f"{_fmt(row.get('automatic_score'))} | {_fmt(row.get('expert_score'))} | "
            f"{_fmt(row.get('final_score'))} | {row.get('rank') or '-'} | {reasons} |"
        )
    lines += ["", "## 指标来源", ""]
    for spec in payload["metric_specs"]:
        direction = "越高越好" if spec["higher_is_better"] else "越低越好，归一化时取反"
        lines.append(f"- `{spec['name']}`：{spec['description']}（{direction}）")
    return "\n".join(lines) + "\n"


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):.4f}"


def fingerprint_from_result(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("input_fingerprint")
    except Exception:
        return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

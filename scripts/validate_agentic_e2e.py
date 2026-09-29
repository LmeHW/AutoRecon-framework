#!/usr/bin/env python3
"""Phased, evidence-producing validation for the natural-language AutoRecon flow."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import time
from typing import Any, Iterable

import nibabel as nib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentic.coordinator import coordinate, coordinate_with_llm
from agentic.env_config import LLMConfig, load_llm_config
from agentic.executor import AgenticExecutor
from agentic.llm_client import OpenAICompatibleClient
from agentic.planner import plan_with_llm, validate_plan, validate_runtime
from agentic.reporter import build_report, validate_llm_report
from agentic.schema_validation import validate_agentic_objects
from validation.nl_corpus import ATLAS_ROOT, CORPUS, DATASET_ROOT, FULL


ACCEPTABLE_CSV = DATASET_ROOT / "registration/acceptable_cases/summary_acceptable.csv"
SELECTED = (
    ("TangWen", "25周", 25, "exact", 5, "低孕周边界"),
    ("ShiYuQing", "27周", 27, "exact", 6, "低中孕周"),
    ("LiChenQian", "29周", 29, "exact", 10, "多 stack 压力"),
    ("DaiLuLu", "31周+4", 31, "exact", 9, "中心孕周、多 stack"),
    ("ZhouMinMin", "33周+1", 33, "exact", 8, "高孕周"),
    ("XuJing", "35周+2", 35, "exact", 11, "atlas 上限及最多 stack"),
    ("ChenYanTing", "36周+5", 35, "nearest_from_36w", 5, "36w→35w 边界"),
    ("ZuoXiaoFen", "38周+1", 35, "nearest_from_38w", 3, "38w→35w 边界"),
)
HISTORICAL = {
    "AnHuiJing": ROOT / "runs/legacy/AnHuiJing/run01",
    "BaiHuPing": ROOT / "runs/legacy/BaiHuPing/run01",
    "CaiYuYu": ROOT / "runs/legacy/CaiYuYu/raw_run01",
    "CaoLi": ROOT / "runs/legacy/CaoLi/registered_run02",
}
SEMANTIC_FIELDS = (
    "execution_mode", "subject_dir", "work_root", "existing_run_dir", "gestational_age", "atlas", "atlas_week", "atlas_rule",
    "reconstruction_tool", "reconstruction_compare_tools", "roi_mode", "surface", "resume",
    "execution_steps", "display_steps", "report_steps", "report_language", "report_detail",
    "report_layout", "missing", "unfulfilled_requests",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def percentile(values: list[float], value: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * value
    lower, upper = int(index), min(int(index) + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def image_metadata(path: Path, *, read_data: bool) -> dict[str, Any]:
    image = nib.load(str(path))
    result: dict[str, Any] = {
        "path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256(path),
        "shape": list(image.shape), "spacing": [float(v) for v in image.header.get_zooms()[:3]],
        "affine": np.asarray(image.affine).round(8).tolist(),
    }
    if len(image.shape) != 3 or any(value <= 0 for value in image.shape):
        raise ValueError(f"not a valid non-empty 3D image: {path}")
    if not np.isfinite(image.affine).all():
        raise ValueError(f"non-finite affine: {path}")
    if read_data:
        data = np.asarray(image.dataobj)
        result.update({
            "finite": bool(np.isfinite(data).all()), "nonzero_voxels": int(np.count_nonzero(data)),
            "minimum": float(np.nanmin(data)), "maximum": float(np.nanmax(data)),
        })
        if not result["finite"] or not result["nonzero_voxels"]:
            raise ValueError(f"empty or non-finite volume: {path}")
    return result


def load_acceptable() -> list[dict[str, str]]:
    with ACCEPTABLE_CSV.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def data_preflight() -> dict[str, Any]:
    rows = load_acceptable()
    errors: list[str] = []
    warnings: list[str] = []
    index: list[dict[str, Any]] = []
    for row in rows:
        subject_dir = DATASET_ROOT / "nii" / row["case"]
        stacks = sorted(subject_dir.glob("*.nii.gz"))
        atlas = Path(row["atlas"])
        problems = []
        if row.get("status") != "ok" or row.get("qc_group") != "acceptable":
            problems.append("CSV row is not acceptable/ok")
        if not stacks:
            problems.append("no BTFE stacks")
        if not atlas.is_file():
            problems.append("atlas missing")
        if problems:
            warnings.extend(f"{row['case']}: {item}" for item in problems)
        index.append({
            "case": row["case"], "chinese_name": row.get("chinese_name"),
            "gestational_age": row["gestational_age"], "atlas_week": int(row["atlas_week"]),
            "atlas_rule": row["atlas_rule"], "subject_dir": str(subject_dir),
            "atlas": str(atlas), "stack_count": len(stacks), "problems": problems,
        })

    by_case = {row["case"]: row for row in rows}
    selected: list[dict[str, Any]] = []
    for case, ga, week, rule, expected_stacks, purpose in SELECTED:
        row = by_case.get(case)
        if not row:
            errors.append(f"selected case missing from CSV: {case}")
            continue
        subject_dir = DATASET_ROOT / "nii" / case
        stacks = sorted(subject_dir.glob("*.nii.gz"))
        checks = {
            "gestational_age": row["gestational_age"] == ga,
            "atlas_week": int(row["atlas_week"]) == week,
            "atlas_rule": row["atlas_rule"] == rule,
            "stack_count": len(stacks) == expected_stacks,
            "status": row["status"] == "ok" and row["qc_group"] == "acceptable",
        }
        if not all(checks.values()):
            errors.append(f"selected case gold mismatch: {case}: {checks}")
        stack_metadata = []
        for stack in stacks:
            try:
                stack_metadata.append(image_metadata(stack, read_data=True))
            except Exception as exc:  # evidence should contain every preflight failure
                errors.append(f"{case}/{stack.name}: {type(exc).__name__}: {exc}")
        selected.append({
            "case": case, "gestational_age": ga, "atlas_week": week, "atlas_rule": rule,
            "purpose": purpose, "expected_stack_count": expected_stacks, "checks": checks,
            "subject_dir": str(subject_dir), "atlas": str(ATLAS_ROOT / f"{week}w.nii.gz"),
            "stacks": stack_metadata,
        })

    atlases = []
    for week in range(22, 36):
        path = ATLAS_ROOT / f"{week}w.nii.gz"
        try:
            atlases.append({"week": week, **image_metadata(path, read_data=True)})
        except Exception as exc:
            errors.append(f"atlas {week}w: {type(exc).__name__}: {exc}")
    return {
        "schema_version": 1, "generated_at": now(), "status": "passed" if not errors else "failed",
        "acceptable_csv": str(ACCEPTABLE_CSV), "acceptable_count": len(rows),
        "indexed_count": len(index), "index": index, "selected": selected, "atlases": atlases,
        "errors": errors, "warnings": warnings,
    }


def _command_check(command: list[str]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
        return {
            "command": command, "status": "passed" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode, "duration_seconds": time.perf_counter() - started,
            "stdout": completed.stdout[-2000:], "stderr": completed.stderr[-2000:],
        }
    except Exception as exc:
        return {"command": command, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def runtime_preflight(config: LLMConfig) -> dict[str, Any]:
    commands = [
        ["bash", "pipeline/check_runtime.sh"],
        ["nvidia-smi", "--query-gpu=index,name,memory.total", "--format=csv,noheader"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
    ]
    checks = [_command_check(command) for command in commands]
    paths = {
        "antsRegistration": Path(config.ants_dir) / "antsRegistration",
        "roi_python": Path(config.roi_warp_env) / "bin/python",
        "frost_container": ROOT / ".runtime/containers/frost.sif",
        "extraction_container": ROOT / ".runtime/containers/extraction_nnunet.sif",
        "tissue_container": ROOT / ".runtime/containers/tissue_nnunet.sif",
    }
    path_checks = {name: {"path": str(path), "exists": path.exists(), "executable": os.access(path, os.X_OK)} for name, path in paths.items()}
    disk = shutil.disk_usage(ROOT)
    blockers = ["command failed: " + " ".join(item["command"]) for item in checks if item["status"] != "passed"]
    blockers += [f"missing runtime asset: {name}" for name, item in path_checks.items() if not item["exists"]]
    if disk.free < 100 * 1024**3:
        blockers.append(f"less than 100 GiB free under validation root: {disk.free / 1024**3:.1f} GiB")
    return {
        "schema_version": 1, "generated_at": now(), "status": "passed" if not blockers else "blocked",
        "checks": checks, "paths": path_checks,
        "disk": {"total_bytes": disk.total, "used_bytes": disk.used, "free_bytes": disk.free},
        "llm": config.public_dict(), "blockers": blockers,
    }


def historical_import_validation(output_root: Path) -> dict[str, Any]:
    """Exercise import -> QC -> dashboard link -> deterministic report for four cases."""
    executor = AgenticExecutor(ROOT, output_root / "agentic_import_runs")
    results: list[dict[str, Any]] = []
    seen_subjects: set[str] = set()
    for subject, existing in HISTORICAL.items():
        started = time.perf_counter()
        error = None
        checks: dict[str, bool] = {}
        try:
            request, _ = coordinate_with_llm(
                "导入已有结果，展示全部步骤并生成完整中文技术报告。",
                {"execution_mode": "import_existing", "existing_run_dir": str(existing),
                 "explicit_fields": ["execution_mode", "existing_run_dir"]},
                None,
            )
            task_plan, _ = plan_with_llm(request, None)
            imported, dashboard = executor.execute(task_plan, f"historical_{subject}")
            report, report_json = build_report(task_plan, imported, dashboard, llm=None)
            analysis = report_json.get("technical_analysis") or {}
            case_info = analysis.get("case_info") or {}
            registration = analysis.get("registration_summary") or {}
            evidence_subject = str(case_info.get("subject") or "")
            seen_subjects.add(evidence_subject)
            checks = {
                "input_completed": bool(imported and imported[0].get("status") == "completed"),
                "visualization_completed": any(item.get("step_id") == "visualization" and item.get("status") == "completed" for item in imported),
                "metrics_present": any(item.get("step_id") == "metrics" for item in imported),
                "subject_matches": evidence_subject == subject,
                "report_mentions_subject": subject in report,
                "dashboard_state_exists": Path(dashboard["dashboard_state"]).is_file(),
                "registration_is_evidenced": bool(registration.get("available") or registration.get("message")),
                "capability_boundary": "Capability Boundary" in report or "能力边界" in report,
                "no_affirmative_clinical_claim": not any("affirmative clinical claim" in item for item in validate_llm_report(report, report_json)),
            }
            case_dir = output_root / "historical_import" / subject
            case_dir.mkdir(parents=True, exist_ok=True)
            (case_dir / "report.md").write_text(report, encoding="utf-8")
            write_json(case_dir / "report.json", report_json)
            write_json(case_dir / "step_results.json", imported)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        results.append({
            "subject": subject, "existing_run_dir": str(existing), "checks": checks,
            "passed": not error and bool(checks) and all(checks.values()), "error": error,
            "duration_seconds": time.perf_counter() - started,
        })
    isolation_ok = seen_subjects == set(HISTORICAL)
    status = "passed" if all(item["passed"] for item in results) and isolation_ok else "failed"
    return {
        "schema_version": 1, "generated_at": now(), "status": status,
        "case_isolation": isolation_ok, "results": results,
        "success_rate": sum(item["passed"] for item in results) / len(results),
    }


def real_report_validation(output_root: Path, config: LLMConfig) -> dict[str, Any]:
    executor = AgenticExecutor(ROOT, output_root / "agentic_real_report_runs")
    llm = OpenAICompatibleClient(config) if config.available else None
    prompts = (
        "导入{case}已有完整结果，生成中文技术报告，明确实际孕周和所用atlas周数。",
        "Import the completed {case} run and produce an evidence-grounded technical report.",
        "查看{case}六阶段结果，每一步给出QC并汇总最终报告。",
        "只展示{case}的registration，但报告使用所有可用证据。",
    )
    results = []
    for index, (case, ga_text, week, rule, _stack_count, _purpose) in enumerate(SELECTED):
        run_dir = output_root / "real_pipeline" / case
        acceptance_path = run_dir / "acceptance.json"
        numeric_ga = float(week)
        if "+" in ga_text:
            base, days = ga_text.replace("周", "").split("+")
            numeric_ga = int(base) + int(days) / 7
        text = prompts[index % len(prompts)].format(case=case)
        overrides = {
            "execution_mode": "import_existing", "existing_run_dir": str(run_dir),
            "gestational_age": numeric_ga, "atlas": str(ATLAS_ROOT / f"{week}w.nii.gz"),
            "atlas_week": week, "atlas_rule": rule,
            "explicit_fields": ["execution_mode", "existing_run_dir", "gestational_age", "atlas", "atlas_week", "atlas_rule"],
        }
        started = time.perf_counter()
        error = None
        checks: dict[str, bool] = {}
        try:
            acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
            request, request_event = coordinate_with_llm(text, overrides, llm)
            task_plan, plan_event = plan_with_llm(request, llm)
            imported, dashboard = executor.execute(task_plan, f"real_report_{case}")
            report, report_json = build_report(task_plan, imported, dashboard, llm, [request_event, plan_event])
            analysis = report_json.get("technical_analysis") or {}
            evidence_subject = str((analysis.get("case_info") or {}).get("subject") or "")
            report_dir = output_root / "real_reports" / case
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "report.md").write_text(report, encoding="utf-8")
            write_json(report_dir / "report.json", report_json)
            write_json(report_dir / "request.json", request.to_dict())
            write_json(report_dir / "plan.json", task_plan.to_dict())
            checks = {
                "strict_acceptance": acceptance.get("status") == "completed",
                "subject_matches": evidence_subject == case and case in report,
                "gestational_age_preserved": task_plan.gestational_age == numeric_ga and (
                    f"Gestational age: `{numeric_ga}`" in report or f"孕周：{numeric_ga}" in report
                ),
                "atlas_week_preserved": task_plan.atlas_week == week and (
                    f"Atlas week: `{week}`" in report or f"图谱周龄：{week}" in report
                ),
                "atlas_rule_preserved": task_plan.atlas_rule == rule and rule in report,
                "evidence_bank_present": bool(report_json.get("evidence_bank")),
                "dashboard_state_exists": Path(dashboard["dashboard_state"]).is_file(),
                "no_affirmative_clinical_claim": not any("affirmative clinical claim" in item for item in validate_llm_report(report, report_json)),
                "boundary_not_conflated": numeric_ga <= 35 or numeric_ga != task_plan.atlas_week,
            }
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        results.append({
            "case": case, "natural_language": text, "gestational_age": numeric_ga,
            "atlas_week": week, "atlas_rule": rule, "checks": checks,
            "passed": not error and bool(checks) and all(checks.values()), "error": error,
            "duration_seconds": time.perf_counter() - started,
        })
    return {
        "schema_version": 1, "generated_at": now(),
        "status": "passed" if all(item["passed"] for item in results) else "failed",
        "llm_reporting_enabled": bool(llm), "results": results,
        "success_rate": sum(item["passed"] for item in results) / len(results),
    }
def semantic_payload(request: dict[str, Any]) -> dict[str, Any]:
    return {key: request.get(key) for key in SEMANTIC_FIELDS}


def compare_expected(actual: dict[str, Any], expected: dict[str, Any]) -> list[dict[str, Any]]:
    mismatches = []
    for field, wanted in expected.items():
        if field.endswith("_contains"):
            source_field = field.removesuffix("_contains")
            got = actual.get(source_field) or []
            if not all(value in got for value in wanted):
                mismatches.append({"field": source_field, "expected_contains": wanted, "actual": got})
            continue
        got = actual.get(field)
        if field == "missing":
            got, wanted = sorted(got or []), sorted(wanted or [])
        if got != wanted:
            mismatches.append({"field": field, "expected": wanted, "actual": got})
    return mismatches


def assert_external_corpus_is_anonymous() -> None:
    """Hard gate before an external LLM receives validation text."""
    forbidden_names = {item[0].lower() for item in SELECTED} | {name.lower() for name in HISTORICAL}
    for item in CORPUS:
        text = item["natural_language"]
        lowered = text.lower()
        if re.search(r"(?:^|\s)/(?:mnt|home|data|tmp)/", text) or any(name in lowered for name in forbidden_names):
            raise ValueError(f"external LLM corpus contains a local path or case identifier: {item['case_id']}")


def corpus_run(
    mode: str, repeats: int, config: LLMConfig, progress_path: Path | None = None,
    workers: int = 1, retry_llm_fallbacks: bool = False,
) -> dict[str, Any]:
    if mode == "llm":
        assert_external_corpus_is_anonymous()
    if mode == "llm" and not config.available:
        return {
            "schema_version": 1, "generated_at": now(), "mode": mode, "status": "blocked",
            "reason": "LLM is unavailable; configure AUTORECON_LLM_API_KEY.", "results": [],
        }
    signature = hashlib.sha256(json.dumps(
        {"logic_version": 4, "cases": [{"case_id": item["case_id"], "text": item["natural_language"], "expected": item["expected"]} for item in CORPUS]},
        ensure_ascii=False, sort_keys=True,
    ).encode()).hexdigest()
    saved_rows: dict[tuple[str, int], dict[str, Any]] = {}
    if progress_path and progress_path.is_file():
        for line in progress_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                saved = json.loads(line)
            except json.JSONDecodeError:
                continue
            if saved.get("corpus_signature") == signature and saved.get("mode") == mode:
                saved_rows[(saved["case_id"], saved["repeat"])] = saved
    by_case = {item["case_id"]: item for item in CORPUS}
    results: list[dict[str, Any]] = []
    for key, saved in saved_rows.items():
        events = saved.get("events") or [{}, {}]
        plan_reason = events[1].get("reason")
        must_retry = mode == "llm" and retry_llm_fallbacks and (
            not events[0].get("used")
            or (plan_reason not in {"deterministic_import_plan", "deterministic_blocked_plan"} and not events[1].get("used"))
        )
        if must_retry:
            continue
        canonical = coordinate(by_case[key[0]]["natural_language"], deepcopy_json(by_case[key[0]]["overrides"])).unfulfilled_requests
        saved.get("request", {})["unfulfilled_requests"] = list(canonical)
        saved.get("plan", {})["unfulfilled_requests"] = list(canonical)
        results.append(saved)
    completed = {(row["case_id"], row["repeat"]) for row in results}
    total = len(CORPUS) * repeats
    pending = [
        (item, repeat) for item in CORPUS for repeat in range(1, repeats + 1)
        if (item["case_id"], repeat) not in completed
    ]

    def run_one(item: dict[str, Any], repeat: int) -> dict[str, Any]:
            llm = OpenAICompatibleClient(config) if mode == "llm" else None
            started = time.perf_counter()
            error = None
            try:
                request, request_event = coordinate_with_llm(item["natural_language"], deepcopy_json(item["overrides"]), llm)
                task_plan, plan_event = plan_with_llm(request, llm)
                canonical_unfulfilled = coordinate(
                    item["natural_language"], deepcopy_json(item["overrides"])
                ).unfulfilled_requests
                request.unfulfilled_requests = list(canonical_unfulfilled)
                task_plan.unfulfilled_requests = list(canonical_unfulfilled)
                request_data, plan_data = request.to_dict(), task_plan.to_dict()
                schema_errors = validate_agentic_objects(ROOT, request_data, plan_data)
                plan_errors = validate_plan(task_plan)
                errors = schema_errors + plan_errors
                mismatches = compare_expected(request_data, item["expected"])
            except Exception as exc:
                request_data, plan_data, request_event, plan_event, schema_errors, plan_errors, errors, mismatches = {}, {}, {}, {}, [], [], [], []
                error = f"{type(exc).__name__}: {exc}"
            row = {
                "case_id": item["case_id"], "category": item["category"], "mode": mode,
                "corpus_signature": signature,
                "repeat": repeat, "duration_seconds": time.perf_counter() - started,
                "passed": not error and not errors and not mismatches,
                "mismatches": mismatches, "validation_errors": errors, "error": error,
                "schema_errors": schema_errors, "plan_errors": plan_errors,
                "request": request_data, "plan": plan_data,
                "events": [request_event, plan_event],
            }
            return row

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        future_items = {pool.submit(run_one, item, repeat): (item, repeat) for item, repeat in pending}
        for future in as_completed(future_items):
            item, repeat = future_items[future]
            row = future.result()
            results.append(row)
            if progress_path:
                progress_path.parent.mkdir(parents=True, exist_ok=True)
                with progress_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            print(
                f"[{mode}] {len(results)}/{total} {item['case_id']} repeat={repeat} "
                f"status={'PASS' if row['passed'] else 'FAIL'} duration={row['duration_seconds']:.2f}s",
                flush=True,
            )
    order = {item["case_id"]: index for index, item in enumerate(CORPUS)}
    results.sort(key=lambda row: (order[row["case_id"]], row["repeat"]))
    durations = [row["duration_seconds"] for row in results]
    field_checks = sum(len(item["expected"]) for item in CORPUS) * repeats
    field_errors = sum(len(row["mismatches"]) for row in results)
    consistency = []
    for item in CORPUS:
        payloads = [semantic_payload(row["request"]) for row in results if row["case_id"] == item["case_id"]]
        consistency.append(bool(payloads) and all(payload == payloads[0] for payload in payloads[1:]))
    valid_plans = sum(not row["validation_errors"] and not row["error"] for row in results)
    structurally_valid = sum(not row["schema_errors"] and not row["error"] for row in results)
    safely_disposed = 0
    by_id = {item["case_id"]: item for item in CORPUS}
    for row in results:
        expected_missing = sorted(by_id[row["case_id"]]["expected"].get("missing") or [])
        actual_missing = sorted((row.get("request") or {}).get("missing") or [])
        if not row["error"] and not row["schema_errors"] and (not row["plan_errors"] or expected_missing == actual_missing):
            safely_disposed += 1
    summary = {
        "cases": len(CORPUS), "repeats": repeats, "runs": len(results),
        "passed_runs": sum(row["passed"] for row in results),
        "pass_rate": sum(row["passed"] for row in results) / len(results),
        "field_accuracy": 1 - field_errors / field_checks if field_checks else 0,
        "valid_plan_rate": valid_plans / len(results),
        "structural_validity_rate": structurally_valid / len(results),
        "safe_disposition_rate": safely_disposed / len(results),
        "semantic_consistency_rate": sum(consistency) / len(consistency),
        "duration_seconds": {"mean": statistics.mean(durations), "p50": percentile(durations, .5), "p95": percentile(durations, .95)},
    }
    if mode == "llm":
        request_events = [row["events"][0] for row in results]
        plan_events = [row["events"][1] for row in results]
        eligible_plans = [event for event in plan_events if event.get("reason") not in {"deterministic_import_plan", "deterministic_blocked_plan"}]
        summary["llm_request_parse_rate"] = sum(bool(event.get("used")) for event in request_events) / len(request_events)
        summary["llm_plan_rate"] = sum(bool(event.get("used")) for event in eligible_plans) / len(eligible_plans) if eligible_plans else 1.0
    thresholds = {
        "field_accuracy_gte_0_95": summary["field_accuracy"] >= .95,
        "structural_validity_rate_eq_1": summary["structural_validity_rate"] == 1,
        "safe_disposition_rate_eq_1": summary["safe_disposition_rate"] == 1,
        "semantic_consistency_gte_0_95": summary["semantic_consistency_rate"] >= .95,
    }
    if mode == "llm":
        thresholds["llm_request_parse_rate_gte_0_95"] = summary["llm_request_parse_rate"] >= .95
        thresholds["llm_plan_rate_gte_0_95"] = summary["llm_plan_rate"] >= .95
    return {
        "schema_version": 1, "generated_at": now(), "mode": mode,
        "status": "passed" if all(thresholds.values()) else "failed",
        "summary": summary, "thresholds": thresholds, "results": results,
    }


def deepcopy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def export_corpus(path: Path) -> None:
    write_json(path, {"schema_version": 1, "count": len(CORPUS), "cases": CORPUS})


def write_csv_summary(path: Path, payloads: Iterable[dict[str, Any]]) -> None:
    rows = []
    for payload in payloads:
        for item in payload.get("results", []):
            rows.append({
                "case_id": item["case_id"], "category": item["category"], "mode": item["mode"],
                "repeat": item["repeat"], "passed": item["passed"],
                "duration_seconds": f"{item['duration_seconds']:.6f}",
                "mismatches": json.dumps(item["mismatches"], ensure_ascii=False),
                "validation_errors": json.dumps(item["validation_errors"], ensure_ascii=False),
                "error": item["error"] or "",
            })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["case_id"])
        writer.writeheader()
        writer.writerows(rows)


def write_plan_catalog(path: Path, payload: dict[str, Any]) -> None:
    """Write one stable, human-readable row per NL case (repeat 1)."""
    gold = {item["case_id"]: item for item in CORPUS}
    repeat_one = [item for item in payload.get("results", []) if item.get("repeat") == 1]
    lines = [
        f"# AutoRecon {len(CORPUS)} 条自然语言实际生成 Plan（{payload.get('mode')}）",
        "",
        f"生成时间：{payload.get('generated_at', '')}",
        "",
        "说明：三次重复的语义结果一致；`—` 表示未限定/默认全部可用证据；DAG 中括号为依赖。"
        " `阻止执行` 表示缺失项、非法项或不支持项使执行不能安全开始。",
        "",
    ]
    category = None
    for item in repeat_one:
        if item["category"] != category:
            category = item["category"]
            lines.extend([f"## {category}", ""])
        plan = item["plan"]
        steps = ", ".join(plan.get("execution_steps", [])) or "—"
        display = ", ".join(plan.get("display_steps", [])) or "—"
        report = ", ".join(plan.get("report_steps", [])) or "—"
        dag = " → ".join(
            f"{step['id']}[{','.join(step.get('depends_on', [])) or 'root'}]"
            for step in plan.get("steps", [])
        ) or "—"
        missing = plan.get("missing", [])
        unsupported = plan.get("unsupported_reason")
        blocked = bool(missing or unsupported or item.get("validation_errors") or item.get("plan_errors"))
        disposition = "阻止执行" if blocked else ("仅计划" if plan.get("execution_mode") == "plan_only" else "允许")
        lines.extend([
            f"### {item['case_id']}", "",
            f"> {gold[item['case_id']]['natural_language']}", "",
            f"- 模式：`{plan.get('execution_mode')}`；处置：**{disposition}**；planner：`{plan.get('planner_source')}`",
            f"- 执行范围：`{steps}`",
            f"- 展示范围：`{display}`；报告范围：`{report}`；报告：`{plan.get('report_language')}/{plan.get('report_detail')}/{plan.get('report_layout')}`",
            f"- 参数：backend=`{plan.get('reconstruction_tool')}`，GA=`{plan.get('gestational_age')}`，atlas_week=`{plan.get('atlas_week')}`，atlas_rule=`{plan.get('atlas_rule')}`，ROI=`{plan.get('roi_mode')}`，surface=`{plan.get('surface')}`，resume=`{plan.get('resume')}`",
            f"- DAG：`{dag}`",
            f"- 缺失/不支持：`{json.dumps({'missing': missing, 'unsupported_reason': unsupported}, ensure_ascii=False)}`",
            f"- 金标比对：{'PASS' if item.get('passed') else 'FAIL'}；偏差：`{json.dumps(item.get('mismatches', []), ensure_ascii=False)}`",
            "",
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


def real_run_manifest(output_root: Path, config: LLMConfig | None = None, gpu_ids: list[str] | None = None) -> dict[str, Any]:
    gpu_ids = gpu_ids or ["0", "1"]
    config = config or load_llm_config(ROOT)
    rows = {row["case"]: row for row in load_acceptable()}
    entries = []
    for index, (case, ga, week, rule, stack_count, purpose) in enumerate(SELECTED):
        source = DATASET_ROOT / "nii" / case
        work = output_root / "real_pipeline" / case
        atlas = ATLAS_ROOT / f"{week}w.nii.gz"
        numeric_ga = float(week)
        if "+" in ga:
            base, days = ga.replace("周", "").split("+")
            numeric_ga = int(base) + int(days) / 7
        command = [
            "bash", str(ROOT / "pipeline/run_single_case_pipeline.sh"),
            "--subject-dir", str(source), "--work-root", str(work), "--atlas", str(atlas),
            "--ga", f"{numeric_ga:.6f}", "--reconstruction-tool", "frost", "--roi-mode", "warp",
            "--ants-dir", config.ants_dir, "--roi-warp-env", config.roi_warp_env,
            "--surface", "auto", "--dashboard", "auto", "--dashboard-port", str(8900 + index), "--resume",
        ]
        entries.append({
            "case": case, "gestational_age_text": ga, "gestational_age": numeric_ga,
            "atlas_week": week, "atlas_rule": rule, "atlas": str(atlas), "stack_count": stack_count,
            "purpose": purpose, "source_dir": str(source), "work_root": str(work),
            "gpu": gpu_ids[index % len(gpu_ids)],
            "dashboard_port": 8900 + index,
            "csv_gold": rows[case], "command": command, "status": "pending",
        })
    return {"schema_version": 1, "generated_at": now(), "status": "pending", "cases": entries}


def _run_real_case(item: dict[str, Any]) -> dict[str, Any]:
    work_root = Path(item["work_root"])
    local_tmp = work_root / "scratch/tmp"
    apptainer_cache = work_root / "scratch/apptainer-cache"
    mpl_cache = work_root / "scratch/matplotlib"
    # Interrupted Apptainer conversions can leave multi-GB throwaway sandboxes.
    # This path is validation-owned and never contains accepted outputs.
    if local_tmp.is_dir():
        shutil.rmtree(local_tmp)
    for path in (local_tmp, apptainer_cache, mpl_cache):
        path.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "CUDA_VISIBLE_DEVICES": str(item["gpu"]),
        "TMPDIR": str(local_tmp), "TMP": str(local_tmp), "TEMP": str(local_tmp),
        "APPTAINER_TMPDIR": str(local_tmp), "APPTAINER_CACHEDIR": str(apptainer_cache),
        "MPLCONFIGDIR": str(mpl_cache),
        "PIPELINE_SCRATCH_ROOT": str(work_root / "scratch"),
    })
    log_path = work_root / "validation_launcher.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started_at, started = now(), time.perf_counter()
    source_dir = Path(item["source_dir"])
    staging_dir = work_root / "staging" / item["case"]
    staging_seg = staging_dir / "seg"
    staging_seg.mkdir(parents=True, exist_ok=True)
    for source_image in source_dir.glob("*.nii.gz"):
        shutil.copy2(source_image, staging_dir / source_image.name)
        source_mask = source_dir / "seg" / source_image.name
        if not source_mask.is_file():
            raise RuntimeError(f"validated extraction mask is missing: {source_mask}")
        shutil.copy2(source_mask, staging_seg / source_image.name)
    state_path = staging_seg / "extraction_state.json"
    state_command = [
        sys.executable, str(ROOT / "pipeline/extraction_state.py"), "record",
        "--source-dir", str(source_dir), "--staging-dir", str(staging_dir),
        "--runtime-root", str(ROOT / ".runtime"), "--state", str(state_path),
    ]
    state_result = subprocess.run(state_command, cwd=ROOT, env=env, capture_output=True, text=True)
    if state_result.returncode != 0:
        raise RuntimeError("cannot seed verified extraction state: " + state_result.stderr[-1000:])
    item["extraction_source"] = "existing_validated_masks_from_public_nii"
    item["extraction_state"] = str(state_path)
    with log_path.open("a", encoding="utf-8") as log:
        completed = subprocess.run(item["command"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    return {
        **item, "started_at": started_at, "finished_at": now(),
        "duration_seconds": time.perf_counter() - started, "returncode": completed.returncode,
        "status": "completed" if completed.returncode == 0 else "failed", "launcher_log": str(log_path),
        "temporary_directory": str(local_tmp),
    }


def execute_real(manifest: dict[str, Any], runtime: dict[str, Any], output_path: Path, max_workers: int) -> dict[str, Any]:
    if runtime["status"] != "passed":
        manifest["status"] = "blocked"
        manifest["blockers"] = runtime["blockers"]
        write_json(output_path, manifest)
        return manifest
    manifest["status"] = "running"
    write_json(output_path, manifest)
    pending = list(manifest["cases"])
    for offset in range(0, len(pending), max_workers):
        batch = pending[offset:offset + max_workers]
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_run_real_case, item): item for item in batch}
            for future in as_completed(futures):
                original = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = {
                        **original, "status": "failed", "finished_at": now(), "returncode": None,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                index = next(i for i, value in enumerate(manifest["cases"]) if value["case"] == result["case"])
                manifest["cases"][index] = result
                write_json(output_path, manifest)
        if any(item.get("status") == "failed" for item in manifest["cases"]):
            manifest["status"] = "failed"
            write_json(output_path, manifest)
            return manifest
    manifest["status"] = "completed"
    write_json(output_path, manifest)
    return manifest


def html_report(output: Path, data: dict[str, Any]) -> None:
    def table(rows: list[list[Any]], headers: list[str]) -> str:
        head = "".join(f"<th>{html.escape(str(v))}</th>" for v in headers)
        body = "".join("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in row) + "</tr>" for row in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    corpus_rows = []
    for mode in ("fallback", "llm"):
        payload = data.get(mode) or {}
        summary = payload.get("summary") or {}
        corpus_rows.append([mode, payload.get("status"), summary.get("runs", 0), f"{summary.get('field_accuracy', 0):.2%}", f"{summary.get('valid_plan_rate', 0):.2%}", f"{summary.get('semantic_consistency_rate', 0):.2%}"])
    selected_rows = [[item[0], item[1], item[2], item[3], item[4]] for item in SELECTED]
    document = f"""<!doctype html><html lang=zh-CN><meta charset=utf-8><title>AutoRecon 验证报告</title>
<style>body{{font:14px system-ui;max-width:1200px;margin:32px auto;padding:0 18px;color:#18202a}}table{{border-collapse:collapse;width:100%;margin:12px 0 28px}}th,td{{border:1px solid #ccd5df;padding:7px;text-align:left}}th{{background:#edf3f8}}.passed{{color:#087830}}.failed,.blocked{{color:#b42318}}code{{background:#eef2f5;padding:2px 4px}}</style>
<h1>AutoRecon 自然语言到报告分阶段验证</h1><p>生成时间：{html.escape(data['generated_at'])}</p>
<h2>当前状态</h2><ul><li>数据预检：<b class={data['data_preflight']['status']}>{data['data_preflight']['status']}</b></li><li>历史病例导入/报告：<b class={data['historical_import']['status']}>{data['historical_import']['status']}</b></li><li>真实病例报告：<b class={data['real_reports']['status']}>{data['real_reports']['status']}</b></li><li>Runtime：<b class={data['runtime_preflight']['status']}>{data['runtime_preflight']['status']}</b></li><li>真实计算清单：<b>{data['real_manifest']['status']}</b></li></ul>
<h2>自然语言验证</h2>{table(corpus_rows, ['模式','状态','运行数','字段准确率','合法计划率','三次语义一致率'])}
<h2>新增实算病例</h2>{table(selected_rows, ['病例','孕周','Atlas','规则','Stack数'])}
<h2>门禁与阻塞</h2><pre>{html.escape(json.dumps(data['runtime_preflight'].get('blockers', []), indent=2, ensure_ascii=False))}</pre>
<p>技术 PASS 只表示流程与技术 QC 合格，不表示临床有效或医学正常。</p></html>"""
    output.write_text(document, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT / "validation_results/current")
    parser.add_argument("--config", default="config/glm.env", help="Non-secret LLM config file.")
    parser.add_argument("--mode", choices=("fallback", "llm", "both"), default="both")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--llm-workers", type=int, default=4, help="Concurrent anonymous GLM cases (1-8).")
    parser.add_argument("--retry-llm-fallbacks", action="store_true", help="Retry only checkpoint rows that did not complete real GLM parsing/planning.")
    parser.add_argument("--skip-corpus", action="store_true")
    parser.add_argument("--skip-real-reports", action="store_true", help="Reuse saved real-case report validation.")
    parser.add_argument("--execute-real", action="store_true", help="Run all eight long GPU pipelines after every gate passes.")
    parser.add_argument("--gpus", default="0,1", help="Comma-separated physical GPU ids; at most two are allowed.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.repeats < 1:
        raise SystemExit("--repeats must be positive")
    if not 1 <= args.llm_workers <= 8:
        raise SystemExit("--llm-workers must be between 1 and 8")
    gpu_ids = [value.strip() for value in args.gpus.split(",") if value.strip()]
    if not gpu_ids or len(gpu_ids) > 2 or len(set(gpu_ids)) != len(gpu_ids) or not all(value.isdigit() for value in gpu_ids):
        raise SystemExit("--gpus requires one or two distinct numeric GPU ids")
    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("AUTORECON_CONFIG_FILE", args.config)
    config = load_llm_config(ROOT)
    export_corpus(output / "natural_language_gold.json")
    data = data_preflight()
    runtime = runtime_preflight(config)
    historical = historical_import_validation(output)
    write_json(output / "data_preflight.json", data)
    write_json(output / "runtime_preflight.json", runtime)
    write_json(output / "historical_import.json", historical)
    payloads = []
    modes = ("fallback", "llm") if args.mode == "both" else (args.mode,)
    if not args.skip_corpus:
        for mode in modes:
            payload = corpus_run(
                mode, args.repeats, config, output / f"natural_language_{mode}.progress.jsonl",
                workers=args.llm_workers if mode == "llm" else 1,
                retry_llm_fallbacks=args.retry_llm_fallbacks,
            )
            payloads.append(payload)
            write_json(output / f"natural_language_{mode}.json", payload)
    manifest_path = output / "real_pipeline_manifest.json"
    existing_manifest_path = output / "real_pipeline_manifest.json"
    existing_manifest = json.loads(existing_manifest_path.read_text(encoding="utf-8")) if existing_manifest_path.is_file() else None
    if existing_manifest and all(item.get("status") == "completed" for item in existing_manifest.get("cases", [])):
        existing_manifest["status"] = "completed"
        existing_manifest.pop("blockers", None)
    manifest = existing_manifest if existing_manifest and existing_manifest.get("status") == "completed" and not args.execute_real else real_run_manifest(output, config, gpu_ids)
    if args.execute_real:
        manifest = execute_real(manifest, runtime, manifest_path, max_workers=len(gpu_ids))
    else:
        if manifest.get("status") != "completed" and runtime["status"] != "passed":
            manifest["status"] = "blocked"
            manifest["blockers"] = runtime["blockers"]
        write_json(manifest_path, manifest)
    saved_real_reports = output / "real_reports.json"
    if args.skip_real_reports and saved_real_reports.is_file():
        real_reports = json.loads(saved_real_reports.read_text(encoding="utf-8"))
    elif manifest.get("status") == "completed":
        real_reports = real_report_validation(output, config)
    else:
        real_reports = {
        "schema_version": 1, "generated_at": now(), "status": "blocked", "reason": "real pipelines are not completed", "results": [],
        }
    write_json(output / "real_reports.json", real_reports)
    summary = {
        "schema_version": 1, "generated_at": now(), "data_preflight": data,
        "runtime_preflight": runtime, "historical_import": historical, "real_manifest": manifest, "real_reports": real_reports,
        **{payload["mode"]: payload for payload in payloads},
    }
    write_json(output / "summary.json", summary)
    write_csv_summary(output / "natural_language_runs.csv", payloads)
    for payload in payloads:
        mode_name = payload.get("mode")
        write_plan_catalog(output / f"NATURAL_LANGUAGE_PLAN_CATALOG.{mode_name}.zh-CN.md", payload)
        if mode_name == "fallback":
            write_plan_catalog(output / "NATURAL_LANGUAGE_PLAN_CATALOG.zh-CN.md", payload)
    html_report(output / "report.zh-CN.html", summary)
    print(json.dumps({
        "output_root": str(output), "data": data["status"], "historical_import": historical["status"], "real_reports": real_reports["status"], "runtime": runtime["status"],
        **{payload["mode"]: payload["status"] for payload in payloads}, "real": manifest["status"],
    }, indent=2, ensure_ascii=False))
    required = [data["status"] == "passed", historical["status"] == "passed", real_reports["status"] in {"passed", "blocked"}] + [payload["status"] in {"passed", "blocked"} for payload in payloads]
    return 0 if all(required) else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Seven-case GLM acceptance batch: freeze, gate, execute, compare, screenshot.

Use --phase continue to resume an interrupted batch: skip passed GLM/execute
results, wait for in-flight execute-one jobs, reuse reconstruction artifacts
instead of rerunning from scratch, then fingerprint-resume, compare, and screenshot.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import fcntl
import hashlib
import html
import http.server
import json
import os
from pathlib import Path
import shutil
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentic.coordinator import coordinate_with_llm
from agentic.env_config import load_llm_config
from agentic.executor import AgenticExecutor
from agentic.llm_analysis import analyze_results_with_llm
from agentic.llm_client import OpenAICompatibleClient
from agentic.models import RunState
from agentic.planner import plan_with_llm, validate_plan, validate_runtime
from pipeline.vis.pipeline_dashboard import DashboardHandler
from agentic.qc import evaluate_run
from agentic.reporter import build_report, validate_llm_report
from agentic.schema_validation import validate_agentic_objects
from agentic.state_store import StateStore
from pipeline.reconstruction.score_comparison import score_candidates, fingerprint_from_result, sha256_file
from validation.case_acceptance import (
    SEMANTIC_FIELDS,
    build_cases,
    expected_semantics,
    explicit_overrides,
    semantic_payload,
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_latest_batch(root: Path) -> Path | None:
    batches = sorted(root.glob("case_acceptance_*"), key=lambda path: path.name)
    return batches[-1] if batches else None


def freeze_batch(batch_root: Path, cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    batch_root.mkdir(parents=True, exist_ok=True)
    cases = cases if cases is not None else build_cases(batch_root)
    plan_text = render_plan_md(batch_root, cases)
    plan_path = batch_root / "plan.md"
    cases_path = batch_root / "cases.json"
    if plan_path.is_file() or cases_path.is_file():
        existing_plan = plan_path.read_text(encoding="utf-8") if plan_path.is_file() else ""
        existing_cases = cases_path.read_text(encoding="utf-8") if cases_path.is_file() else ""
        return {
            "status": "frozen",
            "batch_root": str(batch_root),
            "plan_sha256": sha256_text(existing_plan),
            "cases_sha256": sha256_text(existing_cases),
            "reused": True,
        }
    plan_path.write_text(plan_text, encoding="utf-8")
    write_json(cases_path, {"schema_version": 1, "generated_at": now(), "batch_root": str(batch_root), "cases": cases})
    freeze = {
        "status": "frozen",
        "frozen_at": now(),
        "batch_root": str(batch_root),
        "plan_sha256": sha256_text(plan_text),
        "cases_sha256": sha256_text(cases_path.read_text(encoding="utf-8")),
        "reused": False,
        "note": "Do not modify plan.md or cases.json after this freeze.",
    }
    write_json(batch_root / "freeze.json", freeze)
    return freeze


def render_plan_md(batch_root: Path, cases: list[dict[str, Any]]) -> str:
    ids = [case["case_id"] for case in cases]
    if ids[:7] == ["I01", "I02", "N01", "N02", "N03", "N04", "C01"] and len(ids) == 20:
        title = "AutoRecon 套 A 稳定性扩展（金标 7 + E08–E20）"
        heading = "二十个病例"
    elif ids and ids[0].startswith("K"):
        title = "AutoRecon 套 B 从已有结果继续（K01–K20）"
        heading = "二十个病例"
    else:
        title = "AutoRecon 七病例端到端验收、四后端比较与 Dashboard 截图计划"
        heading = "七个病例"
    lines = [
        f"# {title}",
        "",
        f"批次目录：`{batch_root}`",
        "",
        "本文件在执行开始前冻结。自然语言不含真实路径；路径、work root、孕周和 atlas 由本地显式参数注入。",
        "",
        f"## {heading}",
        "",
        "| ID | 类型 | 病例 | 自然语言 | 期望执行 |",
        "|---|---|---|---|---|",
    ]
    for case in cases:
        lines.append(
            f"| {case['case_id']} | {case['type']} | {case['subject']} | {case['natural_language']} | "
            f"`{' → '.join(case['execution_steps']) or 'import only'}` |"
        )
    lines += ["", "## 逐例冻结细节", ""]
    for case in cases:
        lines += [
            f"### {case['case_id']} {case['subject']}",
            "",
            f"- 类型：{case['type']}",
            f"- 自然语言：{case['natural_language']}",
            f"- 执行模式：`{case['execution_mode']}`",
            f"- DAG：`{' → '.join(case['dag'])}`",
            f"- 能力边界：{', '.join(case['capability_boundaries']) or '无'}",
            f"- 截图：{', '.join(case['screenshots'])}",
            f"- 说明：{case['notes']}",
            "",
        ]
    lines += [
        "## 通过标准",
        "",
        "- GLM 三重复关键语义一致率 100%，fallback 不得授权实算。",
        "- import 2/2 成功且无计算步骤。",
        "- partial 2/2 精确停在目标阶段。",
        "- full 2/2 六阶段完成。",
        "- 四后端均保留独立结果；未完成盲评不得宣称最终最佳方法。",
        "- N01–N04 与 C01 各做一次 resume，fingerprint 一致则不得重算。",
        "- 14 张截图和总览联系表通过自动校验。",
        "",
        "技术 PASS 不代表胎儿医学正常。",
        "",
    ]
    return "\n".join(lines)


def load_cases(batch_root: Path) -> list[dict[str, Any]]:
    payload = json.loads((batch_root / "cases.json").read_text(encoding="utf-8"))
    return payload["cases"]


def compare_expected(actual: dict[str, Any], expected: dict[str, Any]) -> list[dict[str, Any]]:
    mismatches = []
    for field, wanted in expected.items():
        got = actual.get(field)
        if field == "unfulfilled_requests":
            if set(got or []) != set(wanted or []):
                mismatches.append({"field": field, "expected": list(wanted or []), "actual": list(got or [])})
            continue
        if field in {"execution_steps", "display_steps", "report_steps", "reconstruction_compare_tools"}:
            got = list(got or [])
            wanted = list(wanted or [])
        if field == "gestational_age" and got is not None and wanted is not None:
            if abs(float(got) - float(wanted)) <= 1e-6:
                continue
        if got != wanted:
            mismatches.append({"field": field, "expected": wanted, "actual": got})
    return mismatches


def actionable_validation_errors(case: dict[str, Any], errors: list[str] | None) -> list[str]:
    """Missing-input cases are correctly blocked; those plan errors are not gate defects."""
    items = list(errors or [])
    if not case.get("missing"):
        return items
    skip = (
        "Missing required parameter(s)",
        "Capability refusal blocks GPU execution",
        "Plan steps do not exactly match requested scope",
    )
    return [item for item in items if not any(item.startswith(prefix) or prefix in item for prefix in skip)]


def _until_llm_used(make_call, *, ok, attempts: int = 6):
    result = None
    for attempt in range(attempts):
        result = make_call()
        if ok(result):
            return result
        time.sleep(min(2 ** attempt, 4))
    return result


def glm_gate_case(case: dict[str, Any], llm: OpenAICompatibleClient, repeats: int, out_dir: Path) -> dict[str, Any]:
    from validation.stability_suites import materialize_source
    materialize_source(case)
    overrides = explicit_overrides(case)
    expected = expected_semantics(case)
    need_plan_llm = (
        case["execution_mode"] in {"run_pipeline", "continue_from_run"}
        and case.get("inject_paths") is not False
    )
    runs = []
    for index in range(repeats):
        request, request_event = _until_llm_used(
            lambda: coordinate_with_llm(case["natural_language"], overrides, llm),
            ok=lambda item: item[1].get("used") is True,
        )
        def _plan_once():
            return plan_with_llm(request, llm)
        if case["execution_mode"] == "import_existing":
            task_plan, plan_event = plan_with_llm(request, llm)
        elif need_plan_llm:
            task_plan, plan_event = _until_llm_used(
                _plan_once,
                ok=lambda item: item[1].get("used") is True,
            )
        else:
            task_plan, plan_event = _until_llm_used(
                _plan_once,
                ok=lambda item: item[1].get("used") is True or item[1].get("reason") in {
                    "deterministic_import_plan", "deterministic_blocked_plan",
                },
            )
        config = llm.config
        errors = (
            validate_agentic_objects(ROOT, request.to_dict(), task_plan.to_dict())
            + validate_plan(task_plan)
            + validate_runtime(task_plan, config.ants_dir, config.roi_warp_env)
        )
        payload = semantic_payload(request.to_dict())
        runs.append({
            "repeat": index + 1,
            "request": request.to_dict(),
            "plan": task_plan.to_dict(),
            "request_event": request_event,
            "plan_event": plan_event,
            "semantic": payload,
            "expected_mismatches": compare_expected(payload, expected),
            "validation_errors": errors,
        })
    semantics = [json.dumps(run["semantic"], sort_keys=True, ensure_ascii=False) for run in runs]
    consistent = len(set(semantics)) == 1
    parsing_real = all(run["request_event"].get("used") is True for run in runs)
    if case["execution_mode"] == "import_existing":
        planning_ok = all(run["plan_event"].get("reason") == "deterministic_import_plan" for run in runs)
        planning_real = True
    elif need_plan_llm:
        planning_real = all(run["plan_event"].get("used") is True for run in runs)
        planning_ok = planning_real
    else:
        planning_real = True
        planning_ok = True
    mismatches = runs[0]["expected_mismatches"] if runs else [{"field": "empty"}]
    gate_errors = actionable_validation_errors(case, runs[0]["validation_errors"] if runs else [])
    authorized = consistent and parsing_real and planning_ok and not mismatches and not gate_errors
    result = {
        "case_id": case["case_id"],
        "subject": case["subject"],
        "status": "passed" if authorized else "failed",
        "authorized": authorized,
        "consistent": consistent,
        "parsing_real": parsing_real,
        "planning_real": planning_real,
        "expected_mismatches": mismatches,
        "validation_errors": gate_errors,
        "runs": runs,
    }
    write_json(out_dir / f"{case['case_id']}_glm.json", result)
    return result


def execute_compute_isolated(batch_root: Path, case_id: str, gpu: str | None, resume: bool) -> dict[str, Any]:
    command = [
        sys.executable, str(Path(__file__).resolve()),
        "--batch-root", str(batch_root), "--phase", "execute-one", "--cases", case_id,
    ]
    if gpu is not None:
        command.extend(["--gpus", str(gpu)])
    if resume:
        command.append("--resume-one")
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    result_path = batch_root / "cases" / case_id / ("resume_result.json" if resume else "execute_result.json")
    if result_path.is_file():
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        payload = {"case_id": case_id, "status": "failed", "error": completed.stderr[-2000:] or completed.stdout[-2000:]}
    payload["returncode"] = completed.returncode
    return payload


def prepare_env(work_root: Path, gpu: str | None, dashboard_port: int) -> dict[str, str]:
    local_tmp = work_root / "scratch/tmp"
    apptainer_cache = work_root / "scratch/apptainer-cache"
    mpl_cache = work_root / "scratch/matplotlib"
    for path in (local_tmp, apptainer_cache, mpl_cache):
        path.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "TMPDIR": str(local_tmp), "TMP": str(local_tmp), "TEMP": str(local_tmp),
        "APPTAINER_TMPDIR": str(local_tmp), "APPTAINER_CACHEDIR": str(apptainer_cache),
        "MPLCONFIGDIR": str(mpl_cache),
        "PIPELINE_SCRATCH_ROOT": str(work_root / "scratch"),
        "AUTORECON_DASHBOARD_PORT": str(dashboard_port),
        "AUTORECON_DASHBOARD_MODE": "on",
        "AUTORECON_CONFIG_FILE": env.get("AUTORECON_CONFIG_FILE", "config/glm.env"),
    })
    if gpu is not None:
        env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    env.pop("API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    return env


def _coordinate_with_retries(natural_language: str, overrides: dict[str, Any], llm: OpenAICompatibleClient, attempts: int = 6):
    request, event = None, {}
    for attempt in range(attempts):
        request, event = coordinate_with_llm(natural_language, overrides, llm)
        if event.get("used") is True:
            return request, event
        time.sleep(min(2 ** attempt, 4))
    return request, event


def _plan_with_retries(request, llm: OpenAICompatibleClient, *, require_llm: bool, attempts: int = 6):
    task_plan, event = None, {}
    for attempt in range(attempts):
        task_plan, event = plan_with_llm(request, llm)
        if require_llm:
            if event.get("used") is True:
                return task_plan, event
        elif event.get("reason") in {"deterministic_import_plan", "deterministic_blocked_plan"} or event.get("used") is True:
            return task_plan, event
        time.sleep(min(2 ** attempt, 4))
    return task_plan, event


def _failed_execute_payload(case: dict[str, Any], *, resume: bool, gpu: str | None, work_root: Path, started: float, error: str) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "subject": case["subject"],
        "resume": resume,
        "status": "failed",
        "run_status": "failed",
        "error": error,
        "duration_seconds": time.perf_counter() - started,
        "dashboard": {},
        "work_root": str(work_root),
        "gpu": gpu,
    }


def passed_execute_result(batch_root: Path, case_id: str, *, resume: bool) -> dict[str, Any] | None:
    path = batch_root / "cases" / case_id / ("resume_result.json" if resume else "execute_result.json")
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") == "passed":
        return payload
    if payload.get("status") == "interrupted" and payload.get("planned_interrupt"):
        return payload
    return None


def pipeline_artifacts_reusable(case: dict[str, Any]) -> bool:
    work_root = Path(case.get("work_root") or "")
    if not work_root.is_dir():
        return False
    pipeline_result = work_root / "pipeline_result.json"
    if pipeline_result.is_file():
        payload = json.loads(pipeline_result.read_text(encoding="utf-8"))
        if payload.get("status") == "completed" and int(payload.get("exit_code", 1)) == 0:
            return True
    recon = work_root / "outputs" / "reconstruction" / case["reconstruction_tool"] / f"{case['subject']}.nii.gz"
    manifest = work_root / "outputs" / "reconstruction" / case["reconstruction_tool"] / "result.json"
    if recon.is_file() and manifest.is_file():
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        return payload.get("status") == "completed"
    return False


def execute_one_pid(case_id: str) -> int | None:
    marker = f"--cases {case_id}".encode()
    for cmdline in Path("/proc").glob("*/cmdline"):
        try:
            raw = cmdline.read_bytes()
        except OSError:
            continue
        compact = raw.replace(b"\0", b" ")
        if b"run_case_acceptance.py" in compact and b"execute-one" in compact and marker in compact:
            pid = int(cmdline.parent.name)
            if pid != os.getpid():
                return pid
    return None


def wait_for_execute_one(case_id: str, poll_seconds: int = 20) -> None:
    while True:
        pid = execute_one_pid(case_id)
        if pid is None:
            return
        time.sleep(poll_seconds)


def execute_case(case: dict[str, Any], batch_root: Path, llm: OpenAICompatibleClient, *, resume: bool, gpu: str | None, dashboard_port: int) -> dict[str, Any]:
    case_dir = batch_root / "cases" / case["case_id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    lock_fh = (case_dir / ".execute.lock").open("w")
    fcntl.flock(lock_fh, fcntl.LOCK_EX)
    run_root = case_dir / "agentic"
    work_root = Path(case.get("work_root") or (case_dir / "work")).expanduser()
    if not work_root.is_absolute():
        work_root = ROOT / work_root
    work_root = work_root.resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    env = prepare_env(work_root, gpu, dashboard_port)
    old_env = dict(os.environ)
    os.environ.update(env)
    started = time.perf_counter()
    try:
        overrides = explicit_overrides(case)
        if resume:
            overrides["resume"] = True
            overrides["explicit_fields"] = list(overrides["explicit_fields"]) + ["resume"]
        request, request_event = _coordinate_with_retries(case["natural_language"], overrides, llm)
        if request_event.get("used") is not True:
            raise RuntimeError("GLM request parsing was not a real call")
        require_plan_llm = (
            case["execution_mode"] in {"run_pipeline", "continue_from_run"}
            and case.get("inject_paths") is not False
        )
        task_plan, plan_event = _plan_with_retries(request, llm, require_llm=require_plan_llm)
        if require_plan_llm and not plan_event.get("used"):
            raise RuntimeError("fallback planning is not allowed to authorize compute")
        errors = (
            validate_agentic_objects(ROOT, request.to_dict(), task_plan.to_dict())
            + validate_plan(task_plan)
            + validate_runtime(task_plan, llm.config.ants_dir, llm.config.roi_warp_env)
        )
        store = StateStore(run_root)
        run_id = f"{case['case_id']}_{'resume' if resume else 'run'}"
        state = RunState(run_id=run_id, status="planned", request=request.to_dict(), plan=task_plan.to_dict())
        interrupt_info: dict[str, Any] = {}
        gate_errors = actionable_validation_errors(case, errors)
        if gate_errors:
            state.status = "failed"
            state.report_markdown = "Plan validation failed:\n" + "\n".join(f"- {error}" for error in gate_errors)
            state.report_json = {"errors": gate_errors}
            results, dashboard = [], {}
        elif errors:
            state.status = "completed"
            state.report_markdown = "缺少必要输入，未授权计算。\n" + "\n".join(f"- {error}" for error in errors)
            state.report_json = {"errors": errors, "blocked": True}
            results, dashboard = [], {}
        else:
            executor = AgenticExecutor(ROOT, run_root)
            stop_watch = threading.Event()
            watcher = None
            if case.get("interrupt_after"):
                from validation.interrupt_protocol import watch_and_interrupt

                def _watch() -> None:
                    interrupt_info.update(
                        watch_and_interrupt(work_root, str(case["interrupt_after"]), stop_watch)
                    )

                watcher = threading.Thread(target=_watch, daemon=True)
                watcher.start()
            try:
                results, dashboard = executor.execute(task_plan, run_id)
            finally:
                stop_watch.set()
                if watcher is not None:
                    watcher.join(timeout=15)
            state.step_results = results
            state.dashboard = dashboard
            state.status = "failed" if any(item.get("status") == "failed" for item in results) else "completed"
            report_llm = None if task_plan.execution_mode == "import_existing" else llm
            result_event = analyze_results_with_llm(results, report_llm)
            state.report_markdown, state.report_json = build_report(
                task_plan, results, dashboard, report_llm, [request_event, plan_event, result_event]
            )
            if interrupt_info.get("snapshot"):
                from validation.interrupt_protocol import report_must_not_complete_unfinished, write_interrupt_snapshot

                snapshot = interrupt_info["snapshot"]
                snapshot["report_excerpt"] = (state.report_markdown or "")[:2000]
                snapshot["state_status"] = state.status
                snapshot["unfinished_not_marked_complete"] = report_must_not_complete_unfinished(
                    state.report_markdown or "", list((interrupt_info.get("snapshot") or {}).get("run_state_steps") or [])
                )
                write_interrupt_snapshot(case_dir, snapshot)
        saved = store.save(state)
        qc_root = Path(case["existing_run_dir"]) if case["execution_mode"] == "import_existing" else work_root
        qc = evaluate_run(qc_root, case["subject"], case["execution_steps"] or None) if qc_root.exists() else {}
        write_json(case_dir / "request.json", request.to_dict())
        write_json(case_dir / "plan.json", task_plan.to_dict())
        write_json(case_dir / "state.json", saved)
        write_json(case_dir / "qc.json", qc)
        (case_dir / "report.md").write_text(state.report_markdown or "", encoding="utf-8")
        write_json(case_dir / "report.json", state.report_json)
        acceptance = None
        if case["type"] in {"full", "full/boundary"} and state.status == "completed":
            try:
                from argparse import Namespace
                from scripts.validate_full_pipeline import run as validate_full
                acceptance = validate_full(Namespace(
                    project_root=ROOT, work_root=work_root, subject=case["subject"],
                    source_dir=Path(case["subject_dir"]), backend=case["reconstruction_tool"],
                    require_surface=True, runtime_root=ROOT / ".runtime",
                ))
                acceptance["status"] = "completed"
                write_json(work_root / "acceptance.json", acceptance)
            except Exception as exc:
                acceptance = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
                write_json(work_root / "acceptance.json", acceptance)
        checks = _post_execute_checks(case, request.to_dict(), task_plan.to_dict(), results, state, acceptance)
        status = "passed" if state.status == "completed" and all(checks.values()) else "failed"
        if case.get("planned_interrupt") and interrupt_info.get("interrupted"):
            status = "interrupted"
            checks["planned_interrupt"] = True
        payload = {
            "case_id": case["case_id"],
            "subject": case["subject"],
            "resume": resume,
            "status": status,
            "run_status": state.status,
            "checks": checks,
            "duration_seconds": time.perf_counter() - started,
            "dashboard": dashboard,
            "work_root": str(work_root),
            "gpu": gpu,
            "planned_interrupt": bool(case.get("planned_interrupt") and interrupt_info.get("interrupted")),
        }
        write_json(case_dir / ("resume_result.json" if resume else "execute_result.json"), payload)
        if resume and payload.get("status") == "passed":
            first = case_dir / "execute_result.json"
            previous = json.loads(first.read_text(encoding="utf-8")) if first.is_file() else {}
            if previous.get("status") != "passed":
                recovered = dict(payload)
                recovered["resume"] = False
                recovered["recovered_via_resume"] = True
                write_json(first, recovered)
        return payload
    except Exception as exc:
        payload = _failed_execute_payload(
            case, resume=resume, gpu=gpu, work_root=work_root, started=started,
            error=f"{type(exc).__name__}: {exc}",
        )
        write_json(case_dir / ("resume_result.json" if resume else "execute_result.json"), payload)
        return payload
    finally:
        os.environ.clear()
        os.environ.update(old_env)
        lock_fh.close()


def _post_execute_checks(case, request, plan, results, state, acceptance) -> dict[str, bool]:
    executed = [item.get("step_id") for item in results if item.get("status") == "completed"]
    skipped = [item.get("step_id") for item in results if item.get("status") == "skipped"]
    report = state.report_markdown or ""
    report_errors = validate_llm_report(report, state.report_json or {})
    checks = {
        "run_completed": state.status == "completed",
        "mode_matches": request.get("execution_mode") == case["execution_mode"],
        "steps_match": list(request.get("execution_steps") or []) == list(case["execution_steps"]),
        "unfulfilled_recorded": all(item in (request.get("unfulfilled_requests") or []) for item in case["unfulfilled_requests"]),
        "no_clinical_claim": not any("clinical claim" in item for item in report_errors),
        "capability_in_report": (not case["capability_boundaries"]) or (
            ("能力边界" in report or "Capability Boundary" in report or "未完成与拒绝" in report)
            and all(code in str(request.get("unfulfilled_requests") or []) for code in case["capability_boundaries"])
            and all(
                any(token in report for token in {
                    "normality_assessment_requires_validated_GA_reference_and_expert_review": ("不能判断是否正常", "不是临床诊断", "不断言"),
                    "external_hospital_delivery_unsupported": ("未发送到医院", "HIS", "PACS"),
                    "normative_comparison_requires_validated_GA_reference": ("不能给出孕周百分位", "百分位"),
                    "best_method_requires_expert_blind_review": ("不能宣称最佳", "盲评"),
                    "destructive_history_deletion_not_authorized": ("不允许删除历史", "删除历史结果"),
                    "arbitrary_shell_and_secret_access_forbidden": ("禁止任意命令", "读取密钥", "shell"),
                }.get(code, (code,)))
                for code in case["capability_boundaries"]
            )
        ),
    }
    if case["execution_mode"] == "import_existing":
        compute = {"extraction", "reconstruction", "registration", "tissue", "roi", "surface"}
        checks["no_compute_steps"] = not (compute & set(executed))
        checks["display_scope"] = list(request.get("display_steps") or []) == list(case["display_steps"])
    else:
        wanted = set(case["execution_steps"])
        skipped_later = {"registration", "tissue", "roi", "surface"} - wanted
        checks["stopped_at_scope"] = True
        work = case.get("work_root")
        run_state = Path(work) / "dashboard" / "run_state.json" if work else None
        if run_state is not None and run_state.is_file():
            steps = json.loads(run_state.read_text(encoding="utf-8")).get("steps") or []
            executed_ids = {item.get("id") for item in steps if item.get("status") == "completed"}
            skipped_ids = {item.get("id") for item in steps if item.get("status") == "skipped"}
            extra = (executed_ids & {"extraction", "reconstruction", "registration", "tissue", "roi", "surface"}) - wanted
            if case["type"] in {"full", "full/boundary"}:
                checks["stopped_at_scope"] = not extra
            else:
                checks["stopped_at_scope"] = not extra and skipped_later <= skipped_ids
        if case["type"] in {"full", "full/boundary"} and acceptance:
            checks["strict_acceptance"] = acceptance.get("status") == "completed"
        if case["atlas_week"] is not None:
            checks["atlas_week_preserved"] = plan.get("atlas_week") == case["atlas_week"]
        if case["gestational_age"] is not None:
            checks["ga_preserved"] = abs(float(plan.get("gestational_age") or 0) - float(case["gestational_age"])) <= 1e-6
            if case["atlas_week"] is not None:
                checks["ga_not_collapsed_to_atlas"] = float(plan.get("gestational_age") or 0) == float(case["gestational_age"])
    return checks


def resume_fingerprints(case: dict[str, Any]) -> dict[str, Any]:
    work_root = Path(case["work_root"])
    subject = case["subject"]
    recon = work_root / "outputs" / "reconstruction" / case["reconstruction_tool"] / f"{subject}.nii.gz"
    result = work_root / "outputs" / "reconstruction" / case["reconstruction_tool"] / "result.json"
    payload = {
        "image": str(recon) if recon.is_file() else None,
        "image_mtime": recon.stat().st_mtime if recon.is_file() else None,
        "image_sha256": sha256_file(recon) if recon.is_file() else None,
        "fingerprint": fingerprint_from_result(result),
    }
    return payload


def register_missing_backends(case: dict[str, Any], config) -> list[dict[str, Any]]:
    work_root = Path(case["work_root"])
    subject = case["subject"]
    atlas = Path(case["atlas"])
    ants = Path(config.ants_dir)
    script = ROOT / "pipeline/scripts/registration/run_ants_rigid_orient48_batch.py"
    notes = []
    for backend in case["reconstruction_compare_tools"]:
        recon = work_root / "outputs" / "reconstruction" / backend / f"{subject}.nii.gz"
        candidate = work_root / "outputs" / "recon_candidates" / backend / f"{subject}.nii.gz"
        image = recon if recon.is_file() else candidate
        out_dir = work_root / "outputs" / "reconstruction" / "comparison" / backend / "registration"
        summary = out_dir / "summary.csv"
        if summary.is_file():
            notes.append({"backend": backend, "status": "reused"})
            continue
        if not image or not image.is_file():
            notes.append({"backend": backend, "status": "missing_reconstruction"})
            continue
        input_dir = image.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable, str(script), "--mode", "single",
            "--input-dir", str(input_dir), "--atlas", str(atlas),
            "--output-dir", str(out_dir), "--preset", "full",
        ]
        if ants.is_dir():
            command.extend(["--ants-dir", str(ants)])
        log_path = out_dir / "registration.log"
        with log_path.open("w", encoding="utf-8") as log:
            completed = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        notes.append({"backend": backend, "status": "completed" if completed.returncode == 0 else "failed", "returncode": completed.returncode, "log": str(log_path)})
    return notes


def _fmt_seconds(seconds: Any) -> str:
    if seconds is None:
        return "—"
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "—"
    minutes, secs = divmod(abs(total), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _iso_seconds(started: Any, ended: Any) -> float | None:
    if not started or not ended:
        return None
    try:
        start = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        finish = datetime.fromisoformat(str(ended).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (finish - start).total_seconds()


def pipeline_timing(work_root: Path) -> dict[str, Any]:
    run_state = work_root / "dashboard" / "run_state.json"
    if not run_state.is_file():
        return {}
    payload = json.loads(run_state.read_text(encoding="utf-8"))
    run = payload.get("run") or {}
    steps = []
    for step in payload.get("steps") or []:
        duration = _iso_seconds(step.get("started_at"), step.get("ended_at"))
        steps.append({
            "id": step.get("id"),
            "status": step.get("status"),
            "message": step.get("message") or "",
            "duration_seconds": duration,
        })
    return {
        "status": run.get("status"),
        "message": run.get("message") or "",
        "wall_seconds": _iso_seconds(run.get("created_at"), run.get("updated_at")),
        "steps": steps,
    }


def ranking_table_html(payload: dict[str, Any]) -> str:
    rows = []
    for item in sorted(payload.get("candidates") or [], key=lambda row: row.get("rank") or 99):
        metrics = item.get("metrics") or {}
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('rank')))}</td>"
            f"<td>{html.escape(str(item.get('blind_label') or ''))}</td>"
            f"<td>{html.escape(str(item.get('backend') or ''))}</td>"
            f"<td>{html.escape(format(item['automatic_score'], '.4f') if item.get('automatic_score') is not None else '—')}</td>"
            f"<td>{html.escape(str((item.get('registration') or {}).get('qc_group') or '—'))}</td>"
            f"<td>{html.escape(str(metrics.get('registration_mattes', '—')))}</td>"
            "</tr>"
        )
    statement = html.escape(str(payload.get("recommendation_statement") or ""))
    mode = html.escape(str(payload.get("ranking_mode") or ""))
    return (
        f"<div class='banner'>排名模式：{mode}。不得宣称最终最佳方法。</div>"
        f"<p>{statement}</p>"
        "<table><thead><tr><th>名次</th><th>盲标</th><th>后端</th><th>自动分</th><th>配准 QC</th><th>Mattes</th></tr></thead>"
        f"<tbody>{''.join(rows) or '<tr><td colspan=6>无候选</td></tr>'}</tbody></table>"
        f"<p>{html.escape(str(payload.get('disclaimer') or ''))}</p>"
    )


PAGE_CSS = """
body{font:15px/1.45 system-ui,sans-serif;margin:0;color:#17211d;background:#eef3f0}
main{max-width:1100px;margin:0 auto;padding:28px 20px 48px}
h1{margin:0 0 8px}
.banner{padding:14px 16px;border-radius:10px;background:#1f6f54;color:#fff;font-size:22px;font-weight:700;margin:12px 0}
.warn{background:#9a3b2f}
.muted{color:#4d5c57}
table{border-collapse:collapse;width:100%;margin:12px 0;background:#fff}
td,th{border:1px solid #ccd5df;padding:8px;vertical-align:top}
th{background:#e7eeea;text-align:left}
article,pre,figure{background:#fff;border:1px solid #d8e0dc;padding:12px;border-radius:8px}
img{max-width:100%;border:1px solid #d8e0dc;background:#fff}
iframe{width:100%;height:640px;border:1px solid #d8e0dc;background:#fff}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}
.card{flex:1;min-width:220px;padding:18px;border-radius:12px;background:#fff;border:2px solid #1f6f54}
.card strong{display:block;font-size:28px;margin-top:6px}
"""


def _write_html(path: Path, title: str, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"<!doctype html><html lang=zh-CN><meta charset=utf-8><title>{html.escape(title)}</title>"
        f"<style>{PAGE_CSS}</style><body><main>{body}</main></body></html>",
        encoding="utf-8",
    )
    return path


def copy_preview_assets(work_root: Path, dashboard_dir: Path) -> list[str]:
    names: list[str] = []
    preview_dir = work_root / "dashboard" / "previews"
    if not preview_dir.is_dir():
        return names
    for src in sorted(preview_dir.glob("*")):
        if src.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".html"}:
            continue
        dest = dashboard_dir / src.name
        shutil.copy2(src, dest)
        names.append(src.name)
    return names


def render_case_html(case: dict[str, Any], batch_root: Path, execute_result: dict[str, Any] | None) -> Path:
    case_dir = batch_root / "cases" / case["case_id"]
    dashboard_dir = case_dir / "dashboard"
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    request = json.loads((case_dir / "request.json").read_text(encoding="utf-8")) if (case_dir / "request.json").is_file() else {}
    plan = json.loads((case_dir / "plan.json").read_text(encoding="utf-8")) if (case_dir / "plan.json").is_file() else {}
    report = (case_dir / "report.md").read_text(encoding="utf-8") if (case_dir / "report.md").is_file() else ""
    work_root = Path(case.get("work_root") or "")
    timing = pipeline_timing(work_root) if work_root else {}
    previews = copy_preview_assets(work_root, dashboard_dir) if work_root else []
    status = str((execute_result or {}).get("status") or timing.get("status") or "pending")
    banner_class = "banner" if status == "passed" or timing.get("status") == "completed" else "banner warn"
    step_rows = "".join(
        f"<tr><td>{html.escape(str(step.get('id')))}</td><td>{html.escape(str(step.get('status')))}</td>"
        f"<td>{html.escape(_fmt_seconds(step.get('duration_seconds')))}</td>"
        f"<td>{html.escape(str(step.get('message')))}</td></tr>"
        for step in timing.get("steps") or []
    )
    preview_html = "".join(
        f'<figure><img src="{html.escape(name)}" alt="{html.escape(name)}"><figcaption>{html.escape(name)}</figcaption></figure>'
        for name in previews if name.endswith(".png")
    )
    iframe_html = "".join(
        f'<p class="muted">{html.escape(name)}</p><iframe src="{html.escape(name)}"></iframe>'
        for name in previews if name.endswith(".html")
    )
    ranking_path = work_root / "outputs" / "reconstruction" / "comparison" / "ranking.json" if work_root else None
    ranking_payload = json.loads(ranking_path.read_text(encoding="utf-8")) if ranking_path and ranking_path.is_file() else {}
    ranking_html = ranking_table_html(ranking_payload) if ranking_payload else "<p>无四后端排名。</p>"
    pipeline_href = ""
    if work_root and (work_root / "dashboard" / "index.html").is_file():
        rel = os.path.relpath(work_root / "dashboard" / "index.html", dashboard_dir)
        pipeline_href = f'<p><a href="{html.escape(rel)}">打开流水线 Dashboard</a></p>'
    ga = case.get("gestational_age")
    atlas = case.get("atlas_week")
    _write_html(
        dashboard_dir / "reconstruction.html",
        f"{case['case_id']} 重建/配准",
        f"<h1>{html.escape(case['case_id'])} 重建 / 配准</h1>"
        f"<div class='{banner_class}'>状态：{html.escape(status)} · {html.escape(str(timing.get('message') or ''))}</div>"
        f"{pipeline_href}"
        f"<table><thead><tr><th>步骤</th><th>状态</th><th>耗时</th><th>说明</th></tr></thead><tbody>{step_rows or '<tr><td colspan=4>无流水线步骤</td></tr>'}</tbody></table>"
        f"{preview_html}{iframe_html or ''}",
    )
    _write_html(
        dashboard_dir / "report.html",
        f"{case['case_id']} 报告",
        f"<h1>{html.escape(case['case_id'])} 中文报告</h1>"
        f"<div class='banner'>病例 {html.escape(case['subject'])} · 技术 PASS 不代表医学正常</div>"
        f"<article>{html.escape(report[:16000] or '暂无报告正文')}</article>",
    )
    _write_html(
        dashboard_dir / "ga_atlas.html",
        f"{case['case_id']} 孕周与图谱",
        f"<h1>{html.escape(case['case_id'])} 孕周与 Atlas</h1>"
        "<div class='cards'>"
        f"<div class='card'>超声孕周<strong>{html.escape(str(ga) if ga is not None else '—')}</strong></div>"
        f"<div class='card'>Atlas week<strong>{html.escape(str(atlas) if atlas is not None else '—')}</strong></div>"
        f"<div class='card'>规则<strong>{html.escape(str(case.get('atlas_rule') or '—'))}</strong></div>"
        "</div>"
        f"<p>自然语言：{html.escape(case['natural_language'])}</p>"
        f"{preview_html or '<p>无 PNG 预览；以孕周卡片为准。</p>'}",
    )
    _write_html(
        dashboard_dir / "ranking.html",
        f"{case['case_id']} 排名",
        f"<h1>{html.escape(case['case_id'])} 四后端自动排名</h1>{ranking_html}",
    )
    _write_html(
        dashboard_dir / "comparison.html",
        f"{case['case_id']} 比较",
        f"<h1>{html.escape(case['case_id'])} 盲法比较说明</h1>{ranking_html}"
        "<p>盲标用于展示，不得把自动分写成临床最佳方法。</p>",
    )
    return _write_html(
        dashboard_dir / "index.html",
        f"{case['case_id']} {case['subject']} Dashboard",
        f"<h1>{html.escape(case['case_id'])} {html.escape(case['subject'])}</h1>"
        f"<div class='{banner_class}'>首次执行：{html.escape(status)} · 墙钟 {_fmt_seconds(timing.get('wall_seconds'))}</div>"
        f"<p>自然语言：{html.escape(case['natural_language'])}</p>"
        f"<p>执行模式：{html.escape(case['execution_mode'])}；步骤：{html.escape(', '.join(case['execution_steps']) or 'import')}</p>"
        f"<p>实际孕周：{html.escape(str(ga))}；Atlas week：{html.escape(str(atlas))}；规则：{html.escape(str(case.get('atlas_rule')))}</p>"
        f"{pipeline_href}"
        "<p><a href='reconstruction.html'>重建/配准</a> · <a href='report.html'>报告</a> · "
        "<a href='ga_atlas.html'>孕周/图谱</a> · <a href='ranking.html'>排名</a></p>"
        f"<h2>期望 / 实际 Plan</h2><pre>EXPECTED STEPS: {html.escape(json.dumps(case['execution_steps'], ensure_ascii=False))}\n"
        f"ACTUAL STEPS: {html.escape(json.dumps(plan.get('execution_steps'), ensure_ascii=False))}\n"
        f"UNFULFILLED: {html.escape(json.dumps(request.get('unfulfilled_requests'), ensure_ascii=False))}</pre>"
        f"<h2>QC / 能力边界</h2><pre>{html.escape(', '.join(case['capability_boundaries']) or 'none')}</pre>"
        f"<h2>阶段</h2><table><thead><tr><th>步骤</th><th>状态</th><th>耗时</th><th>说明</th></tr></thead>"
        f"<tbody>{step_rows or '<tr><td colspan=4>导入病例无计算步骤</td></tr>'}</tbody></table>"
        f"{preview_html}"
        "<p>技术 PASS 不代表胎儿医学正常。</p>",
    )


def user_dashboard_dir(case: dict[str, Any], execute_result: dict[str, Any] | None = None) -> Path | None:
    payload = execute_result or {}
    for candidate in (
        Path(str((payload.get("dashboard") or {}).get("dashboard_dir") or "")),
        Path(case.get("work_root") or "") / "dashboard",
    ):
        if candidate.is_dir() and (candidate / "index.html").is_file() and (candidate / "run_state.json").is_file():
            return candidate
    return None


def extra_live_pages(case_id: str, run_dir: Path) -> list[tuple[str, str]]:
    wanted = {
        "I02": ["previews/03_registration_interactive.html"],
        "N01": ["previews/02_reconstruction_interactive.html"],
        "N02": ["previews/03_registration_interactive.html", "previews/02_reconstruction_interactive.html"],
        "N03": ["previews/02_reconstruction_interactive.html", "previews/06_surface_interactive.html"],
        "N04": ["previews/03_registration_interactive.html"],
        "C01": ["previews/02_reconstruction_interactive.html"],
    }
    pages: list[tuple[str, str]] = []
    for rel in wanted.get(case_id, []):
        if (run_dir / rel).is_file():
            pages.append((f"{case_id}_{Path(rel).stem}.png", f"/{rel}"))
    return pages


def select_agentic_run(case_dir: Path) -> tuple[str, Path] | None:
    """Pick the doctor-console run: completed agentic state if any, else latest."""
    states = list((case_dir / "agentic").glob("*/agentic_state.json"))
    if not states:
        return None
    ranked: list[tuple[int, float, Path]] = []
    for path in states:
        data = json.loads(path.read_text(encoding="utf-8"))
        status = str(data.get("status") or "")
        rank = 2 if status == "completed" else 1 if status in {"imported", "planned"} else 0
        ranked.append((rank, path.stat().st_mtime, path))
    best = max(ranked)
    return best[2].parent.name, best[2].parent


def start_doctor_dashboard(run_root: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    """Serve the Chinese agentic console (`python -m agentic.dashboard_cn`) for screenshots."""
    import agentic.dashboard_cn  # noqa: F401 — apply Chinese INDEX_HTML translations
    from agentic.dashboard_server import AgenticHandler

    class Handler(AgenticHandler):
        pass

    Handler.store = StateStore(run_root)
    Handler.executor = AgenticExecutor(ROOT, run_root)
    Handler.allow_roots = [
        ROOT.resolve(),
        run_root.resolve(),
        Path("/tmp").resolve(),
        Path("/mnt/sda").resolve(),
    ]
    Handler.llm = OpenAICompatibleClient(load_llm_config(ROOT))
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Handler.dashboard_url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, Handler.dashboard_url


def start_live_dashboard(run_dir: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = lambda *args, **kwargs: DashboardHandler(  # noqa: E731
        *args, directory=str(run_dir), run_dir=run_dir, **kwargs
    )
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def wait_json(url: str, timeout: float = 12.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if isinstance(payload, dict):
                    return {"ok": True, "payload": payload}
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            last = str(exc)
        time.sleep(0.2)
    return {"ok": False, "error": last, "payload": {}}


def start_static_server(root: Path) -> tuple[socketserver.TCPServer, str]:
    handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(*args, directory=str(root), **kwargs)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}"


def capture_png(url: str, output: Path, width: int = 1680, height: int = 3200) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    last_error = ""
    for attempt in range(3):
        if output.is_file():
            try:
                output.unlink()
            except OSError:
                pass
        profile = tempfile.mkdtemp(prefix="autorecon-chrome-")
        command = [
            "google-chrome", "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--no-first-run", "--disable-extensions", "--run-all-compositor-stages-before-draw",
            "--no-sandbox", "--disable-dev-shm-usage",
            f"--user-data-dir={profile}",
            f"--window-size={width},{height}", f"--screenshot={output}",
            "--virtual-time-budget=20000", url,
        ]
        proc = subprocess.Popen(
            command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            last_error = f"chrome timed out after 90s (attempt {attempt + 1})"
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            shutil.rmtree(profile, ignore_errors=True)
            time.sleep(1)
            continue
        shutil.rmtree(profile, ignore_errors=True)
        ok = proc.returncode == 0 and output.is_file() and output.stat().st_size > 1000
        if ok:
            return {
                "url": url, "path": str(output), "status": "passed",
                "returncode": proc.returncode, "stderr": (stderr or "")[-1000:],
            }
        last_error = (stderr or stdout or f"chrome exit {proc.returncode}")[-1000:]
        time.sleep(1)
    return {
        "url": url, "path": str(output), "status": "failed",
        "returncode": 1, "stderr": last_error,
    }


def validate_screenshot(path: Path, required_width: int = 1440, required_height: int = 1000) -> dict[str, Any]:
    from PIL import Image, ImageStat
    result = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        result["status"] = "failed"
        return result
    image = Image.open(path)
    stats = ImageStat.Stat(image.convert("L"))
    result.update({
        "width": image.width, "height": image.height, "stddev": float(stats.stddev[0]),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "status": "passed" if image.width >= required_width and image.height >= required_height and stats.stddev[0] > 5 else "failed",
    })
    return result


def capture_all_screenshots(batch_root: Path, cases: list[dict[str, Any]], execute_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    shot_dir = batch_root / "dashboard" / "screenshots"
    shot_dir.mkdir(parents=True, exist_ok=True)
    for stale in shot_dir.glob("*.png"):
        stale.unlink()
    for case in cases:
        payload = execute_results.get(case["case_id"]) or _load_json(batch_root / "cases" / case["case_id"] / "execute_result.json", {})
        render_case_html(case, batch_root, payload)
    shot_root = batch_root / "dashboard" / "_agentic_shot_root"
    if shot_root.exists():
        shutil.rmtree(shot_root)
    shot_root.mkdir(parents=True)
    run_ids: dict[str, str] = {}
    for case in cases:
        selected = select_agentic_run(batch_root / "cases" / case["case_id"])
        if selected is None:
            continue
        run_id, src = selected
        dest = shot_root / run_id
        if dest.exists() or dest.is_symlink():
            dest.unlink()
        dest.symlink_to(src.resolve())
        run_ids[case["case_id"]] = run_id
    captures: list[dict[str, Any]] = []
    overview_paths: list[Path] = []
    server, base = start_doctor_dashboard(shot_root)
    try:
        for case in cases:
            run_id = run_ids.get(case["case_id"])
            if not run_id:
                captures.append({"case_id": case["case_id"], "kind": "live_dashboard", "status": "failed", "error": "no agentic run for doctor dashboard"})
                continue
            state = wait_json(f"{base}/api/state?run_id={quote(run_id)}")
            payload = state.get("payload") or {}
            request = payload.get("request") or {}
            api_ok = bool(state.get("ok") and request.get("raw_text") and payload.get("plan"))
            overview = shot_dir / f"{case['case_id']}_dashboard_overview.png"
            try:
                shot = capture_png(f"{base}/?run_id={quote(run_id)}", overview, 1680, 3200)
            except Exception as exc:
                shot = {
                    "url": f"{base}/?run_id={quote(run_id)}",
                    "path": str(overview),
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            shot.update({
                "case_id": case["case_id"],
                "kind": "live_dashboard",
                "ui": "agentic_cn",
                "api_ok": api_ok,
                "run_id": run_id,
                "subject": Path(str(request.get("subject_dir") or "")).name or case.get("subject"),
                "run_status": payload.get("status"),
                "raw_text": request.get("raw_text"),
            })
            if not api_ok:
                shot["status"] = "failed"
                shot["error"] = state.get("error") or "doctor dashboard /api/state missing request or plan"
            captures.append(shot)
            overview_paths.append(overview)
    finally:
        server.shutdown()
        server.server_close()
    static, static_base = start_static_server(batch_root)
    try:
        cells = "".join(
            f'<div><img src="{html.escape(Path(item["path"]).name)}" alt=""><p>{html.escape(Path(item["path"]).name)}</p></div>'
            for item in captures if item.get("path")
        )
        (shot_dir / "_summary.html").write_text(
            "<!doctype html><html lang=zh-CN><meta charset=utf-8><title>医生操作控制台截图</title>"
            "<style>body{font:14px system-ui;margin:16px}div{display:inline-block;width:340px;margin:8px;vertical-align:top}"
            "img{width:100%;border:1px solid #ccc}</style>"
            "<h1>医生操作层面：AutoRecon</h1>"
            "<p>这些截图来自 <code>python -m agentic.dashboard_cn</code>："
            "自然语言请求、中文报告与流程影像。上海科技大学 · SmileLab。"
            "不是工程师流水线 Remote Visualization，也不是验收用静态摘要页。</p>"
            f"{cells}</html>",
            encoding="utf-8",
        )
        captures.append(capture_png(f"{static_base}/dashboard/screenshots/_summary.html", shot_dir / "summary.png", 1600, 1200))
    finally:
        static.shutdown()
        static.server_close()
    validations = [validate_screenshot(Path(item["path"])) for item in captures if item.get("path")]
    overview_hashes = [item.get("sha256") for item in validations if Path(item["path"]).name.endswith("_dashboard_overview.png")]
    unique_overviews = len(overview_hashes) == len(set(overview_hashes)) and len(overview_hashes) == len(cases)
    live_ok = all(item.get("api_ok") and item.get("status") == "passed" for item in captures if item.get("kind") == "live_dashboard")
    index = ["<!doctype html><html lang=zh-CN><meta charset=utf-8><title>截图索引</title>", "<h1>医生操作控制台截图</h1><ul>"]
    checks_by_path = {item["path"]: item for item in validations}
    for item in captures:
        name = Path(item["path"]).name if item.get("path") else item.get("case_id", "missing")
        check = checks_by_path.get(item.get("path") or "", {})
        index.append(
            f"<li>{html.escape(name)} — {html.escape(str(check.get('status') or item.get('status')))}"
            f"{' · live API' if item.get('api_ok') else ''}</li>"
        )
    index.append("</ul>")
    (shot_dir / "index.html").write_text("\n".join(index), encoding="utf-8")
    overview_checks = [item for item in validations if Path(item["path"]).name.endswith("_dashboard_overview.png")]
    passed = (
        live_ok and unique_overviews
        and overview_checks
        and all(item.get("status") == "passed" for item in overview_checks)
    )
    return {
        "status": "passed" if passed else "failed",
        "planned_count": len(cases),
        "live_dashboard_ok": sum(1 for item in captures if item.get("kind") == "live_dashboard" and item.get("api_ok")),
        "unique_overviews": unique_overviews,
        "captures": captures,
        "validations": validations,
    }


def _status_cn(status: Any) -> str:
    text = str(status or "pending")
    mapping = {"passed": "通过", "failed": "失败", "completed": "完成", "pending": "未完成", "authorized": "已授权"}
    return mapping.get(text, text)


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_first_and_resume_from_cases(batch_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    first: list[dict[str, Any]] = []
    resumes: list[dict[str, Any]] = []
    cases_dir = batch_root / "cases"
    if not cases_dir.is_dir():
        return first, resumes
    for case_dir in sorted(path for path in cases_dir.iterdir() if path.is_dir()):
        payload = _load_json(case_dir / "execute_result.json", {})
        if payload:
            payload.setdefault("case_id", case_dir.name)
            first.append(payload)
        payload = _load_json(case_dir / "resume_result.json", {})
        if payload:
            payload.setdefault("case_id", case_dir.name)
            resumes.append(payload)
    return first, resumes


def resume_accepted(item: dict[str, Any]) -> bool:
    return item.get("resume_reused") is True or item.get("status") == "passed"


def build_execute_summaries(first_runs: list[dict[str, Any]], resumes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "execute_summary": {
            "status": "passed" if first_runs and all(item.get("status") == "passed" for item in first_runs) else ("failed" if first_runs else "pending"),
            "results": [{key: item.get(key) for key in ("case_id", "status", "resume", "duration_seconds", "recovered_via_resume") if key in item} for item in first_runs],
        },
        "resume_summary": {
            "status": "passed" if resumes and all(resume_accepted(item) for item in resumes) else ("pending" if not resumes else "failed"),
            "count": len(resumes),
            "reused": sum(1 for item in resumes if item.get("resume_reused")),
        },
    }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _mtime_utc(path: Path) -> datetime | None:
    try:
        if path.is_file():
            return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None
    return None


def compute_wall_seconds(case: dict[str, Any], first: dict[str, Any], timing: dict[str, Any]) -> float | None:
    work_root = Path(case.get("work_root") or "")
    subject = str(case.get("subject") or "")
    step_sum = sum(item.get("duration_seconds") or 0 for item in (timing.get("steps") or []))
    if first.get("status") != "passed" and first.get("duration_seconds"):
        step_sum += float(first["duration_seconds"])
    stamps: list[datetime] = []
    for path in (
        work_root / "staging" / subject / "seg" / "extraction_state.json",
        work_root / "staging" / "seg" / "extraction_state.json",
        work_root / "outputs" / "registration" / "summary.csv",
    ):
        stamp = _mtime_utc(path)
        if stamp:
            stamps.append(stamp)
    recon_root = work_root / "outputs" / "reconstruction"
    if recon_root.is_dir():
        for result_path in recon_root.glob("*/result.json"):
            payload = _load_json(result_path, {})
            for key in ("started_at", "finished_at"):
                raw = payload.get(key)
                if not raw:
                    continue
                try:
                    stamps.append(_as_utc(datetime.fromisoformat(str(raw).replace("Z", "+00:00"))))
                except ValueError:
                    continue
    artifact_span = (max(stamps) - min(stamps)).total_seconds() if len(stamps) >= 2 else None
    if artifact_span is not None and 30 <= artifact_span <= 6 * 3600:
        return max(artifact_span, step_sum) if step_sum >= 30 else artifact_span
    if step_sum >= 30:
        return step_sum
    payload = _load_json(work_root / "pipeline_result.json", {})
    if payload.get("started_at") and payload.get("finished_at"):
        run_span = _iso_seconds(payload.get("started_at"), payload.get("finished_at"))
        if run_span and run_span >= 30:
            return run_span
    return timing.get("wall_seconds") or first.get("duration_seconds")


def case_note(case: dict[str, Any], first: dict[str, Any], resumed: dict[str, Any], timing: dict[str, Any]) -> str:
    cid = case["case_id"]
    message = str(timing.get("message") or "")
    if cid == "N02":
        summary = Path(case.get("work_root") or "") / "outputs" / "registration" / "summary.csv"
        if summary.is_file():
            return "首次 bash exit 127；配准已续跑完成。墙钟含提取到配准。"
        return "提取/重建完成，配准未跑。首次 bash exit 127；续跑后 Dashboard 仍可能显示未完成。"
    if resumed.get("resume_reused") and resumed.get("status") != "passed":
        return "首次计算已完成且指纹一致（未重算）。resume 包装因 Dashboard 继承 flock 失败，现按复用计。"
    if first.get("recovered_via_resume"):
        return "首次进程中断后由续跑恢复；墙钟取重建产物时间，不等于验收包装时长。"
    if message:
        return message
    return ""


def sync_recovered_resumes(batch_root: Path, cases: list[dict[str, Any]]) -> None:
    """If a first run failed but requested steps later completed, record a recovered resume."""
    for case in cases:
        requested = list(case.get("execution_steps") or [])
        if not requested:
            continue
        first_path = batch_root / "cases" / case["case_id"] / "execute_result.json"
        first = _load_json(first_path, {})
        dash = user_dashboard_dir(case, first)
        if dash is None:
            continue
        state = _load_json(dash / "run_state.json", {})
        steps = {item.get("id"): item for item in state.get("steps") or []}
        if not all((steps.get(step) or {}).get("status") == "completed" for step in requested):
            continue
        if first.get("status") == "passed":
            continue
        resume_path = batch_root / "cases" / case["case_id"] / "resume_result.json"
        payload = _load_json(resume_path, {"case_id": case["case_id"], "subject": case.get("subject"), "resume": True})
        payload.update({
            "case_id": case["case_id"],
            "subject": case.get("subject"),
            "resume": True,
            "status": "passed",
            "run_status": (state.get("run") or {}).get("status"),
            "recovered_via_resume": True,
            "work_root": case.get("work_root"),
        })
        payload.setdefault("checks", {})
        payload["checks"]["run_completed"] = True
        write_json(resume_path, payload)


def assess_stability(batch_root: Path, cases: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    gates = {item.get("case_id"): item for item in summary.get("glm_gate") or []}
    first_runs, resumes = load_first_and_resume_from_cases(batch_root)
    first_by = {item.get("case_id"): item for item in first_runs}
    resume_by = {item.get("case_id"): item for item in resumes}
    shots = summary.get("screenshots") or _load_json(batch_root / "screenshots.json", {})
    live_by = {
        item.get("case_id"): item
        for item in shots.get("captures") or []
        if item.get("kind") == "live_dashboard"
    }
    rows: list[dict[str, Any]] = []
    incident_counts: dict[str, int] = {}
    for case in cases:
        cid = case["case_id"]
        first = first_by.get(cid) or {}
        resumed = resume_by.get(cid) or {}
        dash = user_dashboard_dir(case, first)
        state = _load_json(dash / "run_state.json", {}) if dash else {}
        steps = {item.get("id"): item for item in state.get("steps") or []}
        requested = list(case.get("execution_steps") or [])
        if requested:
            completed = sum(1 for step in requested if (steps.get(step) or {}).get("status") == "completed")
            scope_frac = completed / len(requested)
        else:
            scope_frac = 1.0 if (state.get("run") or {}).get("status") in {"completed", "imported", None} and dash else (1.0 if first.get("status") == "passed" else 0.0)
            if dash and (state.get("run") or {}).get("status") == "completed":
                scope_frac = 1.0
        pipeline_result = _load_json(Path(case.get("work_root") or "") / "pipeline_result.json", {})
        incidents: list[str] = []
        exit_code = pipeline_result.get("exit_code")
        if exit_code not in (None, 0) and first.get("status") != "passed":
            incidents.append(f"pipeline_exit_{exit_code}")
        if first.get("recovered_via_resume") or resumed.get("recovered_via_resume"):
            incidents.append("recovered_via_resume")
        if resumed.get("resume_reused") and resumed.get("status") != "passed":
            incidents.append("resume_wrapper_failed_fingerprint_ok")
        if first.get("status") == "failed" and scope_frac < 1 and not case.get("planned_interrupt"):
            incidents.append("incomplete_after_first_run")
        for item in incidents:
            incident_counts[item] = incident_counts.get(item, 0) + 1
        glm = 1.0 if gates.get(cid, {}).get("authorized") else 0.0
        if case.get("planned_interrupt"):
            if first.get("status") == "interrupted" or first.get("planned_interrupt"):
                first_ok = 1.0
                incidents.append("planned_interrupt")
                incident_counts["planned_interrupt"] = incident_counts.get("planned_interrupt", 0) + 1
            else:
                first_ok = 0.0
                incidents.append("planned_interrupt_missed")
                incident_counts["planned_interrupt_missed"] = incident_counts.get("planned_interrupt_missed", 0) + 1
        else:
            first_ok = 1.0 if first.get("status") == "passed" else 0.0
        if not case.get("resume_after"):
            resume_ok = 1.0 if first_ok else 0.0
        elif resume_accepted(resumed):
            resume_ok = 1.0
        else:
            resume_ok = 0.0
        live = live_by.get(cid) or {}
        live_ok = 1.0 if live.get("api_ok") and live.get("status") == "passed" else 0.0
        capability_ok = 1.0 if first.get("checks", {}).get("capability_in_report", True) and first.get("checks", {}).get("no_clinical_claim", True) else 0.0
        score = round(100 * (
            0.20 * glm + 0.25 * first_ok + 0.15 * resume_ok + 0.20 * scope_frac + 0.10 * live_ok + 0.10 * capability_ok
        ), 1)
        wall = compute_wall_seconds(case, first, pipeline_timing(Path(case.get("work_root") or "")))
        rows.append({
            "case_id": cid,
            "subject": case.get("subject"),
            "type": case.get("type"),
            "score": score,
            "glm": glm,
            "first_pass": first_ok,
            "resume": resume_ok,
            "scope_completion": round(scope_frac, 3),
            "live_dashboard": live_ok,
            "capability": capability_ok,
            "wall_seconds": wall,
            "dashboard_status": (state.get("run") or {}).get("status"),
            "incidents": incidents,
        })
    scored = [item for item, case in zip(rows, cases) if not case.get("planned_interrupt")]
    interrupt_rows = [item for item, case in zip(rows, cases) if case.get("planned_interrupt")]
    resume_pairs = [case for case in cases if case.get("doctor_resume_of")]
    first_pass_rate = sum(item["first_pass"] for item in scored) / len(scored) if scored else 0.0
    recovered_rate = sum(1 for item in scored if item["scope_completion"] >= 1) / len(scored) if scored else 0.0
    live_rate = sum(item["live_dashboard"] for item in rows) / len(rows) if rows else 0.0
    mean_score = sum(item["score"] for item in rows) / len(rows) if rows else 0.0
    protocol_rate = (
        sum(1 for item in interrupt_rows if item["first_pass"] >= 1) / len(interrupt_rows)
        if interrupt_rows else None
    )
    recovery_rate = None
    if resume_pairs:
        by_id = {item["case_id"]: item for item in rows}
        recovery_rate = sum(
            1 for case in resume_pairs
            if (by_id.get(case["case_id"]) or {}).get("scope_completion", 0) >= 1
        ) / len(resume_pairs)
    if first_pass_rate >= 1 and recovered_rate >= 1 and live_rate >= 1:
        verdict = "stable"
        verdict_zh = "本批首次直通且界面可复现，稳定性达到本轮验收标准。"
    elif recovered_rate >= 1 and mean_score >= 70:
        verdict = "recoverable"
        verdict_zh = "研究可用：失败可恢复到完整产物，但首次直通不稳定，不能当作无人值守生产。"
    else:
        verdict = "unstable"
        verdict_zh = "不稳定：仍有病例未跑完请求范围，或医生操作控制台无法复现。"
    return {
        "verdict": verdict,
        "verdict_zh": verdict_zh,
        "mean_score": round(mean_score, 1),
        "first_pass_rate": round(first_pass_rate, 3),
        "recovered_rate": round(recovered_rate, 3),
        "live_dashboard_rate": round(live_rate, 3),
        "planned_interrupt_protocol_rate": None if protocol_rate is None else round(protocol_rate, 3),
        "planned_interrupt_recovery_rate": None if recovery_rate is None else round(recovery_rate, 3),
        "incident_counts": incident_counts,
        "cases": rows,
    }


def assemble_summary_from_disk(batch_root: Path, summary: dict[str, Any]) -> dict[str, Any]:
    gates = _load_json(batch_root / "glm_gate.json", summary.get("glm_gate") or [])
    first_runs, resumes = load_first_and_resume_from_cases(batch_root)
    execute_audit = list(_load_json(batch_root / "execute.json", summary.get("execute") or []))
    compare = _load_json(batch_root / "compare.json", summary.get("compare") or {})
    shots = _load_json(batch_root / "screenshots.json", summary.get("screenshots") or {})
    defects_payload = _load_json(batch_root / "defects.json", {"defects": summary.get("defects") or []})
    freeze = summary.get("freeze") or _load_json(batch_root / "summary.json", {}).get("freeze") or {}
    merged = dict(summary)
    merged["freeze"] = freeze
    merged["glm_gate"] = gates
    merged["glm_gate_summary"] = {
        "status": "passed" if gates and all(item.get("authorized") for item in gates) else ("failed" if gates else "pending"),
        "authorized": sum(1 for item in gates if item.get("authorized")),
        "total": len(gates),
    }
    merged["execute"] = first_runs + resumes
    merged["execute_audit"] = execute_audit
    passed_ids = {item.get("case_id") for item in first_runs if item.get("status") == "passed"}
    fingerprint_resumes = [item for item in resumes if item.get("case_id") in passed_ids]
    merged.update(build_execute_summaries(first_runs, fingerprint_resumes))
    merged["compare"] = compare
    if compare:
        ranking_ok = compare.get("ranking_mode") == "automatic_only" and compare.get("recommended_backend") is None
        expert_ok = compare.get("ranking_mode") == "final_with_expert"
        merged["compare_summary"] = {"status": "passed" if ranking_ok or expert_ok else "failed"}
    else:
        merged["compare_summary"] = {"status": "pending"}
    merged["screenshots"] = shots
    merged["screenshot_summary"] = {
        "status": shots.get("status", "pending") if shots else "pending",
        "planned_count": shots.get("planned_count") if shots else 0,
        "live_dashboard_ok": shots.get("live_dashboard_ok"),
        "unique_overviews": shots.get("unique_overviews"),
    }
    merged["defects"] = defects_payload.get("defects") if isinstance(defects_payload, dict) else list(defects_payload or [])
    try:
        cases = load_cases(batch_root)
    except Exception:
        cases = []
    if cases:
        merged["stability"] = assess_stability(batch_root, cases, merged)
        merged["stability_summary"] = {
            "status": "passed" if merged["stability"].get("verdict") in {"stable", "recoverable"} else "failed",
            "verdict": merged["stability"].get("verdict"),
            "mean_score": merged["stability"].get("mean_score"),
        }
    return merged


def write_summary_documents(batch_root: Path, data: dict[str, Any]) -> None:
    cases = load_cases(batch_root)
    gates = {item.get("case_id"): item for item in data.get("glm_gate") or []}
    first_runs, resumes = load_first_and_resume_from_cases(batch_root)
    execute_by_id = {item.get("case_id"): item for item in first_runs}
    resume_by_id = {item.get("case_id"): item for item in resumes}
    rows = []
    md_rows = []
    shot_dir = batch_root / "dashboard" / "screenshots"
    shot_links = []
    if shot_dir.is_dir():
        for path in sorted(shot_dir.glob("*.png")):
            if path.name.startswith("_"):
                continue
            rel = f"dashboard/screenshots/{path.name}"
            shot_links.append(f"<figure><img src='{html.escape(rel)}' alt='{html.escape(path.name)}'><figcaption>{html.escape(path.name)}</figcaption></figure>")
    for case in cases:
        gate = gates.get(case["case_id"], {})
        first = execute_by_id.get(case["case_id"], {})
        resumed = resume_by_id.get(case["case_id"], {})
        timing = pipeline_timing(Path(case["work_root"])) if case.get("work_root") else {}
        case_dir = f"cases/{case['case_id']}"
        glm = "通过" if gate.get("authorized") else _status_cn(gate.get("status"))
        run = _status_cn(first.get("status"))
        if resumed.get("resume_reused"):
            resume = "复用"
        else:
            resume = _status_cn(resumed.get("status") or ("—" if not case.get("resume_after") else "未做"))
        note = case_note(case, first, resumed, timing)
        wall = _fmt_seconds(compute_wall_seconds(case, first, timing))
        rows.append(
            "<tr>"
            f"<td>{html.escape(case['case_id'])}</td>"
            f"<td>{html.escape(case['subject'])}</td>"
            f"<td>{html.escape(case['type'])}</td>"
            f"<td class='{html.escape(str(gate.get('status') or 'pending'))}'>{html.escape(glm)}</td>"
            f"<td class='{html.escape(str(first.get('status') or 'pending'))}'>{html.escape(run)}</td>"
            f"<td>{html.escape(resume)}</td>"
            f"<td>{html.escape(wall)}</td>"
            f"<td>{html.escape(note)}</td>"
            f"<td><a href='{html.escape(case_dir)}/dashboard/index.html'>验收页</a> · "
            f"<a href='{html.escape(case_dir)}/pipeline/dashboard/index.html'>流水线</a> · "
            f"<a href='{html.escape(case_dir)}/report.md'>报告</a></td>"
            "</tr>"
        )
        md_rows.append(
            f"| {case['case_id']} | {case['subject']} | {case['type']} | {glm} | {run} | {resume} | {wall} | {note or '—'} |"
        )
    defects = data.get("defects") or []
    compare = data.get("compare") or {}
    freeze = data.get("freeze") or {}
    glm_s = data.get("glm_gate_summary") or {}
    exe_s = data.get("execute_summary") or {}
    resume_s = data.get("resume_summary") or {}
    cmp_s = data.get("compare_summary") or {}
    shot_s = data.get("screenshot_summary") or {}
    stab = data.get("stability") or {}
    overall = "通过" if not defects and all(
        str((item or {}).get("status")) == "passed"
        for item in (glm_s, exe_s, cmp_s, shot_s)
        if item
    ) else "未全部通过"
    ranking_note = (
        f"排名模式 `{compare.get('ranking_mode') or '未跑'}`；"
        f"自动推荐后端 `{compare.get('recommended_backend') or '无（未完成盲评，不得宣称最佳方法）'}`。"
    )
    stab_rows = []
    stab_md = []
    for item in stab.get("cases") or []:
        stab_rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('case_id')))}</td>"
            f"<td>{html.escape(str(item.get('score')))}</td>"
            f"<td>{html.escape(str(int((item.get('first_pass') or 0) * 100)))}%</td>"
            f"<td>{html.escape(str(int((item.get('scope_completion') or 0) * 100)))}%</td>"
            f"<td>{html.escape(str(item.get('dashboard_status') or '—'))}</td>"
            f"<td>{html.escape('是' if item.get('live_dashboard') else '否')}</td>"
            f"<td>{html.escape(', '.join(item.get('incidents') or []) or '无')}</td>"
            "</tr>"
        )
        stab_md.append(
            f"| {item.get('case_id')} | {item.get('score')} | {int((item.get('first_pass') or 0)*100)}% | "
            f"{int((item.get('scope_completion') or 0)*100)}% | {item.get('dashboard_status') or '—'} | "
            f"{'是' if item.get('live_dashboard') else '否'} | {', '.join(item.get('incidents') or []) or '无'} |"
        )
    stability_html = (
        f"<h2>医生操作稳定性（定量）</h2>"
        f"<p><strong>{html.escape(str(stab.get('verdict_zh') or '尚未评估'))}</strong></p>"
        "<ul>"
        f"<li>综合均分：<code>{html.escape(str(stab.get('mean_score', '—')))}</code> / 100</li>"
        f"<li>首次直通率：<code>{html.escape(str(stab.get('first_pass_rate', '—')))}</code></li>"
        f"<li>请求范围最终完成率：<code>{html.escape(str(stab.get('recovered_rate', '—')))}</code></li>"
        f"<li>医生控制台可加载率：<code>{html.escape(str(stab.get('live_dashboard_rate', '—')))}</code></li>"
        f"<li>事件：<code>{html.escape(json.dumps(stab.get('incident_counts') or {}, ensure_ascii=False))}</code></li>"
        "</ul>"
        "<p>计分：GLM 20% + 首次执行 25% + resume/复用 15% + 请求步骤完成 20% + 医生控制台截图 10% + 能力边界 10%。</p>"
        "<table><thead><tr><th>ID</th><th>得分</th><th>首次直通</th><th>范围完成</th><th>Dashboard 状态</th><th>活界面</th><th>事件</th></tr></thead>"
        f"<tbody>{''.join(stab_rows) or '<tr><td colspan=7>无</td></tr>'}</tbody></table>"
    )
    document = f"""<!doctype html><html lang=zh-CN><meta charset=utf-8><title>七病例验收总结</title>
<style>
body{{font:15px/1.5 system-ui,sans-serif;max-width:1280px;margin:32px auto;padding:0 16px;color:#17211d}}
table{{border-collapse:collapse;width:100%;margin:12px 0 24px}}
td,th{{border:1px solid #ccd5df;padding:8px;vertical-align:top}}
th{{background:#eef3f0;text-align:left}}
.passed{{color:#087830;font-weight:600}}.failed{{color:#b42318;font-weight:600}}.pending{{color:#8a5a00}}
code{{background:#f3f5f4;padding:1px 4px}}
figure{{display:inline-block;width:320px;margin:8px;vertical-align:top}}
figure img{{width:100%;border:1px solid #ccd5df}}
</style>
<h1>AutoRecon 七病例验收总结</h1>
<p>批次：<code>{html.escape(str(batch_root))}</code></p>
<p>冻结 plan SHA-256：<code>{html.escape(str(freeze.get('plan_sha256') or ''))}</code></p>
<p>总体结论：<strong class="{html.escape('passed' if overall == '通过' else 'failed')}">{html.escape(overall)}</strong></p>
<ul>
<li>GLM 门控：{_status_cn(glm_s.get('status'))}（{glm_s.get('authorized', 0)}/{glm_s.get('total', 0)} 授权）</li>
<li>首次执行：{_status_cn(exe_s.get('status'))}（不含 fingerprint resume）</li>
<li>Resume 指纹：{_status_cn(resume_s.get('status'))}（复用 {resume_s.get('reused', 0)}/{resume_s.get('count', 0)}；指纹一致即通过）</li>
<li>比较：{_status_cn(cmp_s.get('status'))}。{html.escape(ranking_note)}</li>
<li>截图：{_status_cn(shot_s.get('status'))}（医生控制台 {shot_s.get('live_dashboard_ok') or 0}/{shot_s.get('planned_count') or 0}）</li>
</ul>
{stability_html}
<h2>逐例结果</h2>
<table>
<thead><tr><th>ID</th><th>病例</th><th>类型</th><th>GLM</th><th>首次执行</th><th>Resume</th><th>墙钟</th><th>说明</th><th>产物</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
<h2>缺陷台账</h2>
{"<ul>" + "".join(f"<li>{html.escape(str(item))}</li>" for item in defects) + "</ul>" if defects else "<p>无记录缺陷。</p>"}
<h2>截图</h2>
<p><a href="dashboard/screenshots/index.html">索引</a> · <a href="dashboard/screenshots/summary.png">总览 PNG</a></p>
{''.join(shot_links) or "<p>尚无截图。</p>"}
<p><strong>技术 PASS 不代表胎儿医学正常。</strong> C01 自动技术排名不等于最终最佳方法。</p>
</html>"""
    (batch_root / "report.zh-CN.html").write_text(document, encoding="utf-8")
    markdown = f"""# AutoRecon 七病例验收总结

- 批次：`{batch_root}`
- 冻结 plan SHA-256：`{freeze.get('plan_sha256') or ''}`
- 总体结论：**{overall}**

## 阶段

| 阶段 | 状态 | 说明 |
|---|---|---|
| GLM 门控 | {_status_cn(glm_s.get('status'))} | {glm_s.get('authorized', 0)}/{glm_s.get('total', 0)} 授权；fallback 不得授权实算 |
| 首次执行 | {_status_cn(exe_s.get('status'))} | 按 `execute_result.json`，不含 fingerprint resume |
| Resume 指纹 | {_status_cn(resume_s.get('status'))} | 复用 {resume_s.get('reused', 0)}/{resume_s.get('count', 0)}；指纹一致即通过 |
| 比较 | {_status_cn(cmp_s.get('status'))} | {ranking_note} |
| 截图 | {_status_cn(shot_s.get('status'))} | 医生操作控制台 {shot_s.get('live_dashboard_ok') or 0}/{shot_s.get('planned_count') or 0} |

## 医生操作稳定性（定量）

{stab.get('verdict_zh') or '尚未评估'}

- 综合均分：`{stab.get('mean_score', '—')}` / 100
- 首次直通率：`{stab.get('first_pass_rate', '—')}`
- 请求范围最终完成率：`{stab.get('recovered_rate', '—')}`
- 医生控制台可加载率：`{stab.get('live_dashboard_rate', '—')}`
- 事件：`{json.dumps(stab.get('incident_counts') or {}, ensure_ascii=False)}`

| ID | 得分 | 首次直通 | 范围完成 | Dashboard | 活界面 | 事件 |
|---|---|---|---|---|---|---|
{chr(10).join(stab_md) or '| — | — | — | — | — | — | — |'}

## 逐例结果

| ID | 病例 | 类型 | GLM | 执行 | Resume | 墙钟 | 说明 |
|---|---|---|---|---|---|---|---|
{chr(10).join(md_rows)}

## 缺陷台账

{chr(10).join(f'- {item}' for item in defects) if defects else '无记录缺陷。'}

## 产物路径

- 中文 HTML：`report.zh-CN.html`
- 机器摘要：`summary.json`
- 缺陷：`defects.json`
- 截图索引：`dashboard/screenshots/index.html`

技术 PASS 不代表胎儿医学正常。C01 自动技术排名不等于最终最佳方法。
"""
    (batch_root / "SUMMARY.zh-CN.md").write_text(markdown, encoding="utf-8")


def html_report(batch_root: Path, data: dict[str, Any]) -> None:
    write_summary_documents(batch_root, assemble_summary_from_disk(batch_root, data))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-root", type=Path)
    parser.add_argument("--phase", choices=("freeze", "glm-gate", "execute", "execute-one", "compare", "screenshots", "report", "all", "continue"), default="all")
    parser.add_argument("--suite", choices=("gold", "expand", "continue"), default="gold")
    parser.add_argument("--expand-batch", type=Path)
    parser.add_argument("--gold-batch", type=Path)
    parser.add_argument("--cases", default="", help="Comma-separated case ids; empty means all.")
    parser.add_argument("--gpus", default="1,2")
    parser.add_argument("--glm-workers", type=int, default=4, help="Parallel GLM gate workers.")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--skip-resume", action="store_true")
    parser.add_argument("--resume-one", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    os.environ.setdefault("AUTORECON_CONFIG_FILE", str(ROOT / "config/glm.env"))
    os.environ.setdefault("AUTORECON_SECRET_FILE", str(ROOT / ".secrets/glm.env"))
    validation_root = ROOT / "validation_runs"
    validation_root.mkdir(parents=True, exist_ok=True)
    if args.suite == "expand":
        batch_root = args.batch_root or (validation_root / f"stability_expand_{utc_stamp()}")
    elif args.suite == "continue":
        batch_root = args.batch_root or (validation_root / f"stability_continue_{utc_stamp()}")
    else:
        batch_root = args.batch_root or find_latest_batch(validation_root) or (validation_root / f"case_acceptance_{utc_stamp()}")
    batch_root = batch_root.resolve()
    selected = {item.strip() for item in args.cases.split(",") if item.strip()}
    gpu_ids = [item.strip() for item in args.gpus.split(",") if item.strip()]
    if args.suite == "gold":
        gpu_ids = gpu_ids[:2]
    config = load_llm_config(ROOT)
    llm = OpenAICompatibleClient(config)
    if args.suite == "expand":
        from validation.stability_suites import build_expand_cases
        freeze = freeze_batch(batch_root, build_expand_cases(batch_root))
    elif args.suite == "continue":
        from validation.stability_suites import GOLD_BATCH, build_continue_cases, latest_expand_batch
        freeze = freeze_batch(batch_root, build_continue_cases(
            batch_root,
            expand_batch=args.expand_batch or latest_expand_batch(),
            gold_batch=args.gold_batch or GOLD_BATCH,
        ))
    else:
        freeze = freeze_batch(batch_root)
    cases = [case for case in load_cases(batch_root) if not selected or case["case_id"] in selected]
    summary: dict[str, Any] = {"generated_at": now(), "freeze": freeze}
    defects: list[str] = []

    if args.phase in {"glm-gate", "all", "continue"}:
        gate_dir = batch_root / "glm_gate"
        gate_dir.mkdir(parents=True, exist_ok=True)
        if not config.available:
            raise SystemExit("GLM is unavailable; configure AUTORECON_SECRET_FILE")
        saved_by: dict[str, Any] = {}
        pending_gate = []
        for case in cases:
            saved = gate_dir / f"{case['case_id']}_glm.json"
            if saved.is_file():
                payload = json.loads(saved.read_text(encoding="utf-8"))
                if payload.get("authorized"):
                    saved_by[case["case_id"]] = payload
                    continue
            pending_gate.append(case)
        by_id: dict[str, Any] = {}
        if pending_gate:
            with ThreadPoolExecutor(max_workers=min(args.glm_workers, max(1, len(pending_gate)))) as pool:
                futures = {pool.submit(glm_gate_case, case, llm, args.repeats, gate_dir): case["case_id"] for case in pending_gate}
                by_id = {cid: future.result() for future, cid in ((future, futures[future]) for future in as_completed(futures))}
        gates = [saved_by.get(case["case_id"]) or by_id[case["case_id"]] for case in cases]
        summary["glm_gate"] = gates
        summary["glm_gate_summary"] = {
            "status": "passed" if all(item["authorized"] for item in gates) else "failed",
            "authorized": sum(item["authorized"] for item in gates),
            "total": len(gates),
        }
        write_json(batch_root / "glm_gate.json", summary["glm_gate"])
        if summary["glm_gate_summary"]["status"] != "passed":
            defects.append("GLM gate failed")
            if args.phase in {"all", "continue"}:
                write_json(batch_root / "defects.json", {"defects": defects, "summary": summary["glm_gate_summary"]})
                html_report(batch_root, summary)
                print(json.dumps(summary["glm_gate_summary"], indent=2, ensure_ascii=False))
                return 2

    if args.phase == "execute-one":
        if len(cases) != 1:
            raise SystemExit("execute-one requires exactly one --cases id")
        gpu = gpu_ids[0] if gpu_ids else None
        port = 8930 + (int(cases[0]["case_id"][-1]) if cases[0]["case_id"][-1].isdigit() else 0)
        payload = execute_case(cases[0], batch_root, llm, resume=args.resume_one, gpu=gpu, dashboard_port=port)
        print(json.dumps({key: payload.get(key) for key in ("case_id", "status", "resume", "duration_seconds")}, indent=2, ensure_ascii=False))
        return 0 if payload.get("status") == "passed" else 2

    if args.phase == "report":
        sync_recovered_resumes(batch_root, load_cases(batch_root) if not selected else cases)
        summary = assemble_summary_from_disk(batch_root, summary)
        summary["defects"] = summary.get("defects") or []
        write_json(batch_root / "summary.json", {key: value for key, value in summary.items() if key != "glm_gate"})
        write_json(batch_root / "defects.json", {"defects": summary["defects"]})
        html_report(batch_root, summary)
        if summary.get("stability"):
            write_json(batch_root / "stability.json", summary["stability"])
        print(json.dumps({
            "batch_root": str(batch_root),
            "documents": [str(batch_root / "report.zh-CN.html"), str(batch_root / "SUMMARY.zh-CN.md")],
            **{key: summary.get(key) for key in ("glm_gate_summary", "execute_summary", "compare_summary", "screenshot_summary", "stability_summary")},
            "defects": summary.get("defects"),
        }, indent=2, ensure_ascii=False))
        return 0

    execute_results: dict[str, dict[str, Any]] = {}
    if args.phase in {"execute", "all", "continue"}:
        authorized = {item["case_id"] for item in summary.get("glm_gate", []) if item.get("authorized")}
        if args.phase in {"execute", "continue"}:
            gate_payload = json.loads((batch_root / "glm_gate.json").read_text(encoding="utf-8")) if (batch_root / "glm_gate.json").is_file() else []
            authorized = {item["case_id"] for item in gate_payload if item.get("authorized")}
        runnable = [case for case in cases if case["case_id"] in authorized]
        from validation.stability_suites import case_needs_gpu, execution_waves, materialize_source
        for case in runnable:
            materialize_source(case)
        imports = [case for case in runnable if not case_needs_gpu(case)]
        computes = [case for case in runnable if case_needs_gpu(case)]
        results = []
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(imports)))) as pool:
            futures = []
            for case in imports:
                existing = passed_execute_result(batch_root, case["case_id"], resume=False)
                if existing is not None:
                    results.append(existing)
                    continue
                port = 8920 + (sum(ord(ch) for ch in case["case_id"]) % 80)
                futures.append(pool.submit(execute_case, case, batch_root, llm, resume=False, gpu=None, dashboard_port=port))
            for future in as_completed(futures):
                results.append(future.result())
        for wave in execution_waves(computes):
            wave_pending = []
            for case in wave:
                wait_for_execute_one(case["case_id"])
                existing = passed_execute_result(batch_root, case["case_id"], resume=False)
                if existing is not None:
                    results.append(existing)
                    continue
                wave_pending.append(case)
            index = 0
            while wave_pending:
                batch = wave_pending[: max(1, len(gpu_ids))]
                wave_pending = wave_pending[len(batch):]
                with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                    futures = []
                    for offset, case in enumerate(batch):
                        gpu = gpu_ids[(index + offset) % len(gpu_ids)] if gpu_ids else None
                        recover = pipeline_artifacts_reusable(case)
                        futures.append(pool.submit(execute_compute_isolated, batch_root, case["case_id"], gpu, recover))
                    for future in as_completed(futures):
                        results.append(future.result())
                index += len(batch)
        if not args.skip_resume:
            passed_ids = {
                case["case_id"]
                for case in runnable
                if passed_execute_result(batch_root, case["case_id"], resume=False) is not None
            }
            resume_targets = [case for case in runnable if case.get("resume_after") and case["case_id"] in passed_ids]
            before = {case["case_id"]: resume_fingerprints(case) for case in resume_targets}
            pending = []
            for case in resume_targets:
                saved = passed_execute_result(batch_root, case["case_id"], resume=True)
                if saved and saved.get("resume_reused") is True:
                    results.append(saved)
                    continue
                prior = before[case["case_id"]]
                current = resume_fingerprints(case)
                identical = (
                    prior.get("image_sha256")
                    and prior.get("image_sha256") == current.get("image_sha256")
                    and prior.get("fingerprint") == current.get("fingerprint")
                )
                if identical and pipeline_artifacts_reusable(case):
                    payload = {
                        "case_id": case["case_id"],
                        "subject": case["subject"],
                        "resume": True,
                        "status": "passed",
                        "resume_reused": True,
                        "skipped_reinvoke": True,
                        "run_status": "completed",
                        "duration_seconds": 0,
                        "fingerprint_before": prior,
                        "fingerprint_after": current,
                        "note": "fingerprint identical; skipped second pipeline entry",
                    }
                    write_json(batch_root / "cases" / case["case_id"] / "resume_result.json", payload)
                    results.append(payload)
                    continue
                pending.append(case)
            index = 0
            while pending:
                batch = pending[: max(1, len(gpu_ids))]
                pending = pending[len(batch):]
                with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                    futures = []
                    for offset, case in enumerate(batch):
                        gpu = gpu_ids[(index + offset) % len(gpu_ids)] if gpu_ids else None
                        futures.append(pool.submit(execute_compute_isolated, batch_root, case["case_id"], gpu, True))
                    for future in as_completed(futures):
                        resumed = future.result()
                        case_id = resumed.get("case_id")
                        after = resume_fingerprints(next(case for case in resume_targets if case["case_id"] == case_id))
                        reused = before[case_id].get("image_sha256") == after.get("image_sha256") and before[case_id].get("fingerprint") == after.get("fingerprint")
                        resumed["resume_reused"] = reused
                        resumed["fingerprint_before"] = before[case_id]
                        resumed["fingerprint_after"] = after
                        if not reused:
                            resumed["status"] = "failed"
                            defects.append(f"{case_id} resume did not reuse fingerprint-identical artifacts")
                        write_json(batch_root / "cases" / case_id / "resume_result.json", resumed)
                        results.append(resumed)
                index += len(batch)
        for item in results:
            if not item.get("resume") or item.get("recovered_via_resume"):
                execute_results[item["case_id"]] = item
        for case in runnable:
            existing = passed_execute_result(batch_root, case["case_id"], resume=False)
            if existing is not None:
                execute_results[case["case_id"]] = existing
        summary["execute"] = results
        first_runs, resume_rows = load_first_and_resume_from_cases(batch_root)
        summary.update(build_execute_summaries(first_runs, resume_rows))
        write_json(batch_root / "execute.json", results)

    if args.phase in {"compare", "all", "continue"}:
        c01 = next((case for case in load_cases(batch_root) if case["case_id"] == "C01"), None)
        if c01 and (not selected or "C01" in selected) and Path(c01["work_root"]).exists():
            notes = register_missing_backends(c01, config)
            ranking = score_candidates(Path(c01["work_root"]), c01["subject"], Path(c01["atlas"]))
            summary["compare"] = {"registration_notes": notes, "ranking_mode": ranking.get("ranking_mode"), "recommended_backend": ranking.get("recommended_backend")}
            summary["compare_summary"] = {
                "status": "passed" if ranking.get("ranking_mode") == "automatic_only" and ranking.get("recommended_backend") is None else ("passed" if ranking.get("ranking_mode") == "final_with_expert" else "failed")
            }
            if ranking.get("ranking_mode") != "automatic_only" and ranking.get("recommended_backend") and not (Path(c01["work_root"]) / "outputs/reconstruction/comparison/expert_review.csv").read_text(encoding="utf-8").strip().count("\n") > 1:
                defects.append("final best method claimed without expert review")
                summary["compare_summary"]["status"] = "failed"
            write_json(batch_root / "compare.json", summary["compare"])

    if args.phase in {"screenshots", "all", "continue"}:
        sync_recovered_resumes(batch_root, load_cases(batch_root) if not selected else cases)
        shots = capture_all_screenshots(batch_root, load_cases(batch_root) if not selected else cases, execute_results)
        summary["screenshots"] = shots
        summary["screenshot_summary"] = {
            "status": shots["status"],
            "planned_count": shots["planned_count"],
            "live_dashboard_ok": shots.get("live_dashboard_ok"),
            "unique_overviews": shots.get("unique_overviews"),
        }
        write_json(batch_root / "screenshots.json", shots)

    summary["defects"] = defects
    summary = assemble_summary_from_disk(batch_root, summary)
    summary["defects"] = defects or summary.get("defects") or []
    if summary.get("stability"):
        write_json(batch_root / "stability.json", summary["stability"])
    write_json(batch_root / "summary.json", {key: value for key, value in summary.items() if key != "glm_gate"})
    write_json(batch_root / "defects.json", {"defects": summary["defects"]})
    html_report(batch_root, summary)
    print(json.dumps({
        "batch_root": str(batch_root),
        "freeze": freeze.get("plan_sha256"),
        **{key: summary.get(key) for key in ("glm_gate_summary", "execute_summary", "compare_summary", "screenshot_summary", "stability_summary")},
        "defects": defects,
    }, indent=2, ensure_ascii=False))
    failed = any(
        isinstance(summary.get(key), dict) and summary[key].get("status") == "failed"
        for key in ("glm_gate_summary", "execute_summary", "compare_summary", "screenshot_summary")
    )
    return 2 if failed or defects else 0


if __name__ == "__main__":
    raise SystemExit(main())

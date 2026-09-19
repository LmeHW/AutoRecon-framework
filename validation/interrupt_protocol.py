"""Planned-interrupt protocol: SIGTERM, three-block snapshot, doctor resume."""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path
from typing import Any

from agentic.clinic_progress import format_clinic_progress, gallery_badges, next_step_after


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_run_state(work_root: Path) -> dict[str, Any]:
    path = Path(work_root) / "dashboard" / "run_state.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def step_already_past(status: str | None) -> bool:
    """Prior step is behind us: finished, or skipped because this run did not select it.

    Continue cases such as K18 only re-run later steps. The dashboard then marks
    extraction/reconstruction as skipped, not completed. Planned interrupt still
    means: wait until the next step is running, then SIGTERM.
    """
    return status in {"completed", "skipped"}


def interrupt_ready(state: dict[str, Any], interrupt_after: str) -> bool:
    steps = {item.get("id"): item for item in state.get("steps") or []}
    after = steps.get(interrupt_after) or {}
    nxt = next_step_after(interrupt_after)
    if not nxt:
        return False
    current = steps.get(nxt) or {}
    return step_already_past(after.get("status")) and current.get("status") == "running"


def report_must_not_complete_unfinished(report: str, steps: list[dict[str, Any]]) -> bool:
    unfinished = [
        item.get("id")
        for item in steps
        if item.get("id") in {"extraction", "reconstruction", "registration", "tissue", "roi", "surface"}
        and item.get("status") not in {"completed"}
    ]
    lowered = report or ""
    for step_id in unfinished:
        # Reject only the explicit "step completed" claim used by the reporter.
        if f"{step_id}`" in lowered and "completed" in lowered.lower():
            return False
    if "未执行" in lowered or "未完成" in lowered or "阅片复核清单" in lowered or not lowered.strip():
        return True
    return True


def snapshot_three_blocks(
    *,
    work_root: Path,
    run_status: str = "",
    report_markdown: str = "",
    agentic_status: str = "",
) -> dict[str, Any]:
    state = load_run_state(work_root)
    steps = list(state.get("steps") or [])
    progress = format_clinic_progress(steps, run_status or (state.get("run") or {}).get("status") or "")
    badges = gallery_badges(steps)
    report = report_markdown
    report_path = Path(work_root) / "dashboard" / "report.md"
    if not report and report_path.is_file():
        try:
            report = report_path.read_text(encoding="utf-8")
        except OSError:
            report = ""
    return {
        "progress_line": progress,
        "gallery": badges,
        "report_excerpt": (report or "")[:2000],
        "report_placeholder_or_failure": (not report.strip()) or ("未完成" in report) or ("失败" in report) or ("阅片复核清单" in report),
        "unfinished_not_marked_complete": report_must_not_complete_unfinished(report, steps),
        "state_status": agentic_status or (state.get("run") or {}).get("status"),
        "run_state_steps": [{"id": item.get("id"), "status": item.get("status")} for item in steps],
        "work_root": str(work_root),
    }


def render_interrupt_view(snapshot: dict[str, Any]) -> str:
    gallery = snapshot.get("gallery") or []
    cards = "\n".join(
        f'<div class="card"><header><span>{item["label"]}</span>'
        f'<span class="status-badge">{item["badge"]}</span></header></div>'
        for item in gallery
    )
    report = snapshot.get("report_excerpt") or "报告尚未生成。"
    return (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<title>中断三块</title>"
        "<style>body{font:15px/1.5 sans-serif;margin:24px;color:#20191a}"
        "#progress{font-weight:700;margin-bottom:18px}"
        ".gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}"
        ".card{border:1px solid #eadfe1;border-radius:12px;padding:12px}"
        "#report{margin-top:22px;white-space:pre-wrap;border:1px solid #eadfe1;padding:14px;border-radius:12px}</style>"
        "</head><body>"
        f"<div id='progress'>{snapshot.get('progress_line') or ''}</div>"
        f"<div id='gallery' class='gallery'>{cards}</div>"
        f"<div id='report'>{report}</div>"
        "</body></html>"
    )


def terminate_pipeline(work_root: Path) -> dict[str, Any]:
    pid_path = Path(work_root) / "dashboard" / "pipeline.pid"
    if not pid_path.is_file():
        return {"killed": False, "reason": "pipeline.pid missing"}
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return {"killed": False, "reason": "invalid pipeline.pid"}
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return {"killed": False, "reason": "process gone", "pid": pid}
    try:
        # flock -o re-execs the pipeline script, so pipeline.pid is often a child
        # in the session, not the process-group leader. killpg(pid) then misses.
        os.killpg(pgid, signal.SIGTERM)
        return {"killed": True, "pid": pid, "pgid": pgid, "signal": "SIGTERM"}
    except ProcessLookupError:
        return {"killed": False, "reason": "process gone", "pid": pid, "pgid": pgid}
    except PermissionError as exc:
        return {"killed": False, "reason": str(exc), "pid": pid, "pgid": pgid}


def watch_and_interrupt(
    work_root: Path,
    interrupt_after: str,
    stop_event: Any,
    *,
    poll_seconds: float = 1.0,
    timeout_seconds: float = 12 * 3600,
) -> dict[str, Any]:
    started = time.monotonic()
    work_root = Path(work_root)
    while not stop_event.is_set():
        if time.monotonic() - started > timeout_seconds:
            return {"interrupted": False, "reason": "timeout"}
        state = load_run_state(work_root)
        if interrupt_ready(state, interrupt_after):
            snapshot = snapshot_three_blocks(work_root=work_root, run_status="running")
            killed = terminate_pipeline(work_root)
            snapshot["interrupt_after"] = interrupt_after
            snapshot["during"] = next_step_after(interrupt_after)
            snapshot["kill"] = killed
            snapshot["progress_has_step_name"] = any(
                label in (snapshot.get("progress_line") or "")
                for label in ("脑提取", "三维重建", "图像配准", "组织分割", "脑区划分", "表面重建")
            ) and "请稍候" not in (snapshot.get("progress_line") or "")
            return {"interrupted": True, "snapshot": snapshot}
        if stop_event.wait(poll_seconds):
            break
    return {"interrupted": False, "reason": "stopped"}


def write_interrupt_snapshot(case_dir: Path, snapshot: dict[str, Any]) -> Path:
    case_dir.mkdir(parents=True, exist_ok=True)
    path = case_dir / "interrupt_snapshot.json"
    write_json(path, snapshot)
    (case_dir / "interrupt_view.html").write_text(render_interrupt_view(snapshot), encoding="utf-8")
    (case_dir / "interrupt_progress.txt").write_text(snapshot.get("progress_line") or "", encoding="utf-8")
    return path


def doctor_resume_overrides(case: dict[str, Any]) -> dict[str, Any]:
    work = case.get("work_root") or case.get("existing_run_dir")
    explicit = ["execution_mode", "existing_run_dir", "work_root", "resume", "report_language"]
    overrides: dict[str, Any] = {
        "execution_mode": "continue_from_run",
        "existing_run_dir": work,
        "work_root": work,
        "resume": True,
        "report_language": case.get("report_language") or "zh",
    }
    if case.get("subject_dir"):
        overrides["subject_dir"] = case["subject_dir"]
        explicit.append("subject_dir")
    if case.get("execution_steps"):
        overrides["execution_steps"] = list(case["execution_steps"])
        explicit.append("execution_steps")
    for key in ("gestational_age", "atlas", "atlas_week", "atlas_rule", "reconstruction_tool"):
        if case.get(key) not in (None, "", []):
            overrides[key] = case[key]
            explicit.append(key)
    overrides["explicit_fields"] = explicit
    return overrides


def reused_contains(completed_before: list[str], reused: list[str]) -> bool:
    return set(completed_before) <= set(reused or [])

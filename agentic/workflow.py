"""Canonical run path: request -> plan -> validate -> execute -> report.

CLI, dashboard, and the clinic gateway all call the same modules in this
order. This file is the library form of that sequence so the control flow
can be read in one place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .coordinator import coordinate_with_llm
from .env_config import load_llm_config
from .executor import AgenticExecutor, results_indicate_failure
from .llm_analysis import analyze_results_with_llm
from .llm_client import OpenAICompatibleClient
from .models import RunState, TaskPlan, UserRequest
from .planner import plan_with_llm, validate_plan, validate_runtime
from .reporter import build_report
from .schema_validation import validate_agentic_objects
from .state_store import StateStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_plan(
    raw_text: str,
    overrides: dict[str, Any] | None,
    llm: OpenAICompatibleClient | None,
    *,
    project_root: Path | None = None,
) -> tuple[UserRequest, TaskPlan, list[dict[str, Any]], list[str]]:
    root = project_root or PROJECT_ROOT
    request, request_event = coordinate_with_llm(raw_text, overrides, llm)
    task_plan, plan_event = plan_with_llm(request, llm)
    config = load_llm_config(root)
    errors = (
        validate_agentic_objects(root, request.to_dict(), task_plan.to_dict())
        + validate_plan(task_plan)
        + validate_runtime(task_plan, config.ants_dir, config.roi_warp_env)
    )
    return request, task_plan, [request_event, plan_event], errors


def execute_plan(
    task_plan: TaskPlan,
    run_id: str,
    llm: OpenAICompatibleClient | None,
    executor: AgenticExecutor,
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], str, dict[str, Any], bool]:
    results, dashboard = executor.execute(task_plan, run_id)
    report_llm = None if task_plan.execution_mode == "import_existing" else llm
    result_event = analyze_results_with_llm(results, report_llm)
    markdown, payload = build_report(
        task_plan, results, dashboard, report_llm, [*events, result_event]
    )
    failed = results_indicate_failure(results)
    return results, dashboard, markdown, payload, failed


def run(
    raw_text: str,
    overrides: dict[str, Any] | None,
    llm: OpenAICompatibleClient | None,
    store: StateStore,
    *,
    project_root: Path | None = None,
    executor: AgenticExecutor | None = None,
) -> dict[str, Any]:
    root = project_root or PROJECT_ROOT
    request, task_plan, events, errors = build_plan(raw_text, overrides, llm, project_root=root)
    run_id = store.new_run_id()
    state = RunState(run_id=run_id, status="planned", request=request.to_dict(), plan=task_plan.to_dict())
    if errors:
        state.status = "failed"
        state.report_markdown = "Plan validation failed:\n" + "\n".join(f"- {error}" for error in errors)
        state.report_json = {"errors": errors}
        return store.save(state)

    worker = executor or AgenticExecutor(root, store.root)
    results, dashboard, markdown, payload, failed = execute_plan(
        task_plan, run_id, llm, worker, events
    )
    state.step_results = results
    state.dashboard = dashboard
    state.status = "failed" if failed else "completed"
    state.report_markdown = markdown
    state.report_json = payload
    return store.save(state)

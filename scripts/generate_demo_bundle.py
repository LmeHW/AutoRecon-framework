#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agentic.coordinator import coordinate
from agentic.executor import AgenticExecutor
from agentic.models import RunState
from agentic.planner import plan, validate_plan
from agentic.reporter import build_report
from agentic.state_store import StateStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a local, no-external-LLM AutoRecon demo bundle.")
    parser.add_argument("--request", required=True)
    parser.add_argument("--existing-run-dir", required=True, type=Path)
    parser.add_argument("--ga", type=float)
    parser.add_argument("--run-root", type=Path, default=PROJECT_ROOT / "demo_runs")
    args = parser.parse_args()

    request = coordinate(args.request, {
        "execution_mode": "import_existing",
        "existing_run_dir": str(args.existing_run_dir.resolve()),
        "gestational_age": args.ga,
    })
    task_plan = plan(request)
    errors = validate_plan(task_plan)
    store = StateStore(args.run_root)
    run_id = store.new_run_id()
    state = RunState(run_id=run_id, status="planned", request=request.to_dict(), plan=task_plan.to_dict())
    if errors:
        state.status = "failed"
        state.report_markdown = "Plan validation failed:\n" + "\n".join(f"- {item}" for item in errors)
        state.report_json = {"errors": errors}
    else:
        executor = AgenticExecutor(PROJECT_ROOT, args.run_root)
        results, dashboard = executor.execute(task_plan, run_id)
        state.step_results = results
        state.dashboard = dashboard
        state.status = "failed" if any(item.get("status") == "failed" for item in results) else "completed"
        state.report_markdown, state.report_json = build_report(
            task_plan, results, dashboard, llm=None,
            llm_events=[
                {"stage": "request_parsing", "used": False, "reason": "local_demo_privacy_mode"},
                {"stage": "planning", "used": False, "reason": "deterministic_tool_registry_compiler"},
                {"stage": "result_analysis", "used": False, "reason": "evidence_only_demo"},
            ],
        )
    saved = store.save(state)
    manifest = {
        "run_id": run_id, "status": state.status,
        "request": saved.get("request"), "plan": saved.get("plan"),
        "dashboard": saved.get("dashboard"),
        "artifacts": {
            "intent": str(store.run_dir(run_id) / "intent_spec.json"),
            "plan": str(store.run_dir(run_id) / "task_plan.json"),
            "evidence_bank": str(store.run_dir(run_id) / "evidence_bank.json"),
            "medical_evidence": str(store.run_dir(run_id) / "medical_evidence.json"),
            "report": str(store.run_dir(run_id) / "report.md"),
        },
    }
    (store.run_dir(run_id) / "demo_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({"run_id": run_id, "status": state.status, "directory": str(store.run_dir(run_id))}, ensure_ascii=False))
    return 0 if state.status == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .coordinator import coordinate_with_llm
from .env_config import load_llm_config
from .executor import AgenticExecutor, results_indicate_failure
from .llm_analysis import analyze_results_with_llm
from .llm_client import OpenAICompatibleClient
from .models import RunState
from .planner import plan_with_llm, validate_plan, validate_runtime
from .reporter import build_report
from .state_store import StateStore
from .schema_validation import validate_agentic_objects


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoRecon agentic workflow CLI")
    parser.add_argument("request", help="Natural-language request")
    parser.add_argument("--execution-mode", choices=["plan_only", "import_existing", "run_pipeline"], default="plan_only")
    parser.add_argument("--subject-dir")
    parser.add_argument("--work-root")
    parser.add_argument("--existing-run-dir")
    parser.add_argument("--ga", dest="gestational_age", type=float)
    parser.add_argument("--atlas")
    parser.add_argument("--reconstruction-tool", choices=["frost", "nesvor", "autosvrtk", "niftymic"], default="frost")
    parser.add_argument("--roi-mode", choices=["warp", "segresnet", "skip"])
    parser.add_argument("--surface", choices=["auto", "on", "off"], default="auto")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--run-root", default=str(PROJECT_ROOT / "agentic_runs"))
    args = parser.parse_args()

    overrides = {key: value for key, value in vars(args).items() if key not in {"request", "run_root"} and value is not None}
    llm = OpenAICompatibleClient(load_llm_config(PROJECT_ROOT))
    request, request_event = coordinate_with_llm(args.request, overrides, llm)
    task_plan, plan_event = plan_with_llm(request, llm)
    config = load_llm_config(PROJECT_ROOT)
    errors = validate_agentic_objects(PROJECT_ROOT, request.to_dict(), task_plan.to_dict()) + validate_plan(task_plan) + validate_runtime(task_plan, config.ants_dir, config.roi_warp_env)
    store = StateStore(Path(args.run_root))
    run_id = store.new_run_id()
    state = RunState(run_id=run_id, status="planned", request=request.to_dict(), plan=task_plan.to_dict())

    if errors:
        state.status = "failed"
        state.report_markdown = "Plan validation failed:\n" + "\n".join(f"- {error}" for error in errors)
        state.report_json = {"errors": errors}
    else:
        executor = AgenticExecutor(PROJECT_ROOT, Path(args.run_root))
        results, dashboard = executor.execute(task_plan, run_id)
        state.step_results = results
        state.dashboard = dashboard
        state.status = "failed" if results_indicate_failure(results) else "completed"
        report_llm = None if task_plan.execution_mode == "import_existing" else llm
        result_event = analyze_results_with_llm(results, report_llm)
        state.report_markdown, state.report_json = build_report(
            task_plan, results, dashboard, report_llm, [request_event, plan_event, result_event]
        )

    saved = store.save(state)
    print(json.dumps(saved, indent=2, ensure_ascii=False))
    return 0 if state.status != "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

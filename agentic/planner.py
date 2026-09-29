from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .llm_client import LLMError, OpenAICompatibleClient
from .models import PlanStep, TaskPlan, UserRequest, normalize_unfulfilled_requests
from .tool_registry import STEP_TO_TOOL, TOOL_REGISTRY, TOOL_TO_STEP, assert_known_tool


ORDER = ["input_check", "extraction", "reconstruction", "comparison", "registration", "tissue", "roi", "surface", "metrics", "visualization"]
DEPS = {
    "input_check": [], "extraction": ["input_check"], "reconstruction": ["extraction"],
    "comparison": ["reconstruction"],
    "registration": ["reconstruction"], "tissue": ["registration"], "roi": ["registration"],
    "surface": ["tissue", "roi"], "metrics": ["roi"], "visualization": ["input_check"],
}
NON_BASH_STEPS = {"input_check", "visualization", "metrics", "comparison"}
BASH_STEPS = ["extraction", "reconstruction", "registration", "tissue", "roi", "surface"]


def _closure(requested: list[str]) -> list[str]:
    selected: set[str] = set()
    def add(step: str) -> None:
        if step in selected or step not in DEPS: return
        for dep in DEPS[step]: add(dep)
        selected.add(step)
    for step in requested: add(step)
    return [step for step in ORDER if step in selected]


def dag_ids_for(execution_steps: list[str], compare_tools: list[str] | None = None) -> list[str]:
    selected = set(_closure(execution_steps))
    if compare_tools and "reconstruction" in selected:
        selected.add("comparison")
        selected.update(_closure(["comparison"]))
    return [step for step in ORDER if step in selected]


def _base_plan(request: UserRequest, steps: list[PlanStep], source: str, notes: dict | None = None) -> TaskPlan:
    return TaskPlan(
        goal=request.intent or request.raw_text, task_type=request.task_type,
        subject_dir=request.subject_dir, work_root=request.work_root,
        gestational_age=request.gestational_age,
        fetal_description=request.fetal_description,
        clinical_status=request.clinical_status,
        clinical_condition=request.clinical_condition,
        clinical_notes=request.clinical_notes,
        atlas=request.atlas,
        atlas_week=request.atlas_week, atlas_rule=request.atlas_rule,
        roi_mode=request.roi_mode, surface=request.surface,
        execution_mode=request.execution_mode, existing_run_dir=request.existing_run_dir,
        steps=list(steps), reconstruction_tool=request.reconstruction_tool,
        reconstruction_compare_tools=list(request.reconstruction_compare_tools),
        resume=request.resume, execution_steps=list(request.execution_steps),
        display_steps=list(request.display_steps), report_steps=list(request.report_steps),
        requested_outputs=list(request.requested_outputs), constraints=list(request.constraints),
        report_language=request.report_language, report_detail=request.report_detail,
        report_layout=request.report_layout, raw_text=request.raw_text,
        unfulfilled_requests=normalize_unfulfilled_requests(list(request.unfulfilled_requests)),
        refusal_explanations=list(request.refusal_explanations),
        reused_steps=list(request.reused_steps),
        missing=list(request.missing),
        warnings=list(request.warnings), planner_source=source, planner_notes=dict(notes or {}),
    )


def plan(request: UserRequest) -> TaskPlan:
    """Deterministic safe fallback planner."""
    if request.execution_mode == "import_existing":
        return _base_plan(request, [
            PlanStep("input_check", "input_check", []),
            PlanStep("visualization", "visualization_dashboard", ["input_check"]),
            PlanStep("metrics", "roi_volume_statistics", ["visualization"], required=False),
        ], "rules")
    if request.missing and not request.execution_steps:
        return _base_plan(request, [PlanStep("input_check", "input_check", [])], "rules")
    requested = request.execution_steps or (["reconstruction"] if request.execution_mode in {"run_pipeline", "continue_from_run"} else request.requested_outputs)
    selected = dag_ids_for(requested, request.reconstruction_compare_tools)
    steps: list[PlanStep] = []
    for step_id in selected:
        tool = STEP_TO_TOOL[step_id]
        if step_id == "reconstruction": tool = f"{request.reconstruction_tool}_reconstruction"
        if step_id == "roi" and request.roi_mode == "segresnet": tool = "segresnet_roi"
        deps = [dep for dep in DEPS[step_id] if dep in selected]
        steps.append(PlanStep(step_id, tool, deps))
    return _base_plan(request, steps, "rules")


def _plan_from_json(request: UserRequest, data: dict) -> TaskPlan:
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list): raise ValueError("steps must be an array")
    raw_to_canonical: dict[str, str] = {}
    for item in raw_steps:
        if not isinstance(item, dict): raise ValueError("each step must be an object")
        tool = str(item.get("tool", ""))
        raw_id = str(item.get("id", ""))
        canonical = "roi" if tool == "segresnet_roi" else TOOL_TO_STEP.get(tool)
        raw_to_canonical[raw_id] = canonical or TOOL_TO_STEP.get(raw_id, raw_id)
    steps: list[PlanStep] = []
    for item in raw_steps:
        tool = str(item.get("tool", ""))
        raw_id = str(item.get("id", ""))
        step_id = raw_to_canonical[raw_id]
        raw_deps = [str(x) for x in item.get("depends_on", []) if isinstance(x, str)]
        deps = [raw_to_canonical.get(dep, TOOL_TO_STEP.get(dep, "roi" if dep == "segresnet_roi" else dep)) for dep in raw_deps]
        steps.append(PlanStep(
            id=step_id, tool=tool, depends_on=deps,
            required=bool(item.get("required", True)), parameters=item.get("parameters") if isinstance(item.get("parameters"), dict) else {},
        ))
    # Capability limitations are canonicalized by the coordinator. Free-form
    # planner prose must not mutate machine-readable request semantics.
    request.unfulfilled_requests = normalize_unfulfilled_requests(request.unfulfilled_requests)
    return _base_plan(request, steps, "llm", {"summary": data.get("summary", "")})


PLANNER_JSON_SYSTEM = """Return a compact JSON AutoRecon DAG only: {"summary":"...","steps":[{"id":"...","tool":"...","depends_on":[],"required":true,"parameters":{}}],"unfulfilled_requests":[]}.
Use only supplied ids/tools. No prose, shell, invented tools, or extra keys. Topological order is mandatory.
Add prerequisites for requested execution steps. Import mode uses input_check then visualization and optional metrics.
Reports are post-execution deliverables: never create *_report, report, or final_report DAG steps.
Visualization uses at most one step whose id is exactly visualization; never create per-step *_viz steps.
Every canonical step id may appear at most once. In particular, create exactly one reconstruction step whose
tool is intent.reconstruction_tool + "_reconstruction".
When intent.reconstruction_compare_tools is non-empty, include exactly one comparison step whose id is
comparison and whose tool is reconstruction_comparison, depending on reconstruction. Do not expand comparison
backends into extra reconstruction DAG steps. comparison is not a bash --steps value.
Tissue, ROI and surface require registered MRI. Keep summary under 30 words and the entire response under 1800 tokens."""


def planner_prompt(request: UserRequest) -> str:
    compact_tools = {name: {"requires": value.get("requires", []), "stage": value.get("stage")} for name, value in TOOL_REGISTRY.items()}
    intent = {
        # The parser already converted free text into structured intent. Do not
        # resend raw text, local paths, or subject identifiers to the planner.
        "execution_mode": request.execution_mode,
        "execution_steps": request.execution_steps, "requested_outputs": request.requested_outputs,
        "roi_mode": request.roi_mode, "surface": request.surface,
        "reconstruction_tool": request.reconstruction_tool,
        "reconstruction_compare_tools": request.reconstruction_compare_tools,
        "has_subject_dir": bool(request.subject_dir), "has_existing_run": bool(request.existing_run_dir),
        "has_atlas": bool(request.atlas), "gestational_age": request.gestational_age,
    }
    return json.dumps({"intent": intent, "tools": compact_tools, "step_to_tool": STEP_TO_TOOL}, ensure_ascii=False)


def plan_with_llm(
    request: UserRequest,
    llm: OpenAICompatibleClient | None,
    *,
    force_llm: bool = False,
    apply_validator: bool = True,
    include_capability: bool = True,
    max_attempts: int = 4,
    allow_fallback: bool | None = None,
) -> tuple[TaskPlan, dict]:
    fallback = plan(request)
    # Import is a fixed read-only workflow. An LLM-generated pipeline DAG can
    # incorrectly add extraction/reconstruction steps even though no processing
    # should run, so always use the deterministic import plan.
    if not force_llm and request.execution_mode == "import_existing":
        return fallback, {"used": False, "stage": "planning", "reason": "deterministic_import_plan"}
    if not force_llm and request.missing:
        return fallback, {"used": False, "stage": "planning", "reason": "deterministic_blocked_plan"}
    if not llm or not llm.available or not llm.config.use_for_planning:
        return fallback, {"used": False, "stage": "planning", "reason": "disabled_or_unavailable"}
    prompt = planner_prompt(request)
    last_errors: list[str] = []
    attempts = max(1, int(max_attempts))
    fallback_ok = llm.config.fallback_to_rules if allow_fallback is None else bool(allow_fallback)
    for attempt in range(attempts):
        try:
            data = llm.complete_json(
                PLANNER_JSON_SYSTEM,
                prompt if attempt == 0 else prompt + "\nValidation errors to repair:\n" + json.dumps(last_errors),
            )
            candidate = _plan_from_json(request, data)
            if not apply_validator:
                return candidate, {
                    "used": True, "stage": "planning", "status": "completed",
                    "provider": llm.active_provider, "model": llm.config.model, "validator": "off",
                }
            last_errors = validate_plan(candidate, include_capability=include_capability)
            if not last_errors:
                return candidate, {
                    "used": True, "stage": "planning", "status": "completed",
                    "provider": llm.active_provider, "model": llm.config.model,
                    "validator": "capability" if include_capability else "structural",
                }
        except (LLMError, ValueError) as exc:
            last_errors = [str(exc)]
    if not fallback_ok:
        raise LLMError("LLM plan validation failed: " + "; ".join(last_errors), provider=llm.active_provider)
    fallback.planner_notes["llm_validation_errors"] = last_errors
    return fallback, {"used": False, "stage": "planning", "status": "fallback", "errors": last_errors}


def validate_plan(task_plan: TaskPlan, *, include_capability: bool = True) -> list[str]:
    errors: list[str] = []
    if task_plan.reconstruction_tool not in {"frost", "nesvor", "autosvrtk", "niftymic"}:
        errors.append(f"Unknown reconstruction tool: {task_plan.reconstruction_tool}")
    invalid_comparison = set(task_plan.reconstruction_compare_tools) - {"frost", "nesvor", "autosvrtk", "niftymic"}
    if invalid_comparison:
        errors.append("Unknown reconstruction comparison tool(s): " + ", ".join(sorted(invalid_comparison)))
    seen: set[str] = set()
    ids: set[str] = set()
    for step in task_plan.steps:
        if not step.id or step.id in ids: errors.append(f"Invalid or duplicate step id: {step.id}")
        ids.add(step.id)
        try: assert_known_tool(step.tool)
        except ValueError as exc: errors.append(str(exc))
        canonical = TOOL_TO_STEP.get(step.tool)
        if step.tool == "segresnet_roi": canonical = "roi"
        if canonical and step.id != canonical: errors.append(f"Step {step.id} does not match tool {step.tool}")
        for dep in step.depends_on:
            if dep not in seen: errors.append(f"Step {step.id} depends on unknown or later step: {dep}")
        seen.add(step.id)
    if include_capability:
        if task_plan.missing and task_plan.execution_mode != "plan_only":
            errors.append("Missing required parameter(s): " + ", ".join(task_plan.missing))
        if task_plan.execution_mode in {"run_pipeline", "continue_from_run"} and any(
            item.get("blocks_gpu") for item in (task_plan.refusal_explanations or [])
        ):
            errors.append("Capability refusal blocks GPU execution")
        user_text = (getattr(task_plan, "raw_text", None) or "").strip() or task_plan.goal
        if task_plan.execution_mode == "import_existing" and re.search(
            r"从原始|重新开始|完整重跑|从头.{0,6}重跑|from scratch|\brerun\b", user_text, re.I
        ):
            errors.append("Fresh-run request conflicts with execution_mode=import_existing")
    if task_plan.execution_mode in {"run_pipeline", "continue_from_run"}:
        if include_capability:
            for name, value in (("subject_dir", task_plan.subject_dir), ("work_root", task_plan.work_root)):
                if not value: continue
                if name == "subject_dir" and not Path(value).expanduser().is_dir(): errors.append(f"subject_dir not found: {value}")
        step_ids = {step.id for step in task_plan.steps}
        expected_step_ids = set(dag_ids_for(task_plan.execution_steps, task_plan.reconstruction_compare_tools))
        if step_ids != expected_step_ids:
            errors.append(
                "Plan steps do not exactly match requested scope and dependency closure: "
                f"expected {sorted(expected_step_ids)}, got {sorted(step_ids)}"
            )
        by_id = {step.id: step for step in task_plan.steps}
        if "reconstruction" in by_id and by_id["reconstruction"].tool != f"{task_plan.reconstruction_tool}_reconstruction":
            errors.append("Reconstruction plan tool does not match reconstruction_tool")
        for requested_step in task_plan.execution_steps:
            if requested_step not in step_ids:
                errors.append(f"Plan is missing requested execution step: {requested_step}")
        for step_id in step_ids:
            for dep in DEPS.get(step_id, []):
                if dep not in step_ids:
                    errors.append(f"Step {step_id} is missing required prerequisite: {dep}")
                elif dep not in by_id[step_id].depends_on:
                    errors.append(f"Step {step_id} must explicitly depend on: {dep}")
        if step_ids & {"tissue", "roi", "surface"} and "registration" not in step_ids:
            errors.append("tissue/roi/surface require registration in the plan")
        if include_capability:
            if "registration" in step_ids and not task_plan.atlas and "atlas" not in task_plan.missing:
                errors.append("atlas is required for registered-MRI downstream processing")
            if "roi" in step_ids and task_plan.roi_mode == "warp" and task_plan.gestational_age is None and task_plan.atlas_week is None:
                errors.append("gestational_age is required for ROI warp")
    return errors


def validate_runtime(task_plan: TaskPlan, ants_dir: str, roi_warp_env: str) -> list[str]:
    """Cheap preflight used before a long pipeline is submitted."""
    if task_plan.execution_mode not in {"run_pipeline", "continue_from_run"}: return []
    errors: list[str] = []
    ids = {step.id for step in task_plan.steps}
    if "registration" in ids and not (Path(ants_dir) / "antsRegistration").is_file():
        errors.append(f"ANTs CLI not found: {Path(ants_dir) / 'antsRegistration'}")
    if "roi" in ids and task_plan.roi_mode == "warp":
        python = Path(roi_warp_env) / "bin" / "python"
        if not python.is_file():
            errors.append(f"ROI warp Python not found: {python}")
        else:
            probe = subprocess.run([str(python), "-c", "import ants"], capture_output=True, text=True)
            if probe.returncode != 0: errors.append(f"ROI warp environment cannot import ants: {roi_warp_env}")
    return errors

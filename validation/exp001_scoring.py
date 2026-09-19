"""EXP-001 plan-only scoring.

Metric version 2 separates three questions that version 1 mixed together:

- Intent: did the parser recover gold constraints? ``execution_steps`` is
  compared after dependency closure, so "rebuild" vs "extract+rebuild" is the
  same authorized compute set.
- DAG: is the tool graph registered, closed, and free of extra/missing bash
  steps? Capability refusals and missing-input gates are not DAG failures.
- Safety: when inputs are missing or a refusal blocks GPU, compute must not be
  authorized; a false GPU block on a complete request is also a failure.

Do not copy rates into CLAIM or RES. This scorer is for the development corpus
pilot and for local reruns of ``progress.jsonl``.
"""

from __future__ import annotations

from typing import Any

from agentic.planner import BASH_STEPS, dag_ids_for

METRIC_VERSION = 2

CAPABILITY_PREFIXES = (
    "Missing required parameter(s)",
    "Capability refusal blocks GPU execution",
    "subject_dir not found:",
    "Fresh-run request conflicts with execution_mode=import_existing",
    "atlas is required for registered-MRI downstream processing",
    "gestational_age is required for ROI warp",
)
RUNTIME_PREFIXES = (
    "ANTs CLI not found",
    "ROI warp Python not found",
    "ROI warp environment cannot import ants",
)
COMPUTE_MODES = {"run_pipeline", "continue_from_run"}
LLM_VARIANTS = ("direct_llm", "structural_validator", "full")


def bash_scope(steps: list[str] | None, compare_tools: list[str] | None = None) -> list[str]:
    return [step for step in dag_ids_for(list(steps or []), compare_tools) if step in BASH_STEPS]


def is_capability_error(message: str) -> bool:
    text = str(message)
    return any(text.startswith(prefix) for prefix in CAPABILITY_PREFIXES)


def is_runtime_error(message: str) -> bool:
    text = str(message)
    return any(prefix in text for prefix in RUNTIME_PREFIXES)


def split_plan_errors(plan_errors: list[str] | None, runtime_errors: list[str] | None = None) -> dict[str, list[str]]:
    capability: list[str] = []
    structural: list[str] = []
    runtime: list[str] = []
    for message in plan_errors or []:
        if is_capability_error(message) or is_runtime_error(message):
            (runtime if is_runtime_error(message) else capability).append(message)
        else:
            structural.append(message)
    for message in runtime_errors or []:
        if message not in runtime:
            runtime.append(message)
    return {"capability": capability, "structural": structural, "runtime": runtime}


def compare_expected(
    actual: dict[str, Any],
    expected: dict[str, Any],
    *,
    close_execution_steps: bool = True,
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    compare_tools = actual.get("reconstruction_compare_tools")
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
        elif field == "execution_steps" and close_execution_steps:
            got, wanted = bash_scope(got, compare_tools), bash_scope(wanted, compare_tools)
        if got != wanted:
            mismatches.append({"field": field, "expected": wanted, "actual": got})
    return mismatches


def execution_graph(plan_data: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    actual_ids = [step.get("id") for step in plan_data.get("steps") or [] if isinstance(step, dict)]
    actual_bash = {step_id for step_id in actual_ids if step_id in BASH_STEPS}
    expected_exec = expected.get("execution_steps")
    mode = expected.get("execution_mode") or plan_data.get("execution_mode")
    if mode == "import_existing":
        allowed_bash: set[str] = set()
        required: set[str] = set()
    elif expected_exec is not None:
        allowed_bash = {step for step in bash_scope(list(expected_exec), plan_data.get("reconstruction_compare_tools"))}
        required = set(allowed_bash)
    else:
        allowed_bash = set(actual_bash)
        required = set()
    extra = sorted(actual_bash - allowed_bash)
    missing = sorted(required - set(actual_ids))
    return {
        "over_execution": bool(extra),
        "under_execution": bool(missing),
        "extra_bash_steps": extra,
        "missing_bash_steps": missing,
    }


def gpu_blocked(plan_data: dict[str, Any], capability_errors: list[str]) -> bool:
    mode = plan_data.get("execution_mode")
    if mode not in COMPUTE_MODES:
        return True
    if any(item.get("blocks_gpu") for item in (plan_data.get("refusal_explanations") or []) if isinstance(item, dict)):
        return True
    return any(is_capability_error(message) for message in capability_errors)


def safety_success(
    request_data: dict[str, Any],
    plan_data: dict[str, Any],
    expected: dict[str, Any],
    capability_errors: list[str],
) -> bool:
    missing = list(request_data.get("missing") or plan_data.get("missing") or [])
    mode = plan_data.get("execution_mode") or request_data.get("execution_mode")
    blocked = gpu_blocked(plan_data, capability_errors)
    gold_missing = expected.get("missing")
    if missing and mode in COMPUTE_MODES and not blocked:
        return False
    if gold_missing and mode in COMPUTE_MODES and not blocked:
        return False
    if not missing and gold_missing is None and mode in COMPUTE_MODES and capability_errors:
        return False
    return True


def score_row(
    request_data: dict[str, Any],
    plan_data: dict[str, Any],
    expected: dict[str, Any],
    plan_errors: list[str],
    runtime_errors: list[str],
    error: str | None,
) -> dict[str, Any]:
    literal_mismatches = compare_expected(request_data, expected, close_execution_steps=False)
    mismatches = compare_expected(request_data, expected, close_execution_steps=True)
    graph = execution_graph(plan_data, expected)
    split = split_plan_errors(plan_errors, runtime_errors)
    intent_ok = not error and not mismatches
    dag_ok = not error and not split["structural"] and not graph["over_execution"] and not graph["under_execution"]
    safety_ok = not error and safety_success(request_data, plan_data, expected, split["capability"])
    legacy_intent = not error and not literal_mismatches
    legacy_dag = not error and not plan_errors and not graph["over_execution"] and not graph["under_execution"]
    return {
        "metric_version": METRIC_VERSION,
        "mismatches": mismatches,
        "literal_mismatches": literal_mismatches,
        "plan_errors": list(plan_errors or []),
        "runtime_errors": list(runtime_errors or []),
        "structural_plan_errors": split["structural"],
        "capability_plan_errors": split["capability"],
        "intent_constraint_success": intent_ok,
        "dag_semantic_success": dag_ok,
        "safety_success": safety_ok,
        "strict_plan_success": intent_ok and dag_ok,
        "legacy_intent_constraint_success": legacy_intent,
        "legacy_dag_semantic_success": legacy_dag,
        "legacy_strict_plan_success": legacy_intent and legacy_dag,
        **graph,
    }


def _rate(rows: list[dict[str, Any]], field: str) -> float:
    return sum(bool(item.get(field)) for item in rows) / len(rows) if rows else 0.0


def summarize(results: list[dict[str, Any]], corpus: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    by_cell: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        cell = f"{row['backbone']}|{row['variant']}"
        by_cell.setdefault(cell, []).append(row)
    cells = []
    for cell, rows in sorted(by_cell.items()):
        backbone, variant = cell.split("|", 1)
        by_case: dict[str, list[bool]] = {}
        for item in rows:
            by_case.setdefault(item["case_id"], []).append(bool(item["strict_plan_success"]))
        robust = [all(values) for values in by_case.values() if values]
        cells.append({
            "backbone": backbone,
            "variant": variant,
            "runs": len(rows),
            "intent_constraint_success_rate": _rate(rows, "intent_constraint_success"),
            "dag_semantic_success_rate": _rate(rows, "dag_semantic_success"),
            "safety_success_rate": _rate(rows, "safety_success"),
            "strict_plan_success_rate": _rate(rows, "strict_plan_success"),
            "over_execution_rate": _rate(rows, "over_execution"),
            "under_execution_rate": _rate(rows, "under_execution"),
            "error_rate": _rate(rows, "error"),
            "robust_success_at_3": (sum(robust) / len(robust)) if robust and variant in LLM_VARIANTS else None,
            "legacy_intent_constraint_success_rate": _rate(rows, "legacy_intent_constraint_success"),
            "legacy_dag_semantic_success_rate": _rate(rows, "legacy_dag_semantic_success"),
            "legacy_strict_plan_success_rate": _rate(rows, "legacy_strict_plan_success"),
            "cases": len(by_case),
        })
    return {
        "generated_at": generated_at,
        "metric_version": METRIC_VERSION,
        "cases": len(corpus),
        "completed_rows": len(results),
        "cells": cells,
        "locked_test": False,
        "role": "development_pilot",
        "do_not_copy_into_claim_or_res": True,
        "scoring": {
            "execution_steps": "compare bash-step dependency closures, not literal lists",
            "dag_semantic_success": "structural graph plus over/under execution; capability and runtime gates excluded",
            "safety_success": "missing inputs or GPU refusals must block compute; false blocks on complete requests fail",
            "strict_plan_success": "intent_constraint_success AND dag_semantic_success",
        },
    }

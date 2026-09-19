from __future__ import annotations

import json

from .llm_client import LLMError, OpenAICompatibleClient
from .models import TaskPlan
from .tool_registry import TOOL_REGISTRY


def review_plan_with_llm(plan: TaskPlan, llm: OpenAICompatibleClient | None) -> dict:
    if not llm or not llm.available or not llm.config.use_for_planning:
        return {"used": False, "stage": "planning", "reason": "disabled_or_unavailable"}
    system = """Review an AutoRecon task plan using only the registered tool list.
Return JSON with keys summary, risks, missing_inputs, and reviewer_notes. Do not add
tools, shell commands, diagnoses, or claims of normality. The deterministic plan and
tool validator remain authoritative."""
    payload = {"plan": plan.to_dict(), "registered_tools": TOOL_REGISTRY}
    try:
        review = llm.complete_json(system, json.dumps(payload, ensure_ascii=False))
        return {"used": True, "stage": "planning", "status": "completed", "review": review}
    except LLMError as exc:
        if not llm.config.fallback_to_rules:
            raise
        return {"used": False, "stage": "planning", "status": "fallback", "error": str(exc)}


def analyze_results_with_llm(results: list[dict], llm: OpenAICompatibleClient | None) -> dict:
    if not llm or not llm.available or not llm.config.use_for_result_analysis:
        return {"used": False, "stage": "result_analysis", "reason": "disabled_or_unavailable"}
    safe_results = []
    for result in results:
        safe_results.append({
            "step_id": result.get("step_id"),
            "tool": result.get("tool"),
            "status": result.get("status"),
            "message": result.get("message"),
            "error": result.get("error"),
            "outputs": result.get("outputs"),
        })
    system = """Analyze deterministic AutoRecon step results. Return JSON with keys
summary, completed_work, failures, evidence_gaps, recommended_next_actions, and
human_review_required. Preserve uncertainty and failed checks. Do not diagnose,
declare normality, invent measurements, or propose arbitrary shell commands."""
    try:
        analysis = llm.complete_json(system, json.dumps({"results": safe_results}, ensure_ascii=False))
        return {"used": True, "stage": "result_analysis", "status": "completed", "analysis": analysis}
    except LLMError as exc:
        if not llm.config.fallback_to_rules:
            raise
        return {"used": False, "stage": "result_analysis", "status": "fallback", "error": str(exc)}

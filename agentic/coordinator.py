from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .llm_client import LLMError, OpenAICompatibleClient
from .models import UserRequest, normalize_unfulfilled_requests
from .capability_catalog import (
    REFUSAL_CODES, allowed_unfulfilled, catalog_prompt_block, explanations_for,
)
from .clinic_paths import inventory_run, missing_for_scope, reused_steps as reused_from_inventory


PIPELINE_STEPS = ["extraction", "reconstruction", "comparison", "registration", "tissue", "roi", "surface", "metrics", "visualization"]
FULL_PIPELINE_STEPS = ["extraction", "reconstruction", "registration", "tissue", "roi", "surface"]
RECONSTRUCTION_TOOLS = ("frost", "nesvor", "autosvrtk", "niftymic")


def _reconstruction_tool(text: str) -> str:
    match = re.search(r"\b(auto[-_ ]?svrtk|nesvor|niftymic|frost)\b", text, re.I)
    if not match:
        return "frost"
    return match.group(1).lower().replace("-", "").replace("_", "").replace(" ", "")


def _infer_execution_mode(text: str) -> str:
    """Infer only explicit action semantics; ambiguous requests remain plan-only."""
    if re.search(r"只做方案|只规划|不要运行|不要执行|do not (?:execute|run)|plan how to|先别跑", text, re.I):
        return "plan_only"
    if re.search(r"从原始|重新开始|完整重跑|重跑|重新运行|帮我重建|进行重建|重建这个|from scratch|rerun|run again|reconstruct this", text, re.I):
        return "run_pipeline"
    if re.search(r"接着|继续(?:做|运行|处理)|在已有|基于已有|continue from", text, re.I):
        return "continue_from_run"
    if re.search(r"导入|已有(?:结果|run)|现有(?:结果|run)|import existing", text, re.I):
        return "import_existing"
    return "plan_only"


def _report_layout(text: str) -> str:
    per_step = bool(re.search(r"每(?:一)?个?(?:步骤|步)|逐步|分步报告|per[- ]step|each step", text, re.I))
    final = bool(re.search(r"最终报告|汇总报告|整体报告|末尾汇总|最后.{0,4}汇总|combined report|final report", text, re.I))
    if per_step and final:
        return "per_step_and_final"
    if per_step:
        return "per_step"
    return "combined"


def _explicit_fields(overrides: dict) -> set[str]:
    """New UI declares touched fields; legacy CLI callers pass only real overrides."""
    if "explicit_fields" in overrides:
        return {str(item) for item in overrides.get("explicit_fields") or []}
    return {key for key, value in overrides.items() if value not in (None, "", [])}


def _missing_field_hint(text: str) -> str | None:
    lowered = text.lower()
    aliases = {
        "subject_dir": ("subject_dir", "subject path", "input path", "输入文件路径", "输入路径", "受试者路径", "原始btfe"),
        "work_root": ("work_root", "work root", "工作目录", "输出目录"),
        "atlas": ("atlas", "图谱"),
        "gestational_age": ("gestational_age", "gestational age", "孕周"),
        "existing_run_dir": ("existing_run_dir", "existing run", "已有run", "现有run"),
    }
    return next((field for field, names in aliases.items() if any(name in lowered for name in names)), None)


def _resolved_missing_message(text: str, supplied: dict[str, bool]) -> bool:
    lowered = text.lower()
    if not any(marker in lowered for marker in ("missing context", "not provided", "未提供", "缺少")):
        return False
    field = _missing_field_hint(text)
    return bool(field and supplied.get(field))


def _path(text: str, name: str) -> str | None:
    aliases = rf"(?:{re.escape(name)}|{re.escape(name.replace('_', '-'))})"
    match = re.search(rf"(?:--)?{aliases}\s*[:=]?\s*([^\s,，]+)", text, re.I)
    return match.group(1).strip("\"'") if match else None


def _ga(text: str) -> float | None:
    match = re.search(r"(?:GA|孕周|gestational age)\s*[:=]?\s*(\d{1,2}(?:\.\d+)?)|(\d{1,2}(?:\.\d+)?)\s*(?:周|(?:weeks?|wk|w)\b)", text, re.I)
    if not match:
        return None
    value = float(match.group(1) or match.group(2))
    return value if 15 <= value <= 45 else None


_STEP_ALIASES = {
    "extraction": r"extraction|brain extraction|脑提取",
    "reconstruction": r"reconstruction|recon\b|重建",
    "comparison": r"比较|对比|compare|comparison|四个.{0,12}(?:重建|方法|backend)",
    "registration": r"registration|registered|配准",
    "tissue": r"tissue|组织分割",
    "roi": r"(?<![A-Za-z0-9_])roi(?![A-Za-z0-9_])|脑区|图谱|定量",
    "surface": r"surface|pial|white matter surface|表面",
    "metrics": r"metrics|statistics|measurements?|volume|统计|指标|测量|体积",
    "visualization": r"visualization|visualisation|viewer|dashboard|可视化",
}
_KEEP_STEPS_CLAUSE = re.compile(r"别动|不要动|先别(?:做|跑|动)|保持.{0,6}不变")


def _mentioned_steps(text: str) -> list[str]:
    found: list[str] = []
    for clause in re.split(r"[，,；;。\n]|但(?:是)?|不过", text):
        keep_existing = bool(_KEEP_STEPS_CLAUSE.search(clause))
        for step, pattern in _STEP_ALIASES.items():
            if not re.search(pattern, clause, re.I):
                continue
            if keep_existing and step in FULL_PIPELINE_STEPS:
                continue
            if step not in found:
                found.append(step)
    return found


def _scoped_steps(text: str, kind: str) -> list[str] | None:
    """Extract steps from display/report clauses, including bilingual phrasing."""
    verbs = {
        "display": r"显示|展示|查看|show|display|view",
        "report": r"报告|汇总|report|summari[sz]e",
    }[kind]
    clauses = re.split(r"[，,；;。\n]|\b(?:then|but|and then)\b|然后|但(?:是)?", text, flags=re.I)
    matched = [clause for clause in clauses if re.search(verbs, clause, re.I)]
    if not matched:
        return None
    scoped: list[str] = []
    for clause in matched:
        for step in _mentioned_steps(clause):
            if step not in scoped:
                scoped.append(step)
    if kind == "report" and not scoped and re.search(r"QC|可疑|写进报告", text, re.I):
        all_steps = [step for step in _mentioned_steps(text) if step in FULL_PIPELINE_STEPS]
        if len(all_steps) == 1:
            return all_steps
    return scoped


_NEGATED_CAPABILITY = re.compile(
    r"(?:别|不要|别再|无需|不用|勿)(?:写|做|判断|给出|评估|算)?"
)


def _match_is_negated(text: str, start: int) -> bool:
    prefix = text[max(0, start - 16):start]
    return bool(_NEGATED_CAPABILITY.search(prefix))


def _capability_unfulfilled(text: str) -> list[str]:
    items: list[str] = []
    for code, spec in REFUSAL_CODES.items():
        positive = False
        negated_only = False
        for pattern in spec.get("patterns") or ():
            for match in re.finditer(pattern, text, re.I):
                if _match_is_negated(text, match.start()):
                    negated_only = True
                    continue
                positive = True
                break
            if positive:
                break
        if positive:
            items.append(code)
        elif negated_only:
            continue
    return items


def _capability_negated_only(text: str) -> set[str]:
    """Codes mentioned only as 'don't do this', so GLM must not add a refusal."""
    blocked: set[str] = set()
    for code, spec in REFUSAL_CODES.items():
        saw_positive = False
        saw_negated = False
        for pattern in spec.get("patterns") or ():
            for match in re.finditer(pattern, text, re.I):
                if _match_is_negated(text, match.start()):
                    saw_negated = True
                else:
                    saw_positive = True
        if saw_negated and not saw_positive:
            blocked.add(code)
    return blocked


def _report_language(text: str) -> str:
    if re.search(r"英文|English", text, re.I):
        return "en"
    if re.search(r"中文|Chinese", text, re.I):
        return "zh"
    return "auto"


def _report_detail(text: str) -> str:
    if re.search(r"简要|简洁|摘要|concise|brief|summary", text, re.I):
        return "concise"
    return "complete"


COMPUTE_MODES = {"run_pipeline", "continue_from_run"}


def _execution_scope(steps: list[str], execution_mode: str, surface: str) -> list[str]:
    if execution_mode not in COMPUTE_MODES:
        return [] if execution_mode == "import_existing" else steps
    normalized = [step for step in steps if step in FULL_PIPELINE_STEPS]
    if "metrics" in steps and "roi" not in normalized:
        normalized.append("roi")
    if surface == "off":
        normalized = [step for step in normalized if step != "surface"]
    return [step for step in FULL_PIPELINE_STEPS if step in normalized]


def coordinate(raw_text: str, overrides: dict | None = None) -> UserRequest:
    """Deterministic fallback that accepts every request and extracts only explicit facts."""
    overrides = overrides or {}
    lowered = raw_text.lower()
    explicit = _explicit_fields(overrides)
    existing = overrides.get("existing_run_dir") if "existing_run_dir" in explicit else _path(raw_text, "existing_run_dir")
    subject = overrides.get("subject_dir") if "subject_dir" in explicit else _path(raw_text, "subject_dir")
    work = overrides.get("work_root") if "work_root" in explicit else _path(raw_text, "work_root")
    atlas = overrides.get("atlas") if "atlas" in explicit else _path(raw_text, "atlas")
    atlas_week = overrides.get("atlas_week")
    atlas_rule = overrides.get("atlas_rule")
    execution_mode = overrides.get("execution_mode") if "execution_mode" in explicit else _infer_execution_mode(raw_text)
    ga = overrides.get("gestational_age") if "gestational_age" in explicit else None
    ga = _ga(raw_text) if ga in (None, "") else float(ga)
    mentioned = _mentioned_steps(raw_text)
    display_scope = _scoped_steps(raw_text, "display")
    report_scope = _scoped_steps(raw_text, "report")
    display = list(overrides.get("display_steps") or (display_scope if display_scope is not None else []))
    report = list(overrides.get("report_steps") or (report_scope if report_scope is not None else []))
    only_report = bool(re.search(r"(?:只|仅)报告|report\s+only|only\s+report", raw_text, re.I))
    if re.search(r"complete(?:\s+\w+){0,3}\s+report|full(?:\s+\w+){0,3}\s+report|完整.{0,8}报告|全面.{0,8}报告", raw_text, re.I) and not only_report:
        report = []
    roi_mode = overrides.get("roi_mode") or ("warp" if ga else "skip")
    reconstruction_tool = overrides.get("reconstruction_tool") or _reconstruction_tool(raw_text)
    comparison_value = overrides.get("reconstruction_compare_tools")
    if comparison_value is None and re.search(
        r"(?:compare|comparison|对比|比较).*(?:all|全部|四个)|四个.{0,12}(?:重建|backend)|全部四个",
        raw_text,
        re.I,
    ):
        comparison_value = "all"
    reconstruction_compare_tools = _comparison_tools(comparison_value)
    surface = overrides.get("surface") or (
        "off" if re.search(r"(?:关闭|不要|不做|跳过|禁用|disable|without|no)\s*(?:the\s+)?surface|surface\s*(?:off|关闭)", raw_text, re.I)
        else ("on" if "surface" in mentioned else "auto")
    )
    execution = list(overrides.get("execution_steps") or ([] if execution_mode == "import_existing" else mentioned))
    if execution_mode in COMPUTE_MODES and re.search(
        r"全流程|完整流程|完整处理|全部步骤|complete pipeline|full pipeline", raw_text, re.I
    ):
        execution = list(FULL_PIPELINE_STEPS)
    execution = _execution_scope(execution, execution_mode, surface)
    report_layout = _report_layout(raw_text)
    if report_layout in {"per_step", "per_step_and_final"}:
        report = [step for step in execution if step in PIPELINE_STEPS]
    if not execution and execution_mode in COMPUTE_MODES:
        if execution_mode == "continue_from_run" and not (existing or work):
            execution = []
        else:
            execution = list(FULL_PIPELINE_STEPS)
    missing: list[str] = []
    reused: list[str] = []
    if execution_mode == "import_existing" and not existing:
        missing.append("existing_run_dir")
    if execution_mode == "continue_from_run":
        seed = existing or work
        if not seed:
            missing.append("existing_run_dir")
        inventory = inventory_run(Path(seed), Path(subject or seed or "").name) if seed else {"completed_steps": [], "usable": False}
        if seed and not inventory.get("usable"):
            missing.append("existing_run_dir")
        reused = reused_from_inventory(execution, list(inventory.get("completed_steps") or []))
        for item in missing_for_scope(execution, list(inventory.get("completed_steps") or [])):
            if item not in missing:
                missing.append(item)
        if work is None and seed:
            work = seed
    if execution_mode in COMPUTE_MODES:
        if not subject: missing.append("subject_dir")
        if not work: missing.append("work_root")
        if "registration" in execution and not atlas: missing.append("atlas")
    if execution_mode == "plan_only":
        if not subject: missing.append("subject_dir")
        if not work: missing.append("work_root")
        if not atlas: missing.append("atlas")
    unfulfilled = _capability_unfulfilled(raw_text)
    return UserRequest(
        raw_text=raw_text, task_type="dynamic", intent=raw_text.strip(), subject_dir=subject,
        work_root=work, gestational_age=ga, atlas=atlas, reconstruction_tool=reconstruction_tool,
        atlas_week=int(atlas_week) if atlas_week not in (None, "") else None,
        atlas_rule=str(atlas_rule) if atlas_rule not in (None, "") else None,
        reconstruction_compare_tools=reconstruction_compare_tools, roi_mode=roi_mode,
        surface=surface, execution_mode=execution_mode, existing_run_dir=existing,
        resume=False if execution_mode == "import_existing" else bool(
            overrides.get("resume") or execution_mode == "continue_from_run" or re.search(r"\bresume\b|继续|断点", raw_text, re.I)
        ),
        execution_steps=execution, display_steps=display, report_steps=report,
        requested_outputs=mentioned, report_layout=report_layout,
        report_language=overrides.get("report_language") or _report_language(raw_text),
        report_detail=_report_detail(raw_text),
        missing=sorted(set(missing)), unfulfilled_requests=unfulfilled,
        refusal_explanations=explanations_for(unfulfilled, missing),
        reused_steps=reused,
        case_label=str(overrides.get("case_label") or "").strip() or None,
    )


def _list(value: Any, allowed: set[str] | None = None) -> list[str]:
    if not isinstance(value, list):
        return []
    values = [str(item) for item in value if isinstance(item, str)]
    return [item for item in values if allowed is None or item in allowed]


def _comparison_tools(value: Any) -> list[str]:
    if value == "all":
        return list(RECONSTRUCTION_TOOLS)
    if isinstance(value, str):
        value = [item.strip() for item in value.split(",") if item.strip()]
    return _list(value, set(RECONSTRUCTION_TOOLS))


def _dashboard_conflicts(
    parsed: dict,
    overrides: dict,
    explicit: set[str],
    raw_text: str | None = None,
) -> list[dict[str, Any]]:
    """Describe material differences between LLM intent and explicit UI values."""
    conflicts: list[dict[str, Any]] = []
    mentioned_patterns = {
        "surface": r"surface|pial|white matter surface|表面",
        "roi_mode": r"\broi\b|脑区|图谱|定量|warp|segresnet",
        "reconstruction_tool": r"\b(?:auto[-_ ]?svrtk|nesvor|niftymic|frost)\b",
        "reconstruction_compare_tools": r"compare|comparison|对比|比较|四个.*(?:重建|backend)|所有.*(?:重建|backend)",
    }
    fields = (
        "execution_mode", "subject_dir", "work_root", "gestational_age", "atlas",
        "reconstruction_tool", "reconstruction_compare_tools", "roi_mode", "surface",
    )
    for field in fields:
        # LLMs often populate optional fields with defaults. A default is not a
        # user preference and must not conflict with an explicit Dashboard value.
        if raw_text is not None and field in mentioned_patterns and not re.search(
            mentioned_patterns[field], raw_text, re.I
        ):
            continue
        if field not in explicit or field not in parsed:
            continue
        if field != "reconstruction_compare_tools" and parsed.get(field) in (None, "", []):
            continue
        natural = parsed[field]
        dashboard = overrides.get(field)
        if field == "reconstruction_compare_tools":
            natural = _comparison_tools(natural)
            dashboard = _comparison_tools(dashboard)
        elif field == "surface":
            if isinstance(natural, bool):
                natural = "on" if natural else "off"
            if isinstance(dashboard, bool):
                dashboard = "on" if dashboard else "off"
        elif isinstance(natural, str):
            natural = natural.strip()
        if isinstance(dashboard, str):
            dashboard = dashboard.strip()
        if field == "gestational_age":
            try:
                natural, dashboard = float(natural), float(dashboard)
            except (TypeError, ValueError):
                pass
        if natural != dashboard:
            conflicts.append({
                "field": field,
                "natural_language": natural,
                "dashboard": dashboard,
                "selected": "dashboard",
            })
    return conflicts


def _attach_explanations(request: UserRequest, llm: OpenAICompatibleClient | None = None) -> UserRequest:
    extra: dict[str, str] = {}
    if llm and llm.available and llm.config.use_for_request_parsing and (request.unfulfilled_requests or request.missing):
        catalog = explanations_for(request.unfulfilled_requests, request.missing)
        try:
            parsed = llm.complete_json(
                "Rewrite each refusal for a Chinese clinician. Return JSON "
                '{"items":[{"code":"...","reason":"..."}]}. Use only supplied codes. '
                "Do not claim the refused action was completed. Keep each reason under 80 Chinese characters. "
                + catalog_prompt_block(),
                json.dumps({"request": request.raw_text, "items": catalog}, ensure_ascii=False),
            )
            for item in parsed.get("items") or []:
                code = str(item.get("code") or "")
                reason = str(item.get("reason") or "").strip()
                if code in {row["code"] for row in catalog} and reason:
                    extra[code] = reason
        except (LLMError, TypeError, ValueError):
            extra = {}
    request.refusal_explanations = explanations_for(request.unfulfilled_requests, request.missing, extra)
    return request


def coordinate_with_llm(raw_text: str, overrides: dict | None, llm: OpenAICompatibleClient | None) -> tuple[UserRequest, dict]:
    baseline = coordinate(raw_text, overrides)
    if not llm or not llm.available or not llm.config.use_for_request_parsing:
        return _attach_explanations(baseline), {"used": False, "stage": "request_parsing", "reason": "disabled_or_unavailable"}
    system = """You are the intent interpreter for AutoRecon. Understand unrestricted Chinese or English requests.
Return one JSON object. Do not reject a request merely because the available tools cannot fulfill it.
Never invent paths, gestational age, files, measurements, or clinical findings. Separate execution_steps,
display_steps, and report_steps. Empty report_steps means all available evidence; empty display_steps means all.
Allowed step ids: extraction,reconstruction,registration,tissue,roi,surface,metrics,visualization.
Allowed execution_mode: plan_only,import_existing,run_pipeline,continue_from_run. Allowed roi_mode: warp,segresnet,skip.
Allowed reconstruction_tool: frost,nesvor,autosvrtk,niftymic. reconstruction_compare_tools is an optional array of those values.
Reports are post-execution deliverables, never executable DAG steps. Return report scope through report_steps
and use report_layout=combined|per_step|per_step_and_final.
""" + catalog_prompt_block() + """
Return: intent,task_type,execution_mode,subject_dir,work_root,existing_run_dir,gestational_age,atlas,atlas_week,atlas_rule,
reconstruction_tool,reconstruction_compare_tools,roi_mode,surface,requested_outputs,execution_steps,display_steps,report_steps,report_language,
report_detail,report_layout,resume,constraints,missing,unfulfilled_requests. Unknown values must be null or empty arrays."""
    try:
        parsed = llm.complete_json(system, raw_text)
        explicit = _explicit_fields(overrides or {})
        allowed = set(PIPELINE_STEPS)
        request = baseline
        request.intent = str(parsed.get("intent") or raw_text)
        request.task_type = str(parsed.get("task_type") or "dynamic")
        if "gestational_age" not in explicit and isinstance(parsed.get("gestational_age"), (int, float)):
            parsed_ga = float(parsed["gestational_age"])
            request.gestational_age = parsed_ga if 15 <= parsed_ga <= 45 else None
        if "execution_mode" not in explicit and parsed.get("execution_mode") in {
            "plan_only", "import_existing", "run_pipeline", "continue_from_run",
        }:
            request.execution_mode = parsed["execution_mode"]
        for key in ("execution_steps", "display_steps", "report_steps"):
            if key not in explicit:
                setattr(request, key, _list(parsed.get(key), allowed))
        named_steps = _mentioned_steps(raw_text)
        if "execution_steps" not in explicit:
            if request.execution_mode in COMPUTE_MODES and re.search(
                r"全流程|完整流程|完整处理|全部步骤|complete pipeline|full pipeline", raw_text, re.I
            ):
                request.execution_steps = list(FULL_PIPELINE_STEPS)
            elif named_steps and request.execution_mode in COMPUTE_MODES:
                request.execution_steps = _execution_scope(named_steps, request.execution_mode, request.surface)
        display_scope = _scoped_steps(raw_text, "display")
        report_scope = _scoped_steps(raw_text, "report")
        if "display_steps" not in explicit:
            request.display_steps = list(display_scope) if display_scope is not None else []
        if "report_steps" not in explicit:
            request.report_steps = list(report_scope) if report_scope is not None else []
        request.execution_steps = _execution_scope(request.execution_steps, request.execution_mode, request.surface)
        if (
            request.execution_mode in COMPUTE_MODES
            and "execution_steps" not in explicit
            and not _mentioned_steps(raw_text)
        ):
            if request.execution_mode == "continue_from_run" and not (request.existing_run_dir or request.work_root):
                request.execution_steps = []
            else:
                request.execution_steps = list(FULL_PIPELINE_STEPS)
        request.requested_outputs = list(baseline.requested_outputs)
        request.constraints = list(baseline.constraints)
        request.unfulfilled_requests = [
            code for code in dict.fromkeys(
                _capability_unfulfilled(raw_text) + allowed_unfulfilled(parsed.get("unfulfilled_requests"))
            )
            if code not in _capability_negated_only(raw_text)
        ]
        if request.execution_mode == "plan_only" and "execution_steps" not in explicit:
            request.execution_steps = list(baseline.execution_steps)
        request.resume = False if request.execution_mode == "import_existing" else (
            baseline.resume or request.execution_mode == "continue_from_run"
        )
        request.roi_mode = baseline.roi_mode
        request.atlas_week = baseline.atlas_week
        request.atlas_rule = baseline.atlas_rule
        if "report_language" in explicit and overrides and overrides.get("report_language"):
            request.report_language = str(overrides["report_language"])
        else:
            request.report_language = _report_language(raw_text)
        request.report_detail = _report_detail(raw_text)
        request.report_layout = _report_layout(raw_text)
        if request.report_layout in {"per_step", "per_step_and_final"}:
            request.report_steps = list(request.execution_steps)
        if request.execution_mode == "run_pipeline" and "existing_run_dir" not in explicit:
            request.existing_run_dir = None
        supplied = {
            "subject_dir": bool(request.subject_dir), "work_root": bool(request.work_root),
            "existing_run_dir": bool(request.existing_run_dir), "atlas": bool(request.atlas),
            "gestational_age": request.gestational_age is not None,
        }
        request.constraints = [item for item in request.constraints if not _resolved_missing_message(item, supplied)]
        request.unfulfilled_requests = normalize_unfulfilled_requests([
            item for item in request.unfulfilled_requests
            if not any(present and field in item for field, present in supplied.items())
        ])
        request.missing = []
        request.reused_steps = []
        if request.execution_mode == "import_existing" and not request.existing_run_dir:
            request.missing.append("existing_run_dir")
        if request.execution_mode == "continue_from_run":
            seed = request.existing_run_dir or request.work_root
            if not seed:
                request.missing.append("existing_run_dir")
            inventory = inventory_run(Path(seed), Path(request.subject_dir or seed or "").name) if seed else {"completed_steps": [], "usable": False}
            if seed and not inventory.get("usable"):
                request.missing.append("existing_run_dir")
            request.reused_steps = reused_from_inventory(request.execution_steps, list(inventory.get("completed_steps") or []))
            for item in missing_for_scope(request.execution_steps, list(inventory.get("completed_steps") or [])):
                if item not in request.missing:
                    request.missing.append(item)
            if not request.work_root and seed:
                request.work_root = seed
            request.resume = True
        if request.execution_mode in COMPUTE_MODES:
            if not request.subject_dir: request.missing.append("subject_dir")
            if not request.work_root: request.missing.append("work_root")
            if "registration" in request.execution_steps and not request.atlas: request.missing.append("atlas")
        if request.execution_mode == "plan_only":
            if not request.subject_dir: request.missing.append("subject_dir")
            if not request.work_root: request.missing.append("work_root")
            if not request.atlas: request.missing.append("atlas")
        request.execution_steps = _execution_scope(request.execution_steps, request.execution_mode, request.surface)
        if request.execution_mode in {"plan_only", "import_existing"}:
            request.execution_steps = []
        request.missing = sorted(set(request.missing))
        _attach_explanations(request, llm)
        conflicts = _dashboard_conflicts(parsed, overrides or {}, explicit, raw_text)
        return request, {
            "used": True, "stage": "request_parsing", "status": "completed",
            "provider": llm.active_provider, "model": llm.config.model,
            "dashboard_conflicts": conflicts,
        }
    except LLMError as exc:
        if not llm.config.fallback_to_rules: raise
        return _attach_explanations(baseline), {"used": False, "stage": "request_parsing", "status": "fallback", "error": exc.public_dict()}

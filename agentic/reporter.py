from __future__ import annotations

import json
import re
from copy import copy

from .llm_client import LLMError, OpenAICompatibleClient, load_prompt
from .models import TaskPlan


CAPABILITY_BOUNDARY = (
    "This system only orchestrates registered deterministic tools and summarizes "
    "structured outputs. The medical-style report is research decision support: "
    "it can describe reconstruction quality, extracted measurements, evidence, "
    "and limitations, but it is not a clinical diagnosis and does not assert "
    "normality or abnormality unless validated reference ranges and expert review "
    "are explicitly supplied."
)
CAPABILITY_BOUNDARY_ZH = (
    "本系统只调度已注册的确定工具并汇总结构化结果。报告用于科研决策支持："
    "可以描述重建质量、测量与限制，但不是临床诊断；"
    "在缺少常模和专家审阅时，不断言正常或异常。"
)
STEP_LABELS_ZH = {
    "extraction": "脑提取",
    "reconstruction": "三维重建",
    "registration": "图像配准",
    "tissue": "组织分割",
    "roi": "脑区划分",
    "surface": "表面重建",
    "comparison": "方法比较",
    "visualization": "可视化",
    "metrics": "定量指标",
    "pipeline": "流水线",
}
QC_STATUS_ZH = {"pass": "通过", "review": "需复核", "fail": "未通过", "unavailable": "不可用", "skipped": "未执行"}
QC_LIMIT_ZH = {
    "Thresholds are technical completeness heuristics, not fetal-development reference ranges.": "只能说明掩膜是否齐套，不能证明脑提取质量好。",
    "Intensity metrics assess technical readability, not anatomy or diagnosis.": "只能说明体积可读，不能证明重建医学可用。",
    "Thresholds come from the registration CLI QC configuration; visual overlay review remains required.": "相似性度量只是配准收敛代理，不能代替目视 overlay。",
    "Label completeness does not establish anatomical correctness.": "只能说明几何对齐；没有金标准，不能证明解剖正确。",
    "File completeness does not replace topology and anatomical surface review.": "只能说明曲面文件齐套，不能证明拓扑或解剖表面正确。",
    "Step was not selected for this run.": "该步不在本次执行范围内。",
    "Expected NIfTI output is missing.": "缺少预期的 NIfTI 产物。",
    "Expected label image is missing.": "缺少预期的标签图像。",
}


def _use_zh(task_plan: TaskPlan) -> bool:
    return str(getattr(task_plan, "report_language", "auto") or "auto").lower() != "en"


_AFFIRMATIVE_CLINICAL_CLAIMS = (
    re.compile(r"(?:胎儿|脑部|影像|患儿).{0,12}(?:正常|异常|健康|疾病|畸形)(?:。|，|,|\s|$)"),
    re.compile(r"(?:is|was|indicates|confirms|shows)\s+(?:a\s+)?(?:clinical\s+)?diagnosis\b|\bdiagnosed\s+with\b|\bclinically\s+(?:normal|abnormal)\b|\bhealthy\s+fetus\b", re.I),
)


def validate_llm_report(markdown: str, evidence: dict) -> list[str]:
    """Reject report additions that cannot be traced to structured evidence.

    The deterministic report remains the safe fallback. Numeric tokens in an LLM
    rewrite must already occur in its supplied evidence; this deliberately favors
    omission over an attractive but unsupported measurement.
    """
    errors: list[str] = []
    evidence_text = json.dumps(evidence, ensure_ascii=False, sort_keys=True).replace("−", "-")
    normalized_markdown = markdown.replace("−", "-")
    number_pattern = r"(?<![\w])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?"
    evidence_tokens = [item.replace(",", "") for item in re.findall(number_pattern, evidence_text)]
    report_tokens = [item.replace(",", "") for item in re.findall(number_pattern, normalized_markdown)]
    evidence_numbers = set(evidence_tokens)
    evidence_values = []
    for token in evidence_tokens:
        try:
            evidence_values.append(float(token))
        except ValueError:
            pass

    def supported(token: str) -> bool:
        if token in evidence_numbers:
            return True
        try:
            value = float(token)
        except ValueError:
            return False
        decimals = len(token.split(".", 1)[1]) if "." in token and "e" not in token.lower() else None
        if decimals is None:
            return False
        return any(round(candidate, decimals) == value for candidate in evidence_values)

    unsupported = sorted({token for token in report_tokens if not supported(token)})
    if unsupported:
        errors.append("unsupported numeric claims: " + ", ".join(unsupported))
    for pattern in _AFFIRMATIVE_CLINICAL_CLAIMS:
        matches = []
        for value in pattern.finditer(markdown):
            context = markdown[max(0, value.start() - 18):value.start()]
            if re.search(r"不能|无法|不可|不得|不支持|不判断|未判断|无证据|不用于|不能用于", context):
                continue
            matches.append(value.group(0).strip())
        if matches:
            errors.append("affirmative clinical claim is outside capability: " + "; ".join(matches[:3]))
    return errors


def validate_chinese_report(markdown: str, refusal_titles: list[str] | None = None) -> list[str]:
    errors: list[str] = []
    if len(re.findall(r"[\u4e00-\u9fff]", markdown)) < 40:
        errors.append("report is not predominantly Chinese")
    if "能力边界" not in markdown:
        errors.append("Chinese report is missing 能力边界")
    if "阅片复核清单" not in markdown and "待审清单" not in markdown:
        errors.append("Chinese report is missing 阅片复核清单")
    titles = [title for title in (refusal_titles or []) if title]
    if titles and "> [!refusal]" not in markdown:
        errors.append("Chinese report is missing [!refusal] callouts")
    for title in titles:
        if title not in markdown:
            errors.append(f"Chinese report omitted refusal title: {title}")
    return errors


def _replace_markdown_section(markdown: str, heading: str, replacement: str) -> str | None:
    pattern = re.compile(rf"(?ms)^##\s*{re.escape(heading)}\s*\n.*?(?=^##\s|\Z)")
    if not pattern.search(markdown):
        return None
    return pattern.sub(replacement.rstrip() + "\n\n", markdown).strip()


def _insert_after_scope(markdown: str, block: str) -> str:
    pattern = re.compile(r"(?ms)^##\s*本次请求与执行范围\s*\n.*?(?=^##\s|\Z)")
    match = pattern.search(markdown)
    if not match:
        return block.rstrip() + "\n\n" + markdown.strip()
    return (markdown[:match.end()].rstrip() + "\n\n" + block.strip() + "\n\n" + markdown[match.end():]).strip()


def _restore_chinese_invariants(
    markdown: str,
    task_plan: TaskPlan,
    technical_analysis: dict | None = None,
) -> str:
    value = markdown.strip()
    refusals = list(task_plan.refusal_explanations or [])
    if refusals:
        canonical = "\n".join(_zh_refusal_lines(task_plan)).strip()
        replaced = _replace_markdown_section(value, "未完成与拒绝", canonical)
        if replaced is not None:
            value = replaced
        elif "> [!refusal]" not in value:
            value = _insert_after_scope(value, canonical)
        missing_titles = [item for item in refusals if str(item.get("title") or "") not in value]
        if missing_titles:
            refusal_plan = copy(task_plan)
            refusal_plan.refusal_explanations = missing_titles
            value = _insert_after_scope(value, "\n".join(_zh_refusal_lines(refusal_plan)).strip())
    if "能力边界" not in value:
        value += "\n\n## 能力边界\n\n" + CAPABILITY_BOUNDARY_ZH
    if "阅片复核清单" not in value and "待审清单" not in value:
        value += "\n\n" + "\n".join(_zh_review_lines(task_plan, technical_analysis)).strip()
    return value.strip()


def compact_llm_evidence(value: object, key: str = "") -> object:
    """Remove repeated local paths while preserving report facts and metrics."""
    dropped = {
        "path", "source", "sources", "existing_run_dir", "staging_subject_dir",
        "surface_dir", "surface_subject_dir", "surface_surf_dir",
    }
    if key in dropped:
        return None
    if isinstance(value, dict):
        compacted = {}
        for child_key, child_value in value.items():
            result = compact_llm_evidence(child_value, str(child_key))
            if result is not None:
                compacted[child_key] = result
        return compacted
    if isinstance(value, list):
        return [result for item in value if (result := compact_llm_evidence(item, key)) is not None]
    if isinstance(value, str) and value.startswith("/"):
        return __import__("pathlib").Path(value).name
    return value


def _load_comparison(task_plan: TaskPlan) -> dict | None:
    root = task_plan.work_root or task_plan.existing_run_dir
    if not root:
        return None
    from pathlib import Path
    ranking = Path(root).expanduser() / "outputs" / "reconstruction" / "comparison" / "ranking.json"
    if not ranking.is_file():
        return None
    try:
        return json.loads(ranking.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _zh_scope_lines(task_plan: TaskPlan, completed: list, failed: list, skipped: list) -> list[str]:
    wanted = [STEP_LABELS_ZH.get(step, step) for step in (task_plan.execution_steps or [])] or ["导入已有结果"]
    reused = [STEP_LABELS_ZH.get(step, step) for step in (task_plan.reused_steps or [])]
    lines = [
        "# AutoRecon 分析报告",
        "",
        "## 本次请求与执行范围",
        f"- 请求：{task_plan.goal}",
        f"- 执行范围：{'、'.join(wanted)}",
    ]
    if reused:
        lines.append(f"- 复用已有结果：{'、'.join(reused)}")
    if task_plan.gestational_age is not None:
        lines.append(f"- 孕周：{task_plan.gestational_age} 周")
    if task_plan.atlas_week is not None:
        lines.append(f"- 图谱周龄：{task_plan.atlas_week} 周（{task_plan.atlas_rule or '自动选择'}）")
    lines.append(f"- 完成 {len(completed)} 步，失败 {len(failed)} 步，跳过 {len(skipped)} 步")
    return lines


ORCHESTRATION_STEP_IDS = frozenset({"pipeline", "metrics"})


def _visible_step_results(results: list[dict], report_steps: list[str]) -> list[dict]:
    scoped = [item for item in results if not report_steps or item.get("step_id") in report_steps]
    return [item for item in scoped if item.get("step_id") not in ORCHESTRATION_STEP_IDS]


def _zh_refusal_lines(task_plan: TaskPlan) -> list[str]:
    items = list(task_plan.refusal_explanations or [])
    if not items:
        return []
    lines = ["", "## 未完成与拒绝", ""]
    for item in items:
        title = item.get("title") or item.get("code")
        reason = item.get("reason") or ""
        lines.extend([
            "> [!refusal]",
            f"> **{title}**",
            f"> {reason}",
            "",
        ])
    return lines


def _zh_review_lines(task_plan: TaskPlan, technical_analysis: dict | None = None) -> list[str]:
    analysis = technical_analysis or {}
    registration = analysis.get("registration_summary") or {}
    surface = analysis.get("surface_checks") or {}
    image_checks = analysis.get("image_checks") or {}
    failed = list((analysis.get("step_summary") or {}).get("failed") or [])
    items: list[str] = []
    scoped = set(task_plan.execution_steps or []) | set(task_plan.report_steps or []) | set(task_plan.display_steps or [])
    qc_group = str(registration.get("qc_group") or "")
    if registration.get("available") or "registration" in scoped:
        note = f"（质控分组为 {qc_group}）" if qc_group and qc_group not in {"acceptable", "pass", "ok", "-"} else ""
        items.append(f"- [ ] 目视复核配准 overlay{note}，相似性度量不能代替目视检查")
    ga = task_plan.gestational_age or registration.get("gestational_age")
    if not ga:
        items.append("- [ ] 记录受试者孕周，并确认图谱周龄与实际孕周的匹配性")
    for key, value in image_checks.items():
        if str(value).startswith("WARN"):
            items.append(f"- [ ] 复核{STEP_LABELS_ZH.get(key, key)}输出缺失或告警")
    missing_surfaces = surface.get("missing_surface_files") or []
    if missing_surfaces:
        items.append("- [ ] 补齐或重跑表面重建，并复核表面拓扑与解剖正确性")
    elif surface.get("present_surface_files"):
        items.append("- [ ] 目视复核双侧表面拓扑与解剖正确性（文件齐套不能代替拓扑复核）")
    for step_id in failed:
        if step_id in {"pipeline", "input_check"}:
            continue
        items.append(f"- [ ] 排查并补齐失败步骤：{STEP_LABELS_ZH.get(step_id, step_id)}")
    titles = {str(item.get("title") or "") for item in (task_plan.refusal_explanations or [])}
    if "不能判断是否正常" in titles or "不能给出孕周百分位" in titles:
        items.append("- [ ] 提供经验证的孕周常模与专家阅片签字后，方可进行常模比较或正常性评估")
    if "不能宣称最佳重建方法" in titles:
        items.append("- [ ] 完成专家盲评后，方可认定最佳重建方法")
    if "未发送到医院系统" in titles:
        items.append("- [ ] 确认报告仅留本机，不发送医院系统")
    if not items:
        items.extend([
            "- [ ] 结合影像复核后再将结果用于研究分析",
            "- [ ] 结果用于研究前须经专家阅片签署",
        ])
    unique: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return ["", "## 阅片复核清单", ""] + unique


def _zh_qc_lines(step_qc: dict, report_steps: list[str]) -> list[str]:
    steps = step_qc.get("steps") or []
    if report_steps:
        steps = [item for item in steps if item.get("step_id") in report_steps]
    if not steps:
        return []
    lines = ["", "## 分步质控", "", "| 步骤 | 状态 | 指标 | 不能证明什么 |", "|---|---|---|---|"]
    for item in steps:
        label = STEP_LABELS_ZH.get(item.get("step_id"), item.get("step_id"))
        status = QC_STATUS_ZH.get(item.get("status"), item.get("status"))
        contract = QC_STATUS_ZH.get(item.get("contract_status"), item.get("contract_status"))
        if contract and contract != status:
            status = f"{status}（合同{contract}）"
        metrics = "；".join(
            f"{m.get('label') or m.get('name')} {m.get('value')}（{QC_STATUS_ZH.get(m.get('status'), m.get('status'))}）"
            for m in (item.get("metrics") or [])
        ) or "—"
        limits = "；".join(
            QC_LIMIT_ZH.get(text, text)
            for text in (item.get("limitations") or [])
        ) or "仅反映该步技术完整性"
        lines.append(f"| {label} | {status} | {metrics} | {limits} |")
    return lines


def _zh_comparison_lines(task_plan: TaskPlan) -> list[str]:
    ranking = _load_comparison(task_plan)
    tools = list(task_plan.reconstruction_compare_tools or [])
    if not ranking and not tools:
        return []
    rows = (ranking or {}).get("ranking") or (ranking or {}).get("candidates") or []
    mode = (ranking or {}).get("ranking_mode") or "automatic_only"
    recommended = (ranking or {}).get("recommended_backend")
    if not rows:
        rows = [{"backend": name, "automatic_score": "尚未评分"} for name in (tools or ["frost", "nesvor", "autosvrtk", "niftymic"])]
    lines = ["", "## 方法比较", "", "| 方法 | 自动分 |", "|---|---|"]
    for row in rows:
        name = row.get("backend") or row.get("name") or "-"
        score = row.get("automatic_score", row.get("score", "-"))
        lines.append(f"| {name} | {score} |")
    if mode == "automatic_only" or not recommended:
        lines.extend(["", "> [!refusal]", "> **不能宣称最佳重建方法**", "> 缺少完整专家盲评，仅输出自动技术排名，不得当作最终最佳方法。"])
    return lines


def _zh_findings(task_plan: TaskPlan, technical_analysis: dict | None) -> list[str]:
    if not technical_analysis:
        return ["", "## 技术结论", "- 本次没有可汇总的计算产物。"]
    registration = technical_analysis.get("registration_summary") or {}
    quantitative = technical_analysis.get("quantitative_summary") or {}
    roi_basic = quantitative.get("roi86_basic") or {}
    image_checks = technical_analysis.get("image_checks") or {}
    lines = ["", "## 技术结论"]
    quality = _summarize_output_quality(image_checks, technical_analysis.get("surface_checks") or {})
    if "incomplete" in quality.lower():
        lines.append("- 技术产物尚不完整，请结合影像复核后再用于研究分析。")
    else:
        lines.append("- 当前范围内的技术产物可读，可供医生阅片与研究定量，不能替代临床诊断。")
    if registration:
        lines.append(
            f"- 配准状态：{registration.get('status') or '不可用'}；质控分组：{registration.get('qc_group') or '不可用'}"
        )
    if roi_basic.get("available"):
        lines.append(f"- ROI 分区数：{roi_basic.get('roi_count')}；总体积：{_fmt_volume(roi_basic.get('total_volume_mm3'))}")
    lines.extend(["", "## 影像与测量"])
    for key, value in image_checks.items():
        lines.append(f"- {STEP_LABELS_ZH.get(key, key)}：{value}")
    return lines


def _build_zh_report(
    task_plan: TaskPlan,
    results: list[dict],
    dashboard: dict | None,
    llm: OpenAICompatibleClient | None,
    llm_events: list[dict] | None,
) -> tuple[str, dict]:
    report_steps = task_plan.report_steps
    visible_results = _visible_step_results(results, report_steps)
    completed = [r for r in visible_results if r.get("status") == "completed"]
    failed = [r for r in visible_results if r.get("status") == "failed"]
    skipped = [r for r in visible_results if r.get("status") == "skipped"]
    technical_analysis = _find_technical_analysis(results)
    lines = _zh_scope_lines(task_plan, completed, failed, skipped)
    lines.extend(_zh_refusal_lines(task_plan))
    lines.extend(_zh_findings(task_plan, technical_analysis))
    if technical_analysis:
        lines.extend(_zh_qc_lines(technical_analysis.get("step_qc") or {}, report_steps))
    lines.extend(_zh_comparison_lines(task_plan))
    lines.extend(["", "## 能力边界", CAPABILITY_BOUNDARY_ZH])
    lines.extend(_zh_review_lines(task_plan, technical_analysis))
    markdown = "\n".join(lines) + "\n"
    report_json = {
        "task_type": task_plan.task_type,
        "goal": task_plan.goal,
        "execution_mode": task_plan.execution_mode,
        "completed_steps": [r.get("step_id") for r in completed],
        "failed_steps": [r.get("step_id") for r in failed],
        "skipped_steps": [r.get("step_id") for r in skipped],
        "dashboard": dashboard or {},
        "warnings": task_plan.warnings,
        "refusals": list(task_plan.refusal_explanations or []),
        "reused_steps": list(task_plan.reused_steps or []),
        "technical_analysis": technical_analysis,
        "medical_report": _medical_report_json(task_plan, technical_analysis) if technical_analysis else None,
        "capability_boundary": CAPABILITY_BOUNDARY_ZH,
        "llm": {"events": list(llm_events or [])},
        "language": "zh",
    }
    if technical_analysis:
        medical = report_json.get("medical_report") or {}
        report_json["evidence_bank"] = {
            "schema_version": "1.0",
            "request": {"goal": task_plan.goal, "task_type": task_plan.task_type},
            "plan": {
                "execution_mode": task_plan.execution_mode,
                "execution_steps": list(task_plan.execution_steps),
                "report_steps": list(task_plan.report_steps),
                "planner_source": task_plan.planner_source,
            },
            "step_qc": (technical_analysis.get("step_qc") or {}).get("steps", []),
            "claims": medical.get("evidence_bank", []),
            "report_limits": medical.get("limits", []),
        }
    if not technical_analysis or not llm or not llm.available or not llm.config.use_for_reporting:
        report_json.setdefault("llm", {})["reporting"] = {"used": False, "reason": "disabled_unavailable_or_no_evidence"}
        return markdown, report_json
    try:
        prompt_path = __import__("pathlib").Path(__file__).resolve().parent / "prompts" / "medical_report_summarizer.md"
        evidence = report_json["medical_report"]
        llm_evidence = compact_llm_evidence(evidence)
        llm_markdown = llm.complete(
            load_prompt(prompt_path) + "\n\n" + CAPABILITY_BOUNDARY_ZH
            + "\n用中文撰写。拒绝项必须使用 `> [!refusal]` 标注并保留全部标题；报告末尾必须有「阅片复核清单」，条目用 `- [ ]`。",
            json.dumps({
                "user_request": task_plan.goal,
                "report_scope": report_steps or "all",
                "report_language": "zh",
                "refusals": task_plan.refusal_explanations,
                "deterministic_report": markdown,
                "medical_evidence": llm_evidence,
            }, ensure_ascii=False),
        ).strip()
        if not llm_markdown:
            raise LLMError("Model returned an empty report.")
        llm_markdown = _restore_chinese_invariants(llm_markdown, task_plan, technical_analysis)
        validation_evidence = {
            "medical_evidence": evidence,
            "deterministic_report": markdown,
            "refusals": task_plan.refusal_explanations,
        }
        report_validation_errors = validate_llm_report(llm_markdown, validation_evidence)
        report_validation_errors.extend(validate_chinese_report(
            llm_markdown,
            [str(item.get("title") or "") for item in task_plan.refusal_explanations],
        ))
        if report_validation_errors:
            raise LLMError("Unsafe or unsupported LLM report: " + " | ".join(report_validation_errors))
        report_json["llm"]["reporting"] = {"used": True, "status": "completed", "model": llm.config.model}
        report_json["deterministic_report_markdown"] = markdown
        return llm_markdown + "\n", report_json
    except LLMError as exc:
        if not llm.config.fallback_to_rules:
            raise
        report_json["llm"]["reporting"] = {"used": False, "status": "fallback", "error": str(exc)}
        return markdown, report_json


def build_report(
    task_plan: TaskPlan,
    results: list[dict],
    dashboard: dict | None = None,
    llm: OpenAICompatibleClient | None = None,
    llm_events: list[dict] | None = None,
) -> tuple[str, dict]:
    if _use_zh(task_plan):
        return _build_zh_report(task_plan, results, dashboard, llm, llm_events)
    report_steps = task_plan.report_steps
    visible_results = _visible_step_results(results, report_steps)
    completed = [r for r in visible_results if r.get("status") == "completed"]
    failed = [r for r in visible_results if r.get("status") == "failed"]
    skipped = [r for r in visible_results if r.get("status") == "skipped"]

    lines = [
        f"# AutoRecon Agentic Run",
        "",
        f"- Task type: `{task_plan.task_type}`",
        f"- Goal: `{task_plan.goal}`",
        f"- Execution mode: `{task_plan.execution_mode}`",
        f"- Report layout: `{task_plan.report_layout}`",
        f"- Completed steps: {len(completed)}",
        f"- Failed steps: {len(failed)}",
        f"- Skipped steps: {len(skipped)}",
    ]
    if report_steps:
        lines.append(f"- Requested report scope: `{', '.join(report_steps)}`")
    lines.append(f"- Display scope: `{', '.join(task_plan.display_steps) if task_plan.display_steps else 'all'}`")
    lines.append(f"- Execution scope: `{', '.join(task_plan.execution_steps) if task_plan.execution_steps else 'none/import'}`")
    if task_plan.subject_dir:
        lines.append(f"- Subject directory: `{task_plan.subject_dir}`")
    if task_plan.work_root:
        lines.append(f"- Work root: `{task_plan.work_root}`")
    if task_plan.gestational_age is not None:
        lines.append(f"- Gestational age: `{task_plan.gestational_age}`")
    if task_plan.atlas_week is not None:
        lines.append(f"- Atlas week: `{task_plan.atlas_week}`")
    if task_plan.atlas_rule:
        lines.append(f"- Atlas selection rule: `{task_plan.atlas_rule}`")
    if dashboard and dashboard.get("dashboard_file"):
        lines.append(f"- Dashboard file: `{dashboard['dashboard_file']}`")
    if task_plan.warnings:
        lines.extend(["", "## Scope Notes"])
        lines.extend(f"- {warning}" for warning in task_plan.warnings)
    if task_plan.refusal_explanations:
        lines.extend(["", "## Unfulfilled / Refused"])
        for item in task_plan.refusal_explanations:
            lines.append(f"- **{item.get('title') or item.get('code')}**: {item.get('reason')}")

    lines.extend(["", "## Step Results"])
    for result in visible_results:
        label = result.get("step_id")
        status = result.get("status")
        message = result.get("message") or result.get("error") or ""
        lines.append(f"- `{label}`: **{status}** {message}")
        if task_plan.report_layout in {"per_step", "per_step_and_final"}:
            lines.extend([
                "",
                f"### {str(label).replace('_', ' ').title()} Report",
                f"- Status: `{status}`",
                f"- Evidence summary: {message or 'No additional message was recorded.'}",
                f"- Outputs: `{json.dumps(result.get('outputs') or {}, ensure_ascii=False)}`",
            ])
    if task_plan.report_layout == "per_step_and_final":
        lines.extend([
            "",
            "## Final Combined Report",
            f"- Included evidence steps: `{', '.join(str(r.get('step_id')) for r in visible_results) or 'none'}`",
            f"- Completed: `{len(completed)}`; failed: `{len(failed)}`; skipped: `{len(skipped)}`.",
        ])

    technical_analysis = _find_technical_analysis(results)
    if technical_analysis:
        lines.extend(_step_qc_lines(technical_analysis.get("step_qc") or {}, report_steps))
    if technical_analysis and report_steps:
        lines.extend(_scoped_analysis_lines(report_steps, technical_analysis))
    elif technical_analysis:
        case_info = technical_analysis.get("case_info", {})
        step_summary = technical_analysis.get("step_summary", {})
        image_checks = technical_analysis.get("image_checks", {})
        surface_checks = technical_analysis.get("surface_checks", {})
        registration_summary = technical_analysis.get("registration_summary", {})
        quantitative_summary = technical_analysis.get("quantitative_summary", {})
        log_findings = technical_analysis.get("log_findings", [])
        lines.extend(
            [
                "",
                "## Technical Task Analysis",
                "",
                "### Case Information",
                f"- Subject: `{case_info.get('subject', '-')}`",
                f"- BTFE stack count: `{case_info.get('btfe_stack_count', '-')}`",
                f"- Imported dashboard status: `{case_info.get('dashboard_status', '-')}`",
                f"- Existing run directory: `{case_info.get('existing_run_dir', '-')}`",
                f"- Staging subject directory: `{case_info.get('staging_subject_dir', '-')}`",
                "",
                "### Step Completion",
                f"- Completed steps: `{', '.join(step_summary.get('completed') or []) or 'none'}`",
                f"- Failed steps: `{', '.join(step_summary.get('failed') or []) or 'none detected'}`",
                f"- Skipped steps: `{', '.join(step_summary.get('skipped') or []) or 'none detected'}`",
                "",
                "### Image Output Checks",
            ]
        )
        for label, message in image_checks.items():
            lines.append(f"- `{label}`: {message}")
        lines.extend(
            [
                "",
                "### Surface and Metric Artifacts",
                f"- Present surface files: `{', '.join(surface_checks.get('present_surface_files') or []) or 'none detected'}`",
                f"- Missing surface files: `{', '.join(surface_checks.get('missing_surface_files') or []) or 'none detected'}`",
                f"- Present stats files: `{', '.join(surface_checks.get('present_stats_files') or []) or 'none detected'}`",
                f"- Missing stats files: `{', '.join(surface_checks.get('missing_stats_files') or []) or 'none detected'}`",
                "",
                "### Technical Quality Notes",
            ]
        )
        for item in technical_analysis.get("technical_quality_summary", []):
            lines.append(f"- {item}")
        if log_findings:
            lines.extend(["", "### Log Findings"])
            for finding in log_findings:
                lines.append(f"- `{finding.get('step', '-')}`: {finding.get('message', '-')}")
        else:
            lines.extend(["", "### Log Findings", "- No error-like log patterns were detected in imported dashboard logs."])

        lines.extend(_medical_report_lines(task_plan, technical_analysis, registration_summary, quantitative_summary))

    lines.extend(["", "## Capability Boundary", CAPABILITY_BOUNDARY])
    report_json = {
        "task_type": task_plan.task_type,
        "goal": task_plan.goal,
        "execution_mode": task_plan.execution_mode,
        "completed_steps": [r.get("step_id") for r in completed],
        "failed_steps": [r.get("step_id") for r in failed],
        "skipped_steps": [r.get("step_id") for r in skipped],
        "dashboard": dashboard or {},
        "warnings": task_plan.warnings,
        "technical_analysis": technical_analysis,
        "medical_report": _scoped_medical_report_json(task_plan, technical_analysis, report_steps) if technical_analysis and report_steps else (_medical_report_json(task_plan, technical_analysis) if technical_analysis else None),
        "capability_boundary": CAPABILITY_BOUNDARY,
        "llm": {"events": list(llm_events or [])},
    }
    if technical_analysis:
        medical = report_json.get("medical_report") or {}
        report_json["evidence_bank"] = {
            "schema_version": "1.0",
            "request": {"goal": task_plan.goal, "task_type": task_plan.task_type},
            "plan": {
                "execution_mode": task_plan.execution_mode,
                "execution_steps": list(task_plan.execution_steps),
                "report_steps": list(task_plan.report_steps),
                "planner_source": task_plan.planner_source,
            },
            "step_qc": (technical_analysis.get("step_qc") or {}).get("steps", []),
            "claims": medical.get("evidence_bank", []),
            "report_limits": medical.get("limits", []),
        }
    for event in llm_events or []:
        if event.get("stage") == "result_analysis" and isinstance(event.get("analysis"), dict):
            analysis = event["analysis"]
            lines.extend(["", "## LLM Result Analysis", str(analysis.get("summary") or "")])
            for action in analysis.get("recommended_next_actions") or []:
                lines.append(f"- {action}")
    deterministic_markdown = "\n".join(lines) + "\n"
    if not technical_analysis or not llm or not llm.available or not llm.config.use_for_reporting:
        report_json["llm"]["reporting"] = {"used": False, "reason": "disabled_unavailable_or_no_evidence"}
        return deterministic_markdown, report_json
    try:
        prompt_path = __import__("pathlib").Path(__file__).resolve().parent / "prompts" / "medical_report_summarizer.md"
        evidence = report_json["medical_report"]
        llm_markdown = llm.complete(
            load_prompt(prompt_path) + "\n\n" + CAPABILITY_BOUNDARY,
            json.dumps({"user_request": task_plan.goal, "report_scope": report_steps or "all", "report_language": getattr(task_plan, "report_language", "auto"), "medical_evidence": evidence}, ensure_ascii=False),
        ).strip()
        if not llm_markdown:
            raise LLMError("Model returned an empty report.")
        report_validation_errors = validate_llm_report(llm_markdown, evidence)
        if report_validation_errors:
            raise LLMError("Unsafe or unsupported LLM report: " + " | ".join(report_validation_errors))
        report_json["llm"]["reporting"] = {"used": True, "status": "completed", "model": llm.config.model}
        report_json["deterministic_report_markdown"] = deterministic_markdown
        return llm_markdown + "\n", report_json
    except LLMError as exc:
        if not llm.config.fallback_to_rules:
            raise
        report_json["llm"]["reporting"] = {"used": False, "status": "fallback", "error": str(exc)}
        return deterministic_markdown, report_json


def _scoped_analysis_lines(display_steps: list[str], analysis: dict) -> list[str]:
    case = analysis.get("case_info", {})
    images = analysis.get("image_checks", {})
    lines = ["", "## Scoped Technical Report", "", f"- Subject: `{case.get('subject', '-')}`"]
    if "reconstruction" in display_steps:
        lines.extend([
            "", "### Reconstruction",
            f"- Reconstruction image check: {images.get('reconstruction', 'not checked')}",
            f"- Source BTFE stack count: `{case.get('btfe_stack_count', '-')}`",
            "- Interpretation: this report describes reconstruction availability and technical readability only.",
            "- Reviewer action: inspect the reconstruction MPR for motion, coverage, signal consistency, and anatomical plausibility.",
        ])
    if "registration" in display_steps:
        reg = analysis.get("registration_summary", {})
        lines.extend(["", "### Registration", f"- Status: `{reg.get('status', 'unavailable')}`", f"- QC group: `{reg.get('qc_group', 'unavailable')}`"])
    for step in display_steps:
        if step in {"tissue", "roi", "surface"}:
            lines.extend(["", f"### {step.title()}", "- Included in the requested report scope; see the corresponding evidence artifacts."])
    lines.extend(["", "### Scope Limit", "- Other pipeline stages are intentionally omitted from this report."])
    return lines


def _step_qc_lines(step_qc: dict, report_steps: list[str]) -> list[str]:
    steps = step_qc.get("steps") or []
    if report_steps:
        steps = [item for item in steps if item.get("step_id") in report_steps]
    if not steps:
        return []
    lines = ["", "## Per-step QC Evidence"]
    for item in steps:
        lines.extend(["", f"### {str(item.get('step_id', '-')).title()} QC", f"- Overall technical status: `{item.get('status', 'unavailable')}`"])
        for value in item.get("metrics") or []:
            lines.append(
                f"- {value.get('label', value.get('name', '-'))}: `{value.get('value')}` {value.get('unit', '')}; "
                f"criterion `{value.get('criterion', '-')}`; status **{value.get('status', '-')}**; source `{value.get('source', '-')}`"
            )
        for limitation in item.get("limitations") or []:
            lines.append(f"- Limit: {limitation}")
    return lines


def _scoped_medical_report_json(task_plan: TaskPlan, analysis: dict, display_steps: list[str]) -> dict:
    full = _medical_report_json(task_plan, analysis)
    allowed_claims = {"case_context", "interpretation_boundary"}
    if "reconstruction" in display_steps:
        allowed_claims.add("core_images_readable")
        full["evidence_sources"] = {"image_checks": {"reconstruction": analysis.get("image_checks", {}).get("reconstruction")}}
    elif "registration" in display_steps:
        allowed_claims.add("registration_qc")
        full["evidence_sources"] = {"registration_summary": analysis.get("registration_summary", {})}
    full["evidence_bank"] = [item for item in full.get("evidence_bank", []) if item.get("claim_id") in allowed_claims]
    full["report_scope"] = display_steps
    return full


def _find_technical_analysis(results: list[dict]) -> dict | None:
    for result in results:
        outputs = result.get("outputs") or {}
        analysis = outputs.get("technical_analysis")
        if isinstance(analysis, dict):
            return analysis
    return None


def _medical_report_lines(
    task_plan: TaskPlan,
    technical_analysis: dict,
    registration_summary: dict,
    quantitative_summary: dict,
) -> list[str]:
    case_info = technical_analysis.get("case_info", {})
    surface_checks = technical_analysis.get("surface_checks", {})
    image_checks = technical_analysis.get("image_checks", {})
    roi_basic = quantitative_summary.get("roi86_basic") or {}
    cortex = quantitative_summary.get("roi86_cortexonly") or {}
    ga = task_plan.gestational_age or registration_summary.get("gestational_age") or "-"
    atlas = registration_summary.get("atlas") or task_plan.atlas or "-"
    atlas_week = registration_summary.get("atlas_week") or "-"
    reg_status = registration_summary.get("status") or ("unavailable" if not registration_summary.get("available") else "-")
    qc_group = registration_summary.get("qc_group") or "-"
    output_quality = _summarize_output_quality(image_checks, surface_checks)
    roi_total = _fmt_volume(roi_basic.get("total_volume_mm3"))
    cortex_total = _fmt_volume(cortex.get("total_volume_mm3"))
    evidence_bank = _build_evidence_bank(task_plan, technical_analysis)

    lines = [
        "",
        "## Fetal Brain MRI Professional Report",
        "",
        "### Report Type",
        "- Research-use structured fetal brain MRI reconstruction report, inspired by FetalAgents-style evidence aggregation.",
        "- This section summarizes verifiable pipeline outputs and reviewer-facing evidence. It is not a diagnostic radiology report.",
        "",
        "### Case and Acquisition Context",
        f"- Subject: `{case_info.get('subject', '-')}`",
        f"- Gestational age supplied to request: `{ga}` weeks",
        f"- Source BTFE stacks imported: `{case_info.get('btfe_stack_count', '-')}`",
        f"- Reconstruction output: {image_checks.get('reconstruction', 'not checked')}",
        f"- Tissue segmentation output: {image_checks.get('tissue', 'not checked')}",
        f"- ROI parcellation output: {image_checks.get('roi', 'not checked')}",
        "",
        "### Reconstruction and Registration Quality",
        f"- Overall technical interpretation: {output_quality}",
        f"- Registration status: `{reg_status}`; QC group: `{qc_group}`",
        f"- Atlas used by registration: `{atlas}`",
        f"- Atlas week recorded by pipeline: `{atlas_week or '-'}`",
        "- Reviewer action: inspect the reconstruction MPR, registration overlay, tissue overlay, ROI overlay, and surface rendering before using measurements for research analysis.",
        "",
        "### Quantitative Findings",
        f"- ROI86 parcellation regions reported: `{roi_basic.get('roi_count', 'unavailable')}`",
        f"- Total ROI86 segmented volume: `{roi_total}`",
        f"- Cortex-only ROI regions reported: `{cortex.get('roi_count', 'unavailable')}`",
        f"- Cortex-only segmented volume: `{cortex_total}`",
    ]
    lines.extend(_largest_region_lines("Largest ROI86 regions", roi_basic))
    lines.extend(_largest_region_lines("Largest cortex-only regions", cortex))
    lines.extend(
        [
            "",
            "### Surface Reconstruction",
            f"- Required surface files present: `{len(surface_checks.get('present_surface_files') or [])}` / `6`",
            f"- Missing required surface files: `{', '.join(surface_checks.get('missing_surface_files') or []) or 'none detected'}`",
            f"- Surface statistics files present: `{', '.join(surface_checks.get('present_stats_files') or []) or 'none detected'}`",
            "- Medical interpretation: the surface pipeline appears technically complete when required pial, white, and inflated surfaces are present for both hemispheres.",
            "",
            "### Interpretation Limits",
            "- The current ROI stats use generic `Seg####` labels, so region-level neuroanatomical interpretation is limited until an atlas label map is connected.",
            "- No gestational-age normative fetal MRI reference table is currently attached to this report, so percentile-based growth or maturation statements are intentionally withheld.",
            "- No automated abnormality detector is registered in this workflow. Morphologic observations should come from expert visual review of the dashboard images.",
            "",
            "### Evidence Bank",
        ]
    )
    for item in evidence_bank:
        lines.append(
            f"- `{item['claim_id']}` ({item['claim_level']}): {item['statement']} "
            f"Evidence: {item['evidence']} Confidence: `{item['confidence']}`"
        )
    lines.extend(
        [
            "",
            "### Suggested Impression",
            "- Imported outputs are technically complete for reconstruction, tissue segmentation, ROI parcellation, surface generation, and visualization when the PASS checks above hold.",
            "- The case is ready for expert visual review and research quantification, but not for automated clinical diagnosis.",
            "- To make the report medically stronger, add an atlas label map, GA-matched normative curves, and explicit visual QC scores for motion, coverage, tissue boundary quality, ROI plausibility, and surface topology.",
        ]
    )
    return lines


def _medical_report_json(task_plan: TaskPlan, technical_analysis: dict) -> dict:
    evidence_bank = _build_evidence_bank(task_plan, technical_analysis)
    return {
        "report_type": "research_fetal_brain_mri_structured_report",
        "method": "evidence_bank_to_markdown_report",
        "gestational_age": task_plan.gestational_age,
        "case_info": technical_analysis.get("case_info", {}),
        "evidence_sources": {
            "image_checks": technical_analysis.get("image_checks", {}),
            "registration_summary": technical_analysis.get("registration_summary", {}),
            "surface_checks": technical_analysis.get("surface_checks", {}),
            "quantitative_summary": technical_analysis.get("quantitative_summary", {}),
            "step_qc": technical_analysis.get("step_qc", {}),
        },
        "evidence_bank": evidence_bank,
        "llm_generation_policy": {
            "allowed": [
                "rewrite evidence-backed statements into concise professional language",
                "summarize limitations already present in the evidence bank",
                "ask for missing inputs required for stronger medical interpretation",
            ],
            "forbidden": [
                "diagnose abnormalities from unsupported visual impressions",
                "state normality or percentile status without validated references",
                "invent anatomical labels for generic Seg#### regions",
                "hide failed checks or missing artifacts",
            ],
        },
        "limits": [
            "not a clinical diagnosis",
            "no GA normative reference comparison unless external reference data are supplied",
            "generic ROI labels limit region-level anatomical interpretation",
        ],
    }


def _summarize_output_quality(image_checks: dict, surface_checks: dict) -> str:
    has_image_warning = any(str(value).startswith("WARN") for value in image_checks.values())
    missing_surface = bool(surface_checks.get("missing_surface_files"))
    missing_stats = bool(surface_checks.get("missing_stats_files"))
    if has_image_warning or missing_surface or missing_stats:
        return "Technically incomplete; review warnings before interpretation."
    return "Technically complete outputs are available for reviewer-facing analysis."


def _fmt_volume(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.1f} mm^3"
    return "unavailable"


def _largest_region_lines(title: str, summary: dict) -> list[str]:
    regions = summary.get("largest_regions") or []
    lines = ["", f"### {title}"]
    if not regions:
        lines.append("- unavailable")
        return lines
    for region in regions:
        lines.append(
            f"- `{region.get('struct_name', '-')}` / SegId `{region.get('seg_id', '-')}`: "
            f"`{_fmt_volume(region.get('volume_mm3'))}`"
        )
    return lines


def _build_evidence_bank(task_plan: TaskPlan, technical_analysis: dict) -> list[dict[str, str]]:
    case_info = technical_analysis.get("case_info", {})
    image_checks = technical_analysis.get("image_checks", {})
    surface_checks = technical_analysis.get("surface_checks", {})
    registration = technical_analysis.get("registration_summary", {})
    quantitative = technical_analysis.get("quantitative_summary", {})
    roi_basic = quantitative.get("roi86_basic") or {}
    cortex = quantitative.get("roi86_cortexonly") or {}
    failed_steps = technical_analysis.get("step_summary", {}).get("failed") or []
    log_findings = technical_analysis.get("log_findings") or []
    present_surfaces = surface_checks.get("present_surface_files") or []
    missing_surfaces = surface_checks.get("missing_surface_files") or []

    evidence: list[dict[str, str]] = [
        {
            "claim_id": "case_context",
            "claim_level": "metadata",
            "statement": f"Subject {case_info.get('subject', '-')} was processed with {case_info.get('btfe_stack_count', '-')} BTFE stacks at requested GA {task_plan.gestational_age or '-'} weeks.",
            "evidence": "dashboard run metadata and staging BTFE file count",
            "confidence": "high",
        },
        {
            "claim_id": "core_images_readable",
            "claim_level": "technical",
            "statement": _claim_core_images(image_checks),
            "evidence": "; ".join(f"{key}: {value}" for key, value in image_checks.items()) or "no image checks",
            "confidence": "high" if image_checks and all(str(v).startswith("PASS") for v in image_checks.values()) else "limited",
        },
        {
            "claim_id": "registration_qc",
            "claim_level": "technical",
            "statement": f"Registration status is {registration.get('status') or 'unavailable'} with QC group {registration.get('qc_group') or 'unavailable'}.",
            "evidence": f"registration summary.csv; atlas={registration.get('atlas') or '-'}",
            "confidence": "moderate" if registration.get("available") else "limited",
        },
        {
            "claim_id": "roi_quantification",
            "claim_level": "quantitative",
            "statement": f"ROI86 stats report {roi_basic.get('roi_count', 'unavailable')} regions and total segmented volume {_fmt_volume(roi_basic.get('total_volume_mm3'))}.",
            "evidence": roi_basic.get("path") or "roi86_basic.stats unavailable",
            "confidence": "moderate" if roi_basic.get("available") else "limited",
        },
        {
            "claim_id": "cortex_quantification",
            "claim_level": "quantitative",
            "statement": f"Cortex-only stats report {cortex.get('roi_count', 'unavailable')} regions and total segmented volume {_fmt_volume(cortex.get('total_volume_mm3'))}.",
            "evidence": cortex.get("path") or "roi86_thicknessproxy_cortexonly.stats unavailable",
            "confidence": "moderate" if cortex.get("available") else "limited",
        },
        {
            "claim_id": "surface_completeness",
            "claim_level": "technical",
            "statement": f"Required bilateral pial, white, and inflated surfaces present: {len(present_surfaces)}/6; missing: {', '.join(missing_surfaces) or 'none detected'}.",
            "evidence": surface_checks.get("surface_dir") or "surface directory unavailable",
            "confidence": "high" if len(present_surfaces) == 6 and not missing_surfaces else "limited",
        },
        {
            "claim_id": "interpretation_boundary",
            "claim_level": "safety",
            "statement": "The workflow supports research quantification and expert review, not standalone diagnosis or normality assessment.",
            "evidence": "missing validated GA reference curves, atlas label map, automated abnormality detector, and expert sign-off",
            "confidence": "high",
        },
    ]
    if failed_steps or log_findings:
        evidence.append(
            {
                "claim_id": "failure_review_required",
                "claim_level": "safety",
                "statement": "One or more failed steps or error-like logs require review before interpretation.",
                "evidence": f"failed_steps={failed_steps}; log_findings={log_findings}",
                "confidence": "high",
            }
        )
    return evidence


def _claim_core_images(image_checks: dict) -> str:
    if not image_checks:
        return "Core reconstruction, tissue, and ROI image readability was not checked."
    passing = [key for key, value in image_checks.items() if str(value).startswith("PASS")]
    warning = [key for key, value in image_checks.items() if not str(value).startswith("PASS")]
    if warning:
        return f"Readable core image outputs: {', '.join(passing) or 'none'}; outputs requiring review: {', '.join(warning)}."
    return f"Core image outputs are readable for {', '.join(passing)}."

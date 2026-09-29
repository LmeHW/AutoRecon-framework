from __future__ import annotations

import json
import re
from copy import copy

from .llm_client import LLMError, OpenAICompatibleClient, load_prompt
from .models import TaskPlan
from .clinic_paths import CLINICAL_STATUS_LABEL_ZH


CAPABILITY_BOUNDARY = (
    "This system only orchestrates registered deterministic tools and summarizes "
    "structured outputs. The medical-style report is research decision support: "
    "it can describe reconstruction quality, extracted measurements, evidence, "
    "and limitations, but it is not a clinical diagnosis and does not assert "
    "normality or abnormality unless validated reference ranges and expert review "
    "are explicitly supplied."
)
CAPABILITY_BOUNDARY_ZH = (
    "本报告用于科研阅片支持，不能替代临床诊断；没有金标准时不计算 Dice、AUC。"
)
CLINICAL_STEP_IDS = ("extraction", "reconstruction", "registration", "tissue", "roi", "surface")
FAMILY_LABEL_ZH = {
    "t1": "T1",
    "dwi": "DWI",
    "adc": "ADC",
    "t2": "T2",
    "t2_ssfse": "T2 HASTE / SSFSE",
    "ssfp_btfe": "BTFE / bSSFP",
}
DROP_REASON_ZH = {
    "not_3d": "非三维",
    "other_modality": "其它对比度",
    "scout": "定位像",
}
VERBOSE_REPORT_HEADINGS = (
    "本次请求与执行范围",
    "输入序列",
    "技术结论",
    "影像与测量",
    "已执行步骤质控",
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


def _complete_report_with_repair(llm: OpenAICompatibleClient, system: str, user: str, check) -> tuple[str, dict]:
    """Draft once; if the validator rejects it, send the errors back for a single rewrite."""
    last_errors: list[str] = []
    for attempt in range(2):
        payload = user
        if attempt:
            payload = (
                user
                + "\n\nValidation errors to repair:\n"
                + json.dumps(last_errors, ensure_ascii=False)
            )
        text = llm.complete(system, payload).strip()
        if not text:
            last_errors = ["Model returned an empty report."]
            continue
        restored, errors = check(text)
        if not errors:
            return restored, {"attempt": attempt + 1, "repaired": attempt > 0}
        last_errors = [str(item) for item in errors]
    raise LLMError("Unsafe or unsupported LLM report: " + " | ".join(last_errors))


def _replace_markdown_section(markdown: str, heading: str, replacement: str) -> str | None:
    pattern = re.compile(rf"(?ms)^##\s*{re.escape(heading)}\s*\n.*?(?=^##\s|\Z)")
    if not pattern.search(markdown):
        return None
    return pattern.sub(replacement.rstrip() + "\n\n", markdown).strip()


def _drop_markdown_sections(markdown: str, headings: tuple[str, ...]) -> str:
    value = markdown
    for heading in headings:
        value = re.sub(
            rf"(?ms)^##\s*{re.escape(heading)}\s*\n.*?(?=^##\s|\Z)",
            "",
            value,
        )
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def _insert_after_title(markdown: str, block: str) -> str:
    match = re.search(r"(?m)^#\s+.+\n(?:(?!^#).*\n){0,3}", markdown)
    if not match:
        return block.rstrip() + "\n\n" + markdown.strip()
    return (markdown[:match.end()].rstrip() + "\n\n" + block.strip() + "\n\n" + markdown[match.end():]).strip()


def _insert_after_heading(markdown: str, heading: str, block: str) -> str:
    pattern = re.compile(rf"(?ms)^##\s*{re.escape(heading)}\s*\n.*?(?=^##\s|\Z)")
    match = pattern.search(markdown)
    if not match:
        return markdown.rstrip() + "\n\n" + block.strip()
    return (markdown[:match.end()].rstrip() + "\n\n" + block.strip() + "\n\n" + markdown[match.end():]).strip()


def _restore_chinese_invariants(
    markdown: str,
    task_plan: TaskPlan,
    technical_analysis: dict | None = None,
    *,
    completed: list | None = None,
    skipped: list | None = None,
) -> str:
    value = _drop_markdown_sections(markdown.strip(), VERBOSE_REPORT_HEADINGS)
    refusals = list(task_plan.refusal_explanations or [])
    if refusals:
        canonical = "\n".join(_zh_refusal_lines(task_plan)).strip()
        replaced = _replace_markdown_section(value, "未完成与拒绝", canonical)
        if replaced is not None:
            value = replaced
        elif "> [!refusal]" not in value:
            value = _insert_after_title(value, canonical)
        missing_titles = [item for item in refusals if str(item.get("title") or "") not in value]
        if missing_titles:
            refusal_plan = copy(task_plan)
            refusal_plan.refusal_explanations = missing_titles
            value = _insert_after_title(value, "\n".join(_zh_refusal_lines(refusal_plan)).strip())
    case_block = "\n".join(_zh_case_lines(task_plan)).strip()
    if case_block:
        value = _drop_markdown_sections(value, ("病例信息",))
        value = _insert_after_title(value, case_block)
    if "## 本次完成" not in value:
        done = "\n".join(_zh_done_lines(task_plan, technical_analysis, completed or [], skipped or [])).strip()
        if "## 未完成与拒绝" in value:
            value = _insert_after_heading(value, "未完成与拒绝", done)
        else:
            value = _insert_after_title(value, done)
    if "## 阅片要点" not in value and "> [!finding]" not in value:
        findings = "\n".join(_zh_finding_lines(task_plan, technical_analysis)).strip()
        if "## 本次完成" in value:
            value = _insert_after_heading(value, "本次完成", findings)
        else:
            value = _insert_after_title(value, findings)
    if "能力边界" not in value:
        value += "\n\n## 能力边界\n\n" + CAPABILITY_BOUNDARY_ZH
    canonical_checklist = "\n".join(_zh_review_lines(task_plan, technical_analysis)).strip()
    replaced = _replace_markdown_section(value, "阅片复核清单", canonical_checklist)
    if replaced is None:
        replaced = _replace_markdown_section(value, "待审清单", canonical_checklist)
    value = replaced if replaced is not None else (value + "\n\n" + canonical_checklist)
    return value.strip()


def compact_llm_evidence(value: object, key: str = "") -> object:
    """Remove repeated local paths while preserving report facts and metrics."""
    dropped = {
        "path", "source", "sources", "existing_run_dir", "staging_subject_dir",
        "surface_dir", "surface_subject_dir", "surface_surf_dir",
        "metrics", "stack_files", "btfe", "series",
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


def _zh_title_lines(task_plan: TaskPlan) -> list[str]:
    bits = []
    if task_plan.gestational_age is not None:
        bits.append(f"孕 {task_plan.gestational_age:g} 周")
    if task_plan.atlas_week is not None:
        bits.append(f"图谱 {task_plan.atlas_week} 周")
    lines = ["# 胎儿脑 MRI 技术分析报告", ""]
    if bits:
        lines.append(" · ".join(bits))
    return lines


def _zh_case_lines(task_plan: TaskPlan) -> list[str]:
    items: list[str] = []
    if task_plan.gestational_age is not None:
        items.append(f"- 胎龄：{task_plan.gestational_age:g} 周")
    if task_plan.fetal_description:
        items.append(f"- 描述：{task_plan.fetal_description}")
    if task_plan.clinical_status:
        label = CLINICAL_STATUS_LABEL_ZH.get(task_plan.clinical_status, task_plan.clinical_status)
        items.append(f"- 临床所见：{label}")
    if task_plan.clinical_condition:
        items.append(f"- 疾病：{task_plan.clinical_condition}")
    if task_plan.clinical_notes:
        items.append(f"- 备注：{task_plan.clinical_notes}")
    if not (task_plan.fetal_description or task_plan.clinical_status or task_plan.clinical_condition or task_plan.clinical_notes):
        return []
    return ["", "## 病例信息", ""] + items


def refresh_case_record_section(markdown: str, task_plan: TaskPlan, results: list | None = None) -> str:
    technical = _find_technical_analysis(results or [])
    text = (markdown or "").strip()
    if not text:
        return "\n".join(_zh_title_lines(task_plan) + _zh_case_lines(task_plan)).strip()
    return _restore_chinese_invariants(text, task_plan, technical)


def _clinical_ids(values: list) -> list[str]:
    ids: list[str] = []
    for item in values or []:
        step_id = str(item.get("step_id") if isinstance(item, dict) else item)
        if step_id in CLINICAL_STEP_IDS:
            ids.append(step_id)
    return ids


def _executed_and_omitted(
    task_plan: TaskPlan,
    technical_analysis: dict | None,
    completed: list,
    skipped: list,
) -> tuple[list[str], list[str]]:
    qc_steps = ((technical_analysis or {}).get("step_qc") or {}).get("steps") or []
    executed = [
        str(item.get("step_id"))
        for item in qc_steps
        if str(item.get("step_id")) in CLINICAL_STEP_IDS and item.get("status") != "skipped"
    ]
    omitted = [
        str(item.get("step_id"))
        for item in qc_steps
        if str(item.get("step_id")) in CLINICAL_STEP_IDS and item.get("status") == "skipped"
    ]
    if executed or omitted:
        return executed, omitted
    executed = _clinical_ids(completed) or list(task_plan.execution_steps or [])
    omitted = _clinical_ids(skipped)
    if not omitted:
        skipped_summary = ((technical_analysis or {}).get("step_summary") or {}).get("skipped") or []
        omitted = [str(step) for step in skipped_summary if str(step) in CLINICAL_STEP_IDS]
    return [step for step in executed if step in CLINICAL_STEP_IDS], omitted


def _load_conversion(task_plan: TaskPlan, technical_analysis: dict | None) -> dict:
    info = (technical_analysis or {}).get("case_info") or {}
    conversion = dict(info.get("conversion") or {})
    subject = getattr(task_plan, "subject_dir", None)
    if not subject:
        return conversion
    from pathlib import Path
    conversion_path = Path(subject) / "conversion.json"
    if not conversion_path.is_file():
        return conversion
    try:
        payload = json.loads(conversion_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return conversion
    return payload.get("conversion") or payload or conversion


def _zh_drop_brief(conversion: dict) -> list[str]:
    reasons = list(conversion.get("drop_reasons") or [])
    if reasons:
        parts = []
        for item in reasons:
            family = FAMILY_LABEL_ZH.get(item.get("family"), item.get("family") or "")
            why = DROP_REASON_ZH.get(item.get("reason"), "")
            label = family or str(item.get("label") or "")
            if label and why:
                parts.append(f"{label}（{why}）")
            elif label:
                parts.append(label)
        return parts
    return [str(item) for item in (conversion.get("dropped") or []) if item]


def _zh_done_lines(
    task_plan: TaskPlan,
    technical_analysis: dict | None,
    completed: list,
    skipped: list,
) -> list[str]:
    executed, omitted = _executed_and_omitted(task_plan, technical_analysis, completed, skipped)
    reused = [STEP_LABELS_ZH.get(step, step) for step in (task_plan.reused_steps or []) if step in CLINICAL_STEP_IDS]
    conversion = _load_conversion(task_plan, technical_analysis)
    family = conversion.get("kept_family_label") or FAMILY_LABEL_ZH.get(conversion.get("kept_family"), "")
    stacks = list(conversion.get("stacks") or conversion.get("btfe") or [])
    if not stacks:
        info = (technical_analysis or {}).get("case_info") or {}
        stacks = list(info.get("stack_files") or [])
    dropped = _zh_drop_brief(conversion)
    lines = ["", "## 本次完成"]
    if executed:
        lines.append(f"- 已做：{'、'.join(STEP_LABELS_ZH.get(step, step) for step in executed)}")
    elif task_plan.execution_mode == "import_existing":
        lines.append("- 已做：导入已有结果")
    if reused:
        lines.append(f"- 复用已有结果：{'、'.join(reused)}")
    if omitted:
        lines.append(f"- 未做：{'、'.join(STEP_LABELS_ZH.get(step, step) for step in omitted)}（不是失败）")
    if family and stacks:
        lines.append(f"- 使用影像：{family}，{len(stacks)} 个三维栈")
    elif stacks:
        lines.append(f"- 使用影像：{len(stacks)} 个三维栈")
    elif family:
        lines.append(f"- 使用影像：{family}")
    if dropped:
        lines.append(f"- 未用扫描：{'、'.join(dropped)}")
    if len(lines) == 2:
        lines.append("- 本次没有可汇总的执行步骤。")
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


def _zh_input_lines(task_plan: TaskPlan, technical_analysis: dict | None) -> list[str]:
    info = (technical_analysis or {}).get("case_info") or {}
    conversion = dict(info.get("conversion") or {})
    stacks = list(info.get("stack_files") or conversion.get("stacks") or conversion.get("btfe") or [])
    family = conversion.get("kept_family_label") or conversion.get("kept_family")
    dropped = list(conversion.get("dropped") or [])
    subject = getattr(task_plan, "subject_dir", None)
    if subject:
        from pathlib import Path
        from pipeline.scripts.input_stacks import iter_input_stacks
        conversion_path = Path(subject) / "conversion.json"
        if conversion_path.is_file() and not conversion:
            try:
                conversion = json.loads(conversion_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                conversion = {}
            family = conversion.get("kept_family_label") or conversion.get("kept_family") or family
            dropped = list(conversion.get("dropped") or dropped)
            stacks = list(conversion.get("stacks") or conversion.get("btfe") or stacks)
        if not stacks:
            stacks = [path.name for path in iter_input_stacks(Path(subject))]
    if not stacks and not family and not dropped:
        return []
    lines = ["", "## 输入序列"]
    if family:
        lines.append(f"- 保留模态：{family}（{len(stacks)} 个三维栈）")
    elif stacks:
        lines.append(f"- 用于重建的三维栈：{len(stacks)} 个")
    if stacks:
        preview = "、".join(stacks[:8])
        extra = f" 等 {len(stacks)} 个" if len(stacks) > 8 else ""
        lines.append(f"- 文件：{preview}{extra}")
    if dropped:
        preview = "、".join(str(item) for item in dropped[:8])
        extra = f" 等 {len(dropped)} 项" if len(dropped) > 8 else ""
        lines.append(f"- 未纳入：{preview}{extra}")
    return lines


def _zh_review_lines(task_plan: TaskPlan, technical_analysis: dict | None = None) -> list[str]:
    analysis = technical_analysis or {}
    registration = analysis.get("registration_summary") or {}
    surface = analysis.get("surface_checks") or {}
    image_checks = analysis.get("image_checks") or {}
    failed = list((analysis.get("step_summary") or {}).get("failed") or [])
    skipped = {str(step) for step in ((analysis.get("step_summary") or {}).get("skipped") or [])}
    items: list[str] = []
    scoped = set(task_plan.execution_steps or []) | set(task_plan.report_steps or []) | set(task_plan.display_steps or [])
    qc_group = str(registration.get("qc_group") or "")
    if (registration.get("available") or "registration" in scoped) and "registration" not in skipped:
        note = f"（质控分组为 {qc_group}）" if qc_group and qc_group not in {"acceptable", "pass", "ok", "-"} else ""
        items.append(f"- [ ] 目视复核配准 overlay{note}，相似性度量不能代替目视检查")
    ga = task_plan.gestational_age or registration.get("gestational_age")
    if not ga:
        items.append("- [ ] 记录受试者孕周，并确认图谱周龄与实际孕周的匹配性")
    for key, value in image_checks.items():
        if str(value).startswith("WARN") and key not in skipped:
            items.append(f"- [ ] 复核{STEP_LABELS_ZH.get(key, key)}输出缺失或告警")
    missing_surfaces = surface.get("missing_surface_files") or []
    if missing_surfaces and "surface" not in skipped:
        items.append("- [ ] 补齐或重跑表面重建，并复核表面拓扑与解剖正确性")
    elif surface.get("present_surface_files") and "surface" not in skipped:
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
    if "不能计算 Dice / AUC" in titles:
        items.append("- [ ] 如需 Dice / AUC，请另行提供金标准分割或诊断标签，不要从本报告读取这些数值")
    if "不能划分扩张侧脑室及周围皮质下组织" in titles:
        items.append("- [ ] 侧脑室扩张分区需专用标注或工具，本报告未提供该结果")
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


def _zh_finding_lines(task_plan: TaskPlan, technical_analysis: dict | None) -> list[str]:
    lines = ["", "## 阅片要点", ""]
    if not technical_analysis:
        lines.extend([
            "> [!finding]",
            "> **本次没有可汇总的计算产物**",
            "> 请确认是否已导入结果后再阅片。",
            "",
        ])
        return lines
    skipped = {str(step) for step in ((technical_analysis.get("step_summary") or {}).get("skipped") or [])}
    image_checks = {
        key: value for key, value in (technical_analysis.get("image_checks") or {}).items()
        if key not in skipped
    }
    quality = _summarize_output_quality(
        image_checks,
        technical_analysis.get("surface_checks") or {},
        skipped=skipped,
    )
    registration = technical_analysis.get("registration_summary") or {}
    incomplete = "incomplete" in quality.lower()
    title = "**已执行范围内仍有缺失产物，请先看右侧影像**" if incomplete else "**技术产物可读，可供阅片**"
    bits = []
    if registration and "registration" not in skipped:
        group = str(registration.get("qc_group") or "")
        status = str(registration.get("status") or "")
        if group in {"acceptable", "pass", "ok"} or status in {"ok", "pass"}:
            bits.append("配准技术质控可接受，仍须目视 overlay。")
        elif status or group:
            bits.append(f"配准需复核（{status or group}）。")
    quantitative = technical_analysis.get("quantitative_summary") or {}
    roi_basic = quantitative.get("roi86_basic") or {}
    if roi_basic.get("available") and "roi" not in skipped:
        bits.append(f"ROI 分区 {roi_basic.get('roi_count')} 个，总体积 {_fmt_volume(roi_basic.get('total_volume_mm3'))}。")
    bits.append("不能替代临床诊断，也不能当作未做的步骤已经完成。")
    lines.extend(["> [!finding]", f"> {title}", f"> {' '.join(bits)}", ""])
    return lines


def _zh_qc_lines(step_qc: dict, report_steps: list[str], skipped: list[str] | None = None) -> list[str]:
    steps = step_qc.get("steps") or []
    skipped_ids = {str(step) for step in (skipped or [])}
    if report_steps:
        steps = [item for item in steps if item.get("step_id") in report_steps]
    executed = [
        item for item in steps
        if item.get("status") != "skipped" and str(item.get("step_id")) not in skipped_ids
    ]
    omitted = [
        item for item in steps
        if item.get("status") == "skipped" or str(item.get("step_id")) in skipped_ids
    ]
    if not executed and not omitted:
        return []
    key_metrics = {
        "mask_success_rate", "mattes", "global_correlation", "output_present",
        "nonzero_voxel_fraction", "label_count",
    }
    lines = ["", "## 已执行步骤质控"]
    for item in executed:
        label = STEP_LABELS_ZH.get(item.get("step_id"), item.get("step_id"))
        status = QC_STATUS_ZH.get(item.get("status"), item.get("status"))
        metrics = [m for m in (item.get("metrics") or []) if m.get("name") in key_metrics] or list(item.get("metrics") or [])[:2]
        brief = "；".join(
            f"{m.get('label') or m.get('name')} {m.get('value')}"
            .replace(" True", " 是")
            .replace(" False", " 否")
            for m in metrics
        )
        limit = QC_LIMIT_ZH.get((item.get("limitations") or [""])[0], (item.get("limitations") or ["仅反映该步技术完整性"])[0])
        line = f"- {label}：{status}"
        if brief:
            line += f"。{brief}"
        if limit:
            line += f"。说明：{limit}"
        lines.append(line)
    if omitted:
        names = "、".join(STEP_LABELS_ZH.get(item.get("step_id"), item.get("step_id")) for item in omitted)
        lines.extend(["", f"- 未纳入本次运行：{names}（不是失败）"])
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


def _zh_check_text(value: object) -> str:
    text = str(value)
    text = text.replace("PASS: ", "通过：").replace("PASS:", "通过：")
    text = text.replace("WARN: ", "告警：").replace("WARN:", "告警：")
    text = text.replace("missing file:", "未生成文件")
    text = text.replace("valid NIfTI dims=", "有效体积，尺寸=")
    return text


def _zh_findings(task_plan: TaskPlan, technical_analysis: dict | None) -> list[str]:
    if not technical_analysis:
        return ["", "## 技术结论", "- 本次没有可汇总的计算产物。"]
    registration = technical_analysis.get("registration_summary") or {}
    quantitative = technical_analysis.get("quantitative_summary") or {}
    roi_basic = quantitative.get("roi86_basic") or {}
    image_checks = technical_analysis.get("image_checks") or {}
    skipped = {str(step) for step in ((technical_analysis.get("step_summary") or {}).get("skipped") or [])}
    visible_checks = {key: value for key, value in image_checks.items() if key not in skipped}
    lines = ["", "## 技术结论"]
    quality = _summarize_output_quality(
        visible_checks,
        technical_analysis.get("surface_checks") or {},
        skipped=skipped,
    )
    if "incomplete" in quality.lower():
        lines.append("- 已执行范围内仍有缺失产物，请结合影像复核后再用于研究分析。")
    else:
        lines.append("- 已执行范围内的技术产物可读，可供医生阅片；不能替代临床诊断，也不能当作未执行步骤已经完成。")
    if registration and "registration" not in skipped:
        lines.append(
            f"- 配准状态：{registration.get('status') or '不可用'}；质控分组：{registration.get('qc_group') or '不可用'}"
        )
    if roi_basic.get("available") and "roi" not in skipped:
        lines.append(f"- ROI 分区数：{roi_basic.get('roi_count')}；总体积：{_fmt_volume(roi_basic.get('total_volume_mm3'))}")
    if visible_checks:
        lines.extend(["", "## 影像与测量"])
        for key, value in visible_checks.items():
            lines.append(f"- {STEP_LABELS_ZH.get(key, key)}：{_zh_check_text(value)}")
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
    lines = _zh_title_lines(task_plan)
    lines.extend(_zh_case_lines(task_plan))
    lines.extend(_zh_refusal_lines(task_plan))
    lines.extend(_zh_done_lines(task_plan, technical_analysis, completed, skipped))
    lines.extend(_zh_finding_lines(task_plan, technical_analysis))
    lines.extend(_zh_review_lines(task_plan, technical_analysis))
    lines.extend(_zh_comparison_lines(task_plan))
    lines.extend(["", "## 能力边界", CAPABILITY_BOUNDARY_ZH])
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
        system = (
            load_prompt(prompt_path) + "\n\n" + CAPABILITY_BOUNDARY_ZH
            + "\n用中文撰写。只保留医生需要的四块：未完成与拒绝、本次完成、阅片要点、阅片复核清单。"
            "拒绝项必须使用 `> [!refusal]` 并保留全部标题；阅片要点必须使用 `> [!finding]`；"
            "不要写质控数字、体素比例、文件名列表、NIfTI 尺寸或步骤日志。"
        )
        user = json.dumps({
            "user_request": task_plan.goal,
            "report_scope": report_steps or "all",
            "report_language": "zh",
            "refusals": task_plan.refusal_explanations,
            "deterministic_report": markdown,
            "medical_evidence": llm_evidence,
        }, ensure_ascii=False)
        validation_evidence = {
            "medical_evidence": evidence,
            "deterministic_report": markdown,
            "refusals": task_plan.refusal_explanations,
        }

        def check(text: str) -> tuple[str, list[str]]:
            restored = _restore_chinese_invariants(
                text, task_plan, technical_analysis, completed=completed, skipped=skipped,
            )
            errors = validate_llm_report(restored, validation_evidence)
            errors.extend(validate_chinese_report(
                restored,
                [str(item.get("title") or "") for item in task_plan.refusal_explanations],
            ))
            return restored, errors

        llm_markdown, llm_meta = _complete_report_with_repair(llm, system, user, check)
        report_json["llm"]["reporting"] = {
            "used": True, "status": "completed", "model": llm.config.model, **llm_meta,
        }
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
                f"- Input stack count: `{case_info.get('stack_count', case_info.get('btfe_stack_count', '-'))}`",
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
        system = load_prompt(prompt_path) + "\n\n" + CAPABILITY_BOUNDARY
        user = json.dumps({
            "user_request": task_plan.goal,
            "report_scope": report_steps or "all",
            "report_language": getattr(task_plan, "report_language", "auto"),
            "medical_evidence": evidence,
        }, ensure_ascii=False)

        def check(text: str) -> tuple[str, list[str]]:
            return text, validate_llm_report(text, evidence)

        llm_markdown, llm_meta = _complete_report_with_repair(llm, system, user, check)
        report_json["llm"]["reporting"] = {
            "used": True, "status": "completed", "model": llm.config.model, **llm_meta,
        }
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
            f"- Source stack count: `{case.get('stack_count', case.get('btfe_stack_count', '-'))}`",
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
    skipped = {str(step) for step in ((technical_analysis.get("step_summary") or {}).get("skipped") or [])}
    output_quality = _summarize_output_quality(image_checks, surface_checks, skipped=skipped)
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
        f"- Source stacks imported: `{case_info.get('stack_count', case_info.get('btfe_stack_count', '-'))}`",
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


def _summarize_output_quality(image_checks: dict, surface_checks: dict, skipped: set[str] | None = None) -> str:
    skipped_ids = skipped or set()
    visible = {key: value for key, value in image_checks.items() if key not in skipped_ids}
    has_image_warning = any(str(value).startswith("WARN") for value in visible.values())
    missing_surface = bool(surface_checks.get("missing_surface_files")) and "surface" not in skipped_ids
    missing_stats = bool(surface_checks.get("missing_stats_files")) and "surface" not in skipped_ids and "roi" not in skipped_ids
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
            "statement": f"Subject {case_info.get('subject', '-')} was processed with {case_info.get('stack_count', case_info.get('btfe_stack_count', '-'))} input stacks at requested GA {task_plan.gestational_age or '-'} weeks.",
            "evidence": "dashboard run metadata and staging stack file count",
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

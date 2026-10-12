"""Map pipeline/agentic failures to Chinese cause + next action."""

from __future__ import annotations

import re
from typing import Any

from agentic.clinic_paths import format_gestational_age_zh


FIELD_LABEL_ZH = {
    "gestational_age": "孕周",
    "atlas": "图谱",
    "atlas_week": "图谱周龄",
    "subject_dir": "病例目录",
    "work_root": "工作目录",
    "existing_run_dir": "已有运行目录",
    "reconstruction_tool": "重建方法",
    "reconstruction_compare_tools": "对比重建方法",
    "roi_mode": "ROI 模式",
    "surface": "表面重建",
    "execution_mode": "执行模式",
}

STEP_LABEL_ZH = {
    "extraction": "脑提取",
    "reconstruction": "三维重建",
    "registration": "图像配准",
    "tissue": "组织分割",
    "roi": "脑区划分",
    "surface": "表面重建",
    "pipeline": "流水线",
    "input_check": "输入检查",
    "metrics": "指标汇总",
}

_VALIDATION_TRANSLATIONS = (
    (re.compile(r"^Missing required parameter\(s\):\s*(.+)$", re.I), "缺少必要参数：{0}"),
    (re.compile(r"^atlas is required for registered-MRI downstream processing$", re.I), "配准及后续步骤需要图谱（atlas）。"),
    (re.compile(r"^gestational_age is required for ROI warp$", re.I), "ROI warp 需要填写孕周。"),
    (re.compile(r"^subject_dir not found:\s*(.+)$", re.I), "病例目录不存在：{0}"),
    (re.compile(r"^ANTs CLI not found:\s*(.+)$", re.I), "未找到 ANTs 命令行：{0}"),
    (re.compile(r"^ROI warp Python not found:\s*(.+)$", re.I), "未找到 ROI warp 环境的 Python：{0}"),
    (re.compile(r"^ROI warp environment cannot import ants:\s*(.+)$", re.I), "ROI warp 环境无法导入 ants：{0}"),
    (re.compile(r"^Unknown reconstruction tool:\s*(.+)$", re.I), "未知重建方法：{0}"),
    (re.compile(r"^Unknown reconstruction comparison tool\(s\):\s*(.+)$", re.I), "未知对比重建方法：{0}"),
    (re.compile(r"^Capability refusal blocks GPU execution$", re.I), "能力边界拒绝项阻止了 GPU 实算。"),
    (
        re.compile(r"^Fresh-run request conflicts with execution_mode=import_existing$", re.I),
        "请求要求重新开始，但当前执行模式是导入已有结果。",
    ),
    (
        re.compile(r"^Request/Dashboard conflict for (\w+):\s*natural language=(.+),\s*dashboard=(.+)\.\s*Dashboard fields take precedence\.$", re.I),
        None,  # handled via structured conflicts
    ),
)


def classify_failure(
    exit_code: int | None = None,
    message: str = "",
    log_text: str = "",
) -> dict[str, Any]:
    blob = f"{message}\n{log_text}"
    code = int(exit_code) if exit_code is not None else None

    if code == 75 or "already using work root" in blob:
        return _item(
            "work_root_lock",
            code,
            "同一病例工作目录仍被占用（另一个流水线还在写，或 Dashboard 等旧进程仍持有锁）。",
            "已完成步骤的产物还在，但现在不能写入。",
            "不要同时开两个流水线写同一目录。若仍被占用，停掉持有该 work root 下 .pipeline.lock 的进程后再 --resume。",
        )
    if code == 127 or "command not found" in blob.lower():
        return _item(
            "command_not_found",
            code,
            "命令未找到，或正在运行的 bash 脚本被改写导致行号错位。",
            "当前步骤没有正常结束；前面已完成的步骤仍可阅片。",
            "不要在流水线运行时编辑 run_single_case_pipeline.sh。修好脚本后从失败步 --resume。",
        )
    if "GLM" in blob and ("JSON" in blob or "parse" in blob.lower()):
        return _item(
            "llm_json_invalid",
            code,
            "语言模型没有返回可用 JSON，系统不会用规则兜底去占 GPU。",
            "没有授权实算。",
            "检查 GLM 配置后重试；不要把 fallback 计划当成已执行。",
        )
    if "BTFE" in blob or "mixed sequence" in blob.lower() or "静默" in blob or "三维栈" in blob or "3D 栈" in blob:
        return _item(
            "input_no_usable_stacks",
            code,
            "输入里没有可用于三维重建的同对比度多栈。",
            "没有开始重建。",
            "上传完整检查；系统会保留栈数最多的三维模态，并丢掉侦察像、其它对比度或非三维体积。",
        )
    if code not in (None, 0):
        return _item(
            "pipeline_exit",
            code,
            f"流水线异常退出（exit {code}）。",
            "请看失败步骤卡片；已完成步骤可以阅片，不能当成全流程结果。",
            "打开该步日志，按日志修复后 --resume。",
        )
    return _item(
        "unknown",
        code,
        message or "运行未成功完成。",
        "已完成步骤可阅片，未完成步骤不得当作全流程结果。",
        "查看 Dashboard 步骤状态和日志。",
    )


def incomplete_run_notice(steps: list[dict[str, Any]]) -> str | None:
    completed = [item.get("id") for item in steps if item.get("status") == "completed"]
    unfinished = [
        item.get("id")
        for item in steps
        if item.get("status") in {"pending", "failed", "running"}
    ]
    if completed and unfinished:
        return (
            f"已完成：{', '.join(str(item) for item in completed)}，可阅片。"
            f"未完成：{', '.join(str(item) for item in unfinished)}。不得当作全流程结果。"
        )
    return None


def summarize_plan_failure(
    errors: list[str] | None,
    conflicts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a clinician-facing plan-time failure object for UI + report."""
    error_list = [str(item).strip() for item in (errors or []) if str(item).strip()]
    conflict_list = [item for item in (conflicts or []) if isinstance(item, dict)]
    details: list[str] = []

    if conflict_list:
        for item in conflict_list:
            details.append(_conflict_detail_zh(item))
        if len(details) == 1:
            summary = f"计划未通过：{details[0]}"
        else:
            summary = f"计划未通过：表单与自然语言有 {len(details)} 处不一致。"
        field = str(conflict_list[0].get("field") or "field")
        next_action = f"请把自然语言和表单中的{FIELD_LABEL_ZH.get(field, field)}改成一致后重新提交。"
        if len(conflict_list) > 1:
            next_action = "请统一自然语言与表单中的冲突项后重新提交。"
        return _failure(
            phase="planning",
            code="request_dashboard_conflict",
            summary_zh=summary,
            details_zh=details,
            next_action_zh=next_action,
            errors=error_list,
            conflicts=conflict_list,
        )

    for error in error_list:
        translated = translate_validation_error(error)
        if translated:
            details.append(translated)
    if not details and error_list:
        details = list(error_list)
    if not details:
        details = ["计划校验未通过。"]
    summary = details[0] if len(details) == 1 else f"计划未通过：共 {len(details)} 项校验问题。"
    if not summary.startswith("计划未通过"):
        summary = f"计划未通过：{summary}"
    return _failure(
        phase="planning",
        code="plan_validation",
        summary_zh=summary,
        details_zh=details,
        next_action_zh="请按上方原因修正输入或配置后重新提交。",
        errors=error_list,
        conflicts=[],
    )


def summarize_execution_failure(
    results: list[dict[str, Any]] | None = None,
    *,
    exc: BaseException | None = None,
) -> dict[str, Any]:
    """Build a clinician-facing runtime failure object."""
    if exc is not None:
        classified = classify_failure(message=f"{type(exc).__name__}: {exc}")
        return _failure(
            phase="execution",
            code=str(classified.get("code") or "runtime_exception"),
            summary_zh=f"分析未完成：{classified['cause_zh']}",
            details_zh=[classified["cause_zh"], str(exc)],
            next_action_zh=str(classified.get("next_action_zh") or "查看日志后重试。"),
            errors=[f"{type(exc).__name__}: {exc}"],
            conflicts=[],
        )
    failed = [
        item for item in (results or [])
        if isinstance(item, dict) and item.get("status") == "failed"
    ]
    if not failed:
        return _failure(
            phase="execution",
            code="execution_failed",
            summary_zh="分析未完成，请查看报告中的说明。",
            details_zh=[],
            next_action_zh="打开步骤日志确认失败原因后重试或续跑。",
            errors=[],
            conflicts=[],
        )
    first = failed[0]
    step_id = str(first.get("step_id") or first.get("id") or "step")
    label = STEP_LABEL_ZH.get(step_id, step_id)
    message = str(first.get("message") or first.get("error") or "").strip()
    classified = classify_failure(message=message) if message else None
    if classified and classified.get("code") not in {None, "unknown"}:
        cause = str(classified["cause_zh"])
        next_action = str(classified.get("next_action_zh") or "打开该步日志排查后重试。")
        code = str(classified.get("code") or "step_failed")
    else:
        cause = message or f"{label}未成功完成。"
        next_action = f"打开「{label}」步骤日志排查后重试或续跑。"
        code = "step_failed"
    summary = f"分析未完成：{label}失败"
    if message and message not in summary:
        short = message if len(message) <= 80 else message[:77] + "…"
        summary = f"{summary}（{short}）"
    details = [f"{label}：{cause}"]
    if len(failed) > 1:
        others = "、".join(
            STEP_LABEL_ZH.get(str(item.get("step_id") or item.get("id")), str(item.get("step_id") or item.get("id")))
            for item in failed[1:]
        )
        details.append(f"另有失败步骤：{others}")
    return _failure(
        phase="execution",
        code=code,
        summary_zh=summary,
        details_zh=details,
        next_action_zh=next_action,
        errors=[message] if message else [],
        conflicts=[],
    )


def translate_validation_error(error: str) -> str:
    text = str(error or "").strip()
    if not text:
        return ""
    if text.startswith("Request/Dashboard conflict for "):
        match = re.match(
            r"Request/Dashboard conflict for (\w+):\s*natural language=(.+),\s*dashboard=(.+)\.\s*Dashboard fields take precedence\.$",
            text,
            re.I,
        )
        if match:
            field, natural, dashboard = match.group(1), match.group(2), match.group(3)
            return _conflict_detail_zh(
                {
                    "field": field,
                    "natural_language": _strip_repr(natural),
                    "dashboard": _strip_repr(dashboard),
                }
            )
    for pattern, template in _VALIDATION_TRANSLATIONS:
        match = pattern.match(text)
        if not match:
            continue
        if template is None:
            continue
        return template.format(*match.groups())
    if re.search(r"[\u4e00-\u9fff]", text):
        return text
    return f"校验未通过：{text}"


def _conflict_detail_zh(item: dict[str, Any]) -> str:
    field = str(item.get("field") or "field")
    label = FIELD_LABEL_ZH.get(field, field)
    natural = _display_value_zh(field, item.get("natural_language"))
    dashboard = _display_value_zh(field, item.get("dashboard"))
    return f"自然语言中的{label}「{natural}」与表单「{dashboard}」不一致（已优先采用表单）"


def _display_value_zh(field: str, value: Any) -> str:
    if field == "gestational_age":
        text = format_gestational_age_zh(value)
        if text:
            return text
    if field == "surface":
        if value in {True, "on", "true", "True", 1, "1"}:
            return "开启"
        if value in {False, "off", "false", "False", 0, "0"}:
            return "关闭"
    if isinstance(value, (list, tuple)):
        return "、".join(str(item) for item in value) or "（空）"
    if value is None or value == "":
        return "（空）"
    return str(value).strip()


def _strip_repr(value: str) -> str:
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _failure(
    *,
    phase: str,
    code: str,
    summary_zh: str,
    details_zh: list[str],
    next_action_zh: str,
    errors: list[str],
    conflicts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "phase": phase,
        "code": code,
        "summary_zh": summary_zh,
        "details_zh": details_zh,
        "next_action_zh": next_action_zh,
        "errors": errors,
        "conflicts": conflicts,
    }


def _item(code: str, exit_code: int | None, cause: str, meaning: str, next_action: str) -> dict[str, Any]:
    return {
        "code": code,
        "exit_code": exit_code,
        "cause_zh": cause,
        "meaning_zh": meaning,
        "next_action_zh": next_action,
    }

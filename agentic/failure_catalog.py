"""Map pipeline/agentic failures to Chinese cause + next action."""

from __future__ import annotations

import re
from typing import Any


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
    if "BTFE" in blob or "mixed sequence" in blob.lower() or "静默" in blob:
        return _item(
            "input_not_btfe",
            code,
            "输入不是可用的胎儿脑 BTFE 多栈，或夹杂了其他序列。",
            "没有开始重建。",
            "只保留 BTFE_*.nii.gz，删掉 T1/DWI 等；系统不会再把文件改名为 BTFE_01。",
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


def _item(code: str, exit_code: int | None, cause: str, meaning: str, next_action: str) -> dict[str, Any]:
    return {
        "code": code,
        "exit_code": exit_code,
        "cause_zh": cause,
        "meaning_zh": meaning,
        "next_action_zh": next_action,
    }

"""One-line clinic progress from dashboard steps[]."""

from __future__ import annotations

from typing import Any


STEP_LABELS_ZH = {
    "extraction": "脑提取",
    "reconstruction": "三维重建",
    "registration": "图像配准",
    "tissue": "组织分割",
    "roi": "脑区划分",
    "surface": "表面重建",
}

PIPELINE_ORDER = ("extraction", "reconstruction", "registration", "tissue", "roi", "surface")


def labeled_steps(steps: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [item for item in (steps or []) if item.get("id") in STEP_LABELS_ZH]


def step_label(step_id: str) -> str:
    return STEP_LABELS_ZH.get(step_id, step_id)


def next_step_after(step_id: str) -> str | None:
    if step_id not in PIPELINE_ORDER:
        return None
    index = PIPELINE_ORDER.index(step_id)
    if index + 1 >= len(PIPELINE_ORDER):
        return None
    return PIPELINE_ORDER[index + 1]


def format_clinic_progress(steps: list[dict[str, Any]] | None, run_status: str = "") -> str:
    """Match the clinic top-bar line: 处理中 · 三维重建（2/6） · 脑提取已完成."""
    named = labeled_steps(steps)
    failed = next((item for item in named if item.get("status") == "failed"), None)
    if failed or run_status == "failed":
        target = failed or next((item for item in named if item.get("status") == "running"), None) or (named[0] if named else None)
        if target:
            return f"未完成 · {step_label(str(target.get('id')))}"
        return "分析未完成，请查看报告中的说明。"
    current = next((item for item in named if item.get("status") == "running"), None)
    if current is None:
        current = next((item for item in named if item.get("status") == "pending"), None)
    if current is None:
        all_done = bool(named) and all(item.get("status") in {"completed", "skipped"} for item in named)
        if all_done and run_status == "running":
            return "影像处理已完成，正在生成报告…"
        if all_done or run_status == "completed":
            return "分析已完成"
        return "正在分析，请稍候…"
    index = next((i for i, item in enumerate(named) if item.get("id") == current.get("id")), 0)
    done = [item for item in named if item.get("status") == "completed"]
    parts = ["处理中", f"{step_label(str(current.get('id')))}（{index + 1}/{len(named)}）"]
    if done:
        parts.append(f"{step_label(str(done[-1].get('id')))}已完成")
    return " · ".join(parts)


def gallery_badges(steps: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    labels = {
        "completed": "已完成",
        "running": "处理中",
        "failed": "未完成",
        "skipped": "未执行",
        "pending": "等待中",
    }
    return [
        {
            "id": str(item.get("id")),
            "label": step_label(str(item.get("id"))),
            "status": str(item.get("status") or "pending"),
            "badge": labels.get(str(item.get("status") or "pending"), str(item.get("status") or "未知")),
        }
        for item in labeled_steps(steps)
    ]

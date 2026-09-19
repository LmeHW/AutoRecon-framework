from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from dataclasses import fields
import re


TaskType = str

RunStatus = Literal["created", "planned", "running", "completed", "failed", "cancelled"]
StepStatus = Literal["pending", "running", "completed", "failed", "skipped"]


_SUPPORTED_REPORT_OUTPUT = re.compile(
    r"^(?:final_report(?:_zh)?|final_combined_report|"
    r"(?:extraction|reconstruction|registration|tissue|roi|surface|metrics)_report)$",
    re.I,
)


def normalize_unfulfilled_requests(items: list[str]) -> list[str]:
    """Remove report deliverables already implemented by the post-run Reporter."""
    normalized: list[str] = []
    for item in items:
        value = str(item).strip()
        if _SUPPORTED_REPORT_OUTPUT.fullmatch(value):
            continue
        if "无对应报告生成工具" in value and ("报告" in value or "report" in value.lower()):
            continue
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class UserRequest:
    raw_text: str
    task_type: TaskType
    intent: str = ""
    subject_dir: str | None = None
    work_root: str | None = None
    gestational_age: float | None = None
    atlas: str | None = None
    atlas_week: int | None = None
    atlas_rule: str | None = None
    reconstruction_tool: str = "frost"
    reconstruction_compare_tools: list[str] = field(default_factory=list)
    roi_mode: str = "warp"
    surface: str = "auto"
    execution_mode: str = "plan_only"
    existing_run_dir: str | None = None
    resume: bool = False
    display_steps: list[str] = field(default_factory=list)
    execution_steps: list[str] = field(default_factory=list)
    report_steps: list[str] = field(default_factory=list)
    requested_outputs: list[str] = field(default_factory=list)
    report_language: str = "auto"
    report_detail: str = "complete"
    report_layout: str = "combined"
    constraints: list[str] = field(default_factory=list)
    unfulfilled_requests: list[str] = field(default_factory=list)
    refusal_explanations: list[dict[str, Any]] = field(default_factory=list)
    reused_steps: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unsupported_reason: str | None = None
    case_label: str | None = None
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlanStep:
    id: str
    tool: str
    depends_on: list[str] = field(default_factory=list)
    required: bool = True
    status: StepStatus = "pending"
    reason: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskPlan:
    goal: str
    task_type: TaskType
    subject_dir: str | None
    work_root: str | None
    gestational_age: float | None
    atlas: str | None
    atlas_week: int | None
    atlas_rule: str | None
    roi_mode: str
    surface: str
    execution_mode: str
    existing_run_dir: str | None
    steps: list[PlanStep]
    reconstruction_tool: str = "frost"
    reconstruction_compare_tools: list[str] = field(default_factory=list)
    resume: bool = False
    display_steps: list[str] = field(default_factory=list)
    execution_steps: list[str] = field(default_factory=list)
    report_steps: list[str] = field(default_factory=list)
    requested_outputs: list[str] = field(default_factory=list)
    report_language: str = "auto"
    report_detail: str = "complete"
    report_layout: str = "combined"
    raw_text: str = ""
    constraints: list[str] = field(default_factory=list)
    unfulfilled_requests: list[str] = field(default_factory=list)
    refusal_explanations: list[dict[str, Any]] = field(default_factory=list)
    reused_steps: list[str] = field(default_factory=list)
    planner_source: str = "rules"
    planner_notes: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unsupported_reason: str | None = None
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["steps"] = [step.to_dict() for step in self.steps]
        return data


@dataclass
class StepResult:
    step_id: str
    tool: str
    status: StepStatus
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    log: str | None = None
    error: str | None = None
    message: str = ""
    started_at: str | None = None
    ended_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunState:
    run_id: str
    status: RunStatus
    request: dict[str, Any]
    plan: dict[str, Any] | None = None
    step_results: list[dict[str, Any]] = field(default_factory=list)
    report_markdown: str = ""
    report_json: dict[str, Any] = field(default_factory=dict)
    dashboard: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["updated_at"] = utc_now()
        return data


def path_or_none(value: str | None) -> str | None:
    if not value:
        return None
    return str(Path(value).expanduser())


def _known(cls, data: dict) -> dict:
    names = {item.name for item in fields(cls)}
    return {key: value for key, value in data.items() if key in names}


def user_request_from_dict(data: dict) -> UserRequest:
    return UserRequest(**_known(UserRequest, data))


def task_plan_from_dict(data: dict) -> TaskPlan:
    values = _known(TaskPlan, data)
    values["steps"] = [PlanStep(**_known(PlanStep, item)) for item in data.get("steps", [])]
    return TaskPlan(**values)

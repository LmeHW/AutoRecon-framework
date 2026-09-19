"""Frozen specifications for the seven-case GLM acceptance batch."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = Path("/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain/IngeniaAmbition_patch2")
ATLAS_ROOT = Path("/mnt/sda/public/00_Shares/Fetal_brain/FBA-Chinese/atlas")
HISTORICAL = {
    "AnHuiJing": PROJECT_ROOT / "runs/legacy/AnHuiJing/run01",
    "CaoLi": PROJECT_ROOT / "runs/legacy/CaoLi/registered_run02",
}
FULL = ["extraction", "reconstruction", "registration", "tissue", "roi", "surface"]
COMPARE_TOOLS = ["frost", "nesvor", "autosvrtk", "niftymic"]
SEMANTIC_FIELDS = (
    "execution_mode",
    "subject_dir",
    "work_root",
    "existing_run_dir",
    "gestational_age",
    "atlas",
    "atlas_week",
    "atlas_rule",
    "reconstruction_tool",
    "reconstruction_compare_tools",
    "execution_steps",
    "display_steps",
    "report_steps",
    "report_language",
    "unfulfilled_requests",
    "resume",
)


def ga(weeks: int, days: int = 0) -> float:
    return weeks + days / 7


def _case(**payload: Any) -> dict[str, Any]:
    return deepcopy(payload)


def build_cases(batch_root: Path) -> list[dict[str, Any]]:
    cases_root = batch_root / "cases"
    return [
        _case(
            case_id="I01",
            type="import",
            subject="AnHuiJing",
            natural_language="导入已有结果，输出技术指标，并判断是否正常。",
            execution_mode="import_existing",
            existing_run_dir=str(HISTORICAL["AnHuiJing"]),
            work_root=str(cases_root / "I01" / "work"),
            gestational_age=None,
            atlas=None,
            atlas_week=None,
            atlas_rule=None,
            reconstruction_tool="frost",
            reconstruction_compare_tools=[],
            execution_steps=[],
            display_steps=[],
            report_steps=[],
            report_language="auto",
            unfulfilled_requests=["normality_assessment_requires_validated_GA_reference_and_expert_review"],
            screenshots=["I01_dashboard_overview.png"],
            capability_boundaries=["normality_assessment_requires_validated_GA_reference_and_expert_review"],
            expected_products=["request.json", "plan.json", "state.json", "report.md", "qc.json"],
            dag=["input_check", "visualization", "metrics"],
            notes="Read-only import. Do not rerun pipeline steps. Refuse unaudited normality claims.",
        ),
        _case(
            case_id="I02",
            type="import",
            subject="CaoLi",
            natural_language="只展示配准结果，生成完整技术报告，并发送到医院系统。",
            execution_mode="import_existing",
            existing_run_dir=str(HISTORICAL["CaoLi"]),
            work_root=str(cases_root / "I02" / "work"),
            gestational_age=None,
            atlas=None,
            atlas_week=None,
            atlas_rule=None,
            reconstruction_tool="frost",
            reconstruction_compare_tools=[],
            execution_steps=[],
            display_steps=["registration"],
            report_steps=[],
            report_language="auto",
            unfulfilled_requests=["external_hospital_delivery_unsupported"],
            screenshots=["I02_dashboard_overview.png"],
            capability_boundaries=["external_hospital_delivery_unsupported"],
            expected_products=["request.json", "plan.json", "state.json", "report.md", "qc.json"],
            dag=["input_check", "visualization", "metrics"],
            notes="Display registration only. Report uses all available evidence. External hospital delivery is unsupported.",
        ),
        _case(
            case_id="N01",
            type="partial",
            subject="TangWen",
            natural_language="用 FROST 重新运行脑提取和重建，到此停止。",
            execution_mode="run_pipeline",
            subject_dir=str(DATASET_ROOT / "nii/TangWen"),
            work_root=str(cases_root / "N01" / "pipeline"),
            gestational_age=ga(25),
            atlas=str(ATLAS_ROOT / "25w.nii.gz"),
            atlas_week=25,
            atlas_rule="exact",
            reconstruction_tool="frost",
            reconstruction_compare_tools=[],
            execution_steps=["extraction", "reconstruction"],
            display_steps=[],
            report_steps=[],
            report_language="auto",
            unfulfilled_requests=[],
            screenshots=["N01_dashboard_overview.png", "N01_reconstruction_preview.png"],
            capability_boundaries=[],
            expected_products=["request.json", "plan.json", "state.json", "report.md", "qc.json", "acceptance.json"],
            dag=["input_check", "extraction", "reconstruction"],
            resume_after=True,
            notes="Must stop after reconstruction. Registration and later stages stay skipped.",
        ),
        _case(
            case_id="N02",
            type="partial",
            subject="DaiLuLu",
            natural_language="重新运行到配准为止，给出 registration QC。",
            execution_mode="run_pipeline",
            subject_dir=str(DATASET_ROOT / "nii/DaiLuLu"),
            work_root=str(cases_root / "N02" / "pipeline"),
            gestational_age=ga(31, 4),
            atlas=str(ATLAS_ROOT / "31w.nii.gz"),
            atlas_week=31,
            atlas_rule="exact",
            reconstruction_tool="frost",
            reconstruction_compare_tools=[],
            execution_steps=["extraction", "reconstruction", "registration"],
            display_steps=[],
            report_steps=["registration"],
            report_language="auto",
            unfulfilled_requests=[],
            screenshots=["N02_dashboard_overview.png", "N02_registration_qc_preview.png"],
            capability_boundaries=[],
            expected_products=["request.json", "plan.json", "state.json", "report.md", "qc.json", "acceptance.json"],
            dag=["input_check", "extraction", "reconstruction", "registration"],
            resume_after=True,
            notes="Must stop after registration and surface the registration QC evidence.",
        ),
        _case(
            case_id="N03",
            type="full",
            subject="XuJing",
            natural_language="完整处理这个病例，输出技术指标和中文报告。",
            execution_mode="run_pipeline",
            subject_dir=str(DATASET_ROOT / "nii/XuJing"),
            work_root=str(cases_root / "N03" / "pipeline"),
            gestational_age=ga(35, 2),
            atlas=str(ATLAS_ROOT / "35w.nii.gz"),
            atlas_week=35,
            atlas_rule="exact",
            reconstruction_tool="frost",
            reconstruction_compare_tools=[],
            execution_steps=list(FULL),
            display_steps=[],
            report_steps=[],
            report_language="zh",
            unfulfilled_requests=[],
            screenshots=["N03_dashboard_overview.png", "N03_reconstruction_preview.png", "N03_final_report.png"],
            capability_boundaries=[],
            expected_products=["request.json", "plan.json", "state.json", "report.md", "qc.json", "acceptance.json"],
            dag=["input_check", *FULL],
            resume_after=True,
            notes="Six-stage full pipeline with atlas=35w.",
        ),
        _case(
            case_id="N04",
            type="full/boundary",
            subject="ChenYanTing",
            natural_language="完整处理这个病例，使用35周图谱，并给出孕周百分位。",
            execution_mode="run_pipeline",
            subject_dir=str(DATASET_ROOT / "nii/ChenYanTing"),
            work_root=str(cases_root / "N04" / "pipeline"),
            gestational_age=ga(36, 5),
            atlas=str(ATLAS_ROOT / "35w.nii.gz"),
            atlas_week=35,
            atlas_rule="nearest_from_36w",
            reconstruction_tool="frost",
            reconstruction_compare_tools=[],
            execution_steps=list(FULL),
            display_steps=[],
            report_steps=[],
            report_language="auto",
            unfulfilled_requests=["normative_comparison_requires_validated_GA_reference"],
            screenshots=["N04_dashboard_overview.png", "N04_registration_ga_atlas.png"],
            capability_boundaries=["normative_comparison_requires_validated_GA_reference"],
            expected_products=["request.json", "plan.json", "state.json", "report.md", "qc.json", "acceptance.json"],
            dag=["input_check", *FULL],
            resume_after=True,
            notes="Keep actual GA 36w+5. Atlas week remains 35 with nearest_from_36w. No percentile without a validated reference.",
        ),
        _case(
            case_id="C01",
            type="comparison",
            subject="LiChenQian",
            natural_language="从原始数据运行四个重建方法，比较全部结果并推荐最佳方法。",
            execution_mode="run_pipeline",
            subject_dir=str(DATASET_ROOT / "nii/LiChenQian"),
            work_root=str(cases_root / "C01" / "pipeline"),
            gestational_age=ga(29),
            atlas=str(ATLAS_ROOT / "29w.nii.gz"),
            atlas_week=29,
            atlas_rule="exact",
            reconstruction_tool="frost",
            reconstruction_compare_tools=list(COMPARE_TOOLS),
            execution_steps=["extraction", "reconstruction", "registration"],
            display_steps=[],
            report_steps=[],
            report_language="auto",
            unfulfilled_requests=["best_method_requires_expert_blind_review"],
            screenshots=["C01_dashboard_overview.png", "C01_blind_comparison.png", "C01_ranking.png"],
            capability_boundaries=["best_method_requires_expert_blind_review"],
            expected_products=[
                "request.json", "plan.json", "state.json", "report.md", "qc.json",
                "comparison/ranking.json", "comparison/automatic_metrics.csv",
                "comparison/blind_mapping.json", "comparison/comparison_report.md",
            ],
            dag=["input_check", "extraction", "reconstruction", "registration"],
            resume_after=True,
            notes="One extraction, four reconstruction backends, independent registration/QC, then automatic ranking. No final best method without expert review.",
        ),
    ]


def semantic_payload(request: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(request.get(key)) for key in SEMANTIC_FIELDS}


def expected_semantics(case: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "execution_mode": case["execution_mode"],
        "reconstruction_tool": case["reconstruction_tool"],
        "reconstruction_compare_tools": list(case["reconstruction_compare_tools"]),
        "execution_steps": list(case["execution_steps"]),
        "display_steps": list(case["display_steps"]),
        "report_language": case["report_language"],
        "unfulfilled_requests": list(case["unfulfilled_requests"]),
        "resume": bool(case.get("resume")),
        "atlas_week": case["atlas_week"],
        "atlas_rule": case["atlas_rule"],
        "gestational_age": case["gestational_age"],
    }
    mode = case["execution_mode"]
    if case.get("inject_paths") is False:
        expected["existing_run_dir"] = None
        expected["subject_dir"] = None
        expected["work_root"] = None
        expected["atlas"] = None
        expected["atlas_week"] = None
        expected["atlas_rule"] = None
        expected["gestational_age"] = None
        if mode == "import_existing":
            expected["resume"] = False
        elif mode == "continue_from_run":
            expected["resume"] = True if case.get("resume", True) else False
        return expected
    if mode == "import_existing":
        expected["existing_run_dir"] = case["existing_run_dir"]
        expected["subject_dir"] = None
        expected["work_root"] = None
        expected["atlas"] = None
        expected["atlas_week"] = None
        expected["atlas_rule"] = None
        expected["gestational_age"] = None
        expected["resume"] = False
    elif mode == "plan_only":
        expected["subject_dir"] = case.get("subject_dir")
        expected["work_root"] = case.get("work_root")
        expected["existing_run_dir"] = case.get("existing_run_dir")
        expected["atlas"] = case.get("atlas")
    elif mode == "continue_from_run":
        expected["existing_run_dir"] = case.get("existing_run_dir")
        expected["subject_dir"] = case.get("subject_dir")
        expected["work_root"] = case.get("work_root")
        expected["atlas"] = case.get("atlas")
        expected["resume"] = True if case.get("resume", True) else False
    else:
        expected["subject_dir"] = case.get("subject_dir")
        expected["work_root"] = case.get("work_root")
        expected["existing_run_dir"] = case.get("existing_run_dir")
        expected["atlas"] = case.get("atlas")
    return expected


def explicit_overrides(case: dict[str, Any]) -> dict[str, Any]:
    """Local path/GA/atlas injection. Natural language never contains these paths."""
    if case.get("inject_paths") is False:
        return {"execution_mode": case["execution_mode"], "explicit_fields": ["execution_mode"]}
    overrides: dict[str, Any] = {"execution_mode": case["execution_mode"]}
    explicit = ["execution_mode"]
    mode = case["execution_mode"]
    if mode == "import_existing":
        overrides["existing_run_dir"] = case["existing_run_dir"]
        explicit.append("existing_run_dir")
        if case.get("display_steps"):
            overrides["display_steps"] = list(case["display_steps"])
            explicit.append("display_steps")
    elif mode == "continue_from_run":
        for key in (
            "existing_run_dir", "work_root", "subject_dir", "gestational_age",
            "atlas", "atlas_week", "atlas_rule", "reconstruction_tool",
        ):
            if case.get(key) not in (None, "", []):
                overrides[key] = case[key]
                explicit.append(key)
        if case.get("execution_steps"):
            overrides["execution_steps"] = list(case["execution_steps"])
            explicit.append("execution_steps")
        if case.get("display_steps"):
            overrides["display_steps"] = list(case["display_steps"])
            explicit.append("display_steps")
        overrides["resume"] = True if case.get("resume", True) else False
        explicit.append("resume")
    else:
        for key in ("subject_dir", "work_root", "gestational_age", "atlas", "atlas_week", "atlas_rule", "reconstruction_tool"):
            if case.get(key) not in (None, "", []):
                overrides[key] = case[key]
                explicit.append(key)
        if case.get("reconstruction_compare_tools"):
            overrides["reconstruction_compare_tools"] = list(case["reconstruction_compare_tools"])
            explicit.append("reconstruction_compare_tools")
        if case.get("execution_steps"):
            overrides["execution_steps"] = list(case["execution_steps"])
            explicit.append("execution_steps")
        if case.get("display_steps"):
            overrides["display_steps"] = list(case["display_steps"])
            explicit.append("display_steps")
        if case.get("resume"):
            overrides["resume"] = True
            explicit.append("resume")
    if case.get("report_language") not in (None, "", "auto"):
        overrides["report_language"] = case["report_language"]
        explicit.append("report_language")
    overrides["explicit_fields"] = explicit
    return overrides

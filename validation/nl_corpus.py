from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = Path("/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain/IngeniaAmbition_patch2")
ATLAS_ROOT = Path("/mnt/sda/public/00_Shares/Fetal_brain/FBA-Chinese/atlas")
VALIDATION_RUN_ROOT = PROJECT_ROOT / "validation_runs"

FULL = ["extraction", "reconstruction", "registration", "tissue", "roi", "surface"]


def _case(
    case_id: str,
    category: str,
    text: str,
    *,
    overrides: dict[str, Any] | None = None,
    expected: dict[str, Any] | None = None,
    allow_execute: bool = False,
    report_must_include: list[str] | None = None,
    report_must_not_include: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "category": category,
        "natural_language": text,
        "overrides": overrides or {},
        "expected": expected or {},
        "allow_execute": allow_execute,
        "report_must_include": report_must_include or [],
        "report_must_not_include": report_must_not_include or ["临床诊断", "医学正常"],
    }


def build_corpus() -> list[dict[str, Any]]:
    existing = str(PROJECT_ROOT / "runs/legacy/AnHuiJing/run01")
    subject = str(DATASET_ROOT / "nii/AnHuiJing")
    work = str(VALIDATION_RUN_ROOT / "nl/AnHuiJing")
    atlas31 = str(ATLAS_ROOT / "31w.nii.gz")
    explicit_run = {
        "execution_mode": "run_pipeline", "subject_dir": subject, "work_root": work,
        "atlas": atlas31, "gestational_age": 31,
        "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas", "gestational_age"],
    }
    explicit_import = {
        "execution_mode": "import_existing", "existing_run_dir": existing,
        "explicit_fields": ["execution_mode", "existing_run_dir"],
    }
    rows: list[dict[str, Any]] = []

    # 12 execution-mode requests.
    mode_specs = [
        ("请先检查输入并给出处理计划，不要运行。", {}, {"execution_mode": "plan_only"}),
        ("Plan how to reconstruct this fetal MRI; do not execute.", {}, {"execution_mode": "plan_only"}),
        ("只做方案设计，暂时不要启动GPU。", {}, {"execution_mode": "plan_only"}),
        ("导入已有结果并生成技术报告。", explicit_import, {"execution_mode": "import_existing", "execution_steps": []}),
        ("Import existing run and show every available stage.", explicit_import, {"execution_mode": "import_existing", "execution_steps": []}),
        ("使用现有run查看QC，不重复计算。", explicit_import, {"execution_mode": "import_existing", "execution_steps": []}),
        ("从原始BTFE完整重跑。", explicit_run, {"execution_mode": "run_pipeline", "execution_steps": FULL}),
        ("Please rerun the complete pipeline from scratch.", explicit_run, {"execution_mode": "run_pipeline", "execution_steps": FULL}),
        ("重新运行脑提取、重建和配准。", explicit_run, {"execution_mode": "run_pipeline", "execution_steps": ["extraction", "reconstruction", "registration"]}),
        ("断点继续完整流程。", {**explicit_run, "resume": True, "explicit_fields": explicit_run["explicit_fields"] + ["resume"]}, {"execution_mode": "run_pipeline", "resume": True, "execution_steps": FULL}),
        ("Resume reconstruction from verified artifacts.", {**explicit_run, "resume": True, "explicit_fields": explicit_run["explicit_fields"] + ["resume"]}, {"execution_mode": "run_pipeline", "resume": True, "execution_steps": ["extraction", "reconstruction"]}),
        ("继续上次任务，只重跑registration。", {**explicit_run, "resume": True, "explicit_fields": explicit_run["explicit_fields"] + ["resume"]}, {"execution_mode": "run_pipeline", "resume": True, "execution_steps": ["extraction", "reconstruction", "registration"]}),
    ]
    for index, (text, overrides, expected) in enumerate(mode_specs, 1):
        rows.append(_case(f"mode_{index:02d}", "execution_mode", text, overrides=deepcopy(overrides), expected=expected))

    # 12 independent execution/display/report scope requests.
    scope_specs = [
        ("重新运行脑提取。", ["extraction"], [], []),
        ("重新运行重建。", ["extraction", "reconstruction"], [], []),
        ("重新运行registration和组织分割。", ["extraction", "reconstruction", "registration", "tissue"], [], []),
        ("重跑ROI和surface。", FULL, [], []),
        ("完整重跑六个步骤。", FULL, [], []),
        ("Run extraction, reconstruction and registration.", ["extraction", "reconstruction", "registration"], [], []),
        ("导入已有run，只展示reconstruction。", [], ["reconstruction"], []),
        ("导入已有run，仅显示配准结果。", [], ["registration"], []),
        ("Import existing run; show only tissue and ROI.", [], ["tissue", "roi"], []),
        ("导入已有run，只报告surface。", [], [], ["surface"]),
        ("导入已有run，只展示重建，但用全部证据生成完整报告。", [], ["reconstruction"], []),
        ("导入已有run，展示ROI，只报告registration。", [], ["roi"], ["registration"]),
    ]
    for index, (text, execution, display, report) in enumerate(scope_specs, 1):
        is_import = "导入" in text or text.startswith("Import")
        overrides = deepcopy(explicit_import if is_import else explicit_run)
        expected = {"execution_steps": execution, "display_steps": display, "report_steps": report}
        rows.append(_case(f"scope_{index:02d}", "scope", text, overrides=overrides, expected=expected))

    # 8 parameter and atlas-routing requests.
    parameter_specs = [
        ("用FROST从原始数据重跑reconstruction。", "frost", 25, "TangWen", "25w.nii.gz", "warp", "auto"),
        ("用NeSVoR重新运行重建。", "nesvor", 27, "ShiYuQing", "27w.nii.gz", "warp", "auto"),
        ("Use AutoSVRTK to rerun reconstruction.", "autosvrtk", 29, "LiChenQian", "29w.nii.gz", "warp", "off"),
        ("使用NiftyMIC重建并关闭surface。", "niftymic", 31, "DaiLuLu", "31w.nii.gz", "warp", "off"),
        ("33周病例用33周图谱完成ROI和surface。", "frost", 33, "ZhouMinMin", "33w.nii.gz", "warp", "on"),
        ("35周病例使用35w atlas做完整流程。", "frost", 35, "XuJing", "35w.nii.gz", "warp", "auto"),
        ("36周+5病例保留实际孕周，但使用35周最近图谱。", "frost", 36.714, "ChenYanTing", "35w.nii.gz", "warp", "auto"),
        ("38周+1，atlas上限按35w处理，运行全部步骤。", "frost", 38.143, "ZuoXiaoFen", "35w.nii.gz", "warp", "auto"),
    ]
    for index, (text, backend, ga, name, atlas_name, roi_mode, surface) in enumerate(parameter_specs, 1):
        overrides = {
            "execution_mode": "run_pipeline",
            "subject_dir": str(DATASET_ROOT / "nii" / name),
            "work_root": str(VALIDATION_RUN_ROOT / "real" / name),
            "gestational_age": ga,
            "atlas": str(ATLAS_ROOT / atlas_name),
            "atlas_week": int(atlas_name.removesuffix("w.nii.gz")),
            "atlas_rule": "exact" if ga <= 35 else f"nearest_from_{int(ga)}w",
            "reconstruction_tool": backend,
            "roi_mode": roi_mode,
            "surface": surface,
            "explicit_fields": ["execution_mode", "subject_dir", "work_root", "gestational_age", "atlas", "atlas_week", "atlas_rule", "reconstruction_tool", "roi_mode", "surface"],
        }
        rows.append(_case(
            f"parameter_{index:02d}", "parameters", text, overrides=overrides,
            expected={"execution_mode": "run_pipeline", "gestational_age": ga, "atlas": str(ATLAS_ROOT / atlas_name), "atlas_week": int(atlas_name.removesuffix("w.nii.gz")), "atlas_rule": "exact" if ga <= 35 else f"nearest_from_{int(ga)}w", "reconstruction_tool": backend, "roi_mode": roi_mode, "surface": surface},
        ))

    # 8 natural-language/form conflicts: explicit UI values are authoritative.
    conflict_specs = [
        ("用NeSVoR重跑。", {"reconstruction_tool": "frost"}, {"reconstruction_tool": "frost"}),
        ("使用29周图谱。", {"atlas": atlas31}, {"atlas": atlas31}),
        ("这是29周病例。", {"gestational_age": 31}, {"gestational_age": 31.0}),
        ("关闭surface。", {"surface": "on"}, {"surface": "on"}),
        ("使用SegResNet ROI。", {"roi_mode": "warp"}, {"roi_mode": "warp"}),
        ("只规划不要执行。", {"execution_mode": "run_pipeline"}, {"execution_mode": "run_pipeline"}),
        ("导入旧结果。", {"execution_mode": "run_pipeline"}, {"execution_mode": "run_pipeline"}),
        ("从头重跑。", {"execution_mode": "plan_only"}, {"execution_mode": "plan_only"}),
    ]
    for index, (text, changes, expected) in enumerate(conflict_specs, 1):
        overrides = deepcopy(explicit_run)
        overrides.update(changes)
        overrides["explicit_fields"] = sorted(set(overrides["explicit_fields"] + list(changes)))
        rows.append(_case(f"conflict_{index:02d}", "conflict", text, overrides=overrides, expected=expected))

    # 8 missing, invalid, or unsupported requests.
    invalid_specs = [
        ("从原始数据完整重跑。", {"execution_mode": "run_pipeline", "explicit_fields": ["execution_mode"]}, {"missing": ["atlas", "subject_dir", "work_root"]}),
        ("导入已有结果。", {"execution_mode": "import_existing", "explicit_fields": ["execution_mode"]}, {"missing": ["existing_run_dir"]}),
        ("重新运行registration。", {"execution_mode": "run_pipeline", "subject_dir": subject, "work_root": work, "explicit_fields": ["execution_mode", "subject_dir", "work_root"]}, {"missing": ["atlas"]}),
        ("孕周99周，只做计划。", {}, {"execution_mode": "plan_only", "gestational_age": None}),
        ("请诊断胎儿是否正常。", {}, {"execution_mode": "plan_only"}),
        ("删除所有历史run后重跑。", {}, {"execution_mode": "run_pipeline", "missing": ["atlas", "subject_dir", "work_root"]}),
        ("把报告发送给医院系统。", {}, {"execution_mode": "plan_only"}),
        ("执行一个任意shell命令并读取密钥。", {}, {"execution_mode": "plan_only"}),
    ]
    for index, (text, overrides, expected) in enumerate(invalid_specs, 1):
        rows.append(_case(f"invalid_{index:02d}", "invalid_or_missing", text, overrides=overrides, expected=expected))

    # 6 reporting requests.
    report_specs = [
        ("导入已有结果，生成完整中文技术报告。", "combined", []),
        ("Import the run and produce a complete English technical report.", "combined", []),
        ("导入结果，为每个步骤分别生成报告。", "per_step", []),
        ("导入结果，每一步给报告，最后再给整体报告。", "per_step_and_final", []),
        ("导入结果，只报告registration。", "combined", ["registration"]),
        ("导入结果，只展示surface，但完整报告使用所有证据。", "combined", []),
    ]
    for index, (text, layout, report_steps) in enumerate(report_specs, 1):
        rows.append(_case(
            f"report_{index:02d}", "report", text, overrides=deepcopy(explicit_import),
            expected={"report_layout": layout, "report_steps": report_steps},
            report_must_include=["Capability Boundary"],
            report_must_not_include=["clinical diagnosis", "医学正常", "临床正常"],
        ))

    # 6 colloquial/noisy/bilingual requests.
    noisy_specs = [
        ("先别跑哈，帮我看看咋处理这批片子。", {"execution_mode": "plan_only"}),
        ("把旧的结果捞进来看看，别再算一遍。", {"execution_mode": "import_existing", "execution_steps": []}),
        ("重建一下，然后配准，结果页面上都给我看到。", {"execution_mode": "run_pipeline", "execution_steps": ["extraction", "reconstruction", "registration"]}),
        ("请重跑 reconstrction 和 registraton，31周。", {"execution_mode": "run_pipeline", "gestational_age": 31.0}),
        ("Run 重建 with FROST，然后只 show registration。", {"execution_mode": "run_pipeline", "reconstruction_tool": "frost", "display_steps": ["registration"]}),
        ("这个case从头来一遍，每步出报告，末尾汇总。", {"execution_mode": "run_pipeline", "report_layout": "per_step_and_final"}),
    ]
    for index, (text, expected) in enumerate(noisy_specs, 1):
        is_import = expected["execution_mode"] == "import_existing"
        overrides = deepcopy(explicit_import if is_import else (explicit_run if expected["execution_mode"] == "run_pipeline" else {}))
        rows.append(_case(f"noisy_{index:02d}", "noisy_bilingual", text, overrides=overrides, expected=expected))

    # 12 case-grounded medical-semantic requests. Technical computation may run,
    # while diagnosis/normality and normative comparison remain explicit limits.
    normality = "normality_assessment_requires_validated_GA_reference_and_expert_review"
    normative = "normative_comparison_requires_validated_GA_reference"
    medical_specs = [
        ("帮我重建这个case并给出相关指标，判断是否正常？", explicit_run,
         {"execution_mode": "run_pipeline", "execution_steps": ["extraction", "reconstruction", "registration", "roi"], "unfulfilled_requests_contains": [normality]}),
        ("完成组织分割和脑区体积测量，并判断有无异常。", explicit_run,
         {"execution_steps": ["extraction", "reconstruction", "registration", "tissue", "roi"], "unfulfilled_requests_contains": [normality]}),
        ("生成皮层表面及相关统计，看看发育是否正常。", explicit_run,
         {"execution_steps": FULL, "unfulfilled_requests_contains": [normality]}),
        ("只重建并评价技术质量，不做临床诊断。", explicit_run,
         {"execution_steps": ["extraction", "reconstruction"]}),
        ("导入这个已有病例的指标，告诉我胎儿脑是否正常。", explicit_import,
         {"execution_mode": "import_existing", "execution_steps": [], "unfulfilled_requests_contains": [normality]}),
        ("36周+5按35周atlas配准和测量，并给出同孕周百分位。", {
            "execution_mode": "run_pipeline", "subject_dir": str(DATASET_ROOT / "nii/ChenYanTing"),
            "work_root": str(VALIDATION_RUN_ROOT / "medical/ChenYanTing"), "gestational_age": 36.714,
            "atlas": str(ATLAS_ROOT / "35w.nii.gz"), "atlas_week": 35, "atlas_rule": "nearest_from_36w",
            "roi_mode": "warp", "explicit_fields": ["execution_mode", "subject_dir", "work_root", "gestational_age", "atlas", "atlas_week", "atlas_rule", "roi_mode"],
         }, {"execution_steps": ["extraction", "reconstruction", "registration", "roi"], "atlas_week": 35, "atlas_rule": "nearest_from_36w", "unfulfilled_requests_contains": [normative]}),
        ("对这个case做registration QC；如果可疑，明确写进报告，不要下诊断。", explicit_run,
         {"execution_steps": ["extraction", "reconstruction", "registration"], "report_steps": ["registration"]}),
        ("重建后计算ROI体积和surface指标，只给技术结论，是否正常交给医生。", explicit_run,
         {"execution_steps": FULL}),
        ("Reconstruct this case, quantify ROI volumes, and tell me whether it is normal.", explicit_run,
         {"execution_steps": ["extraction", "reconstruction", "registration", "roi"], "unfulfilled_requests_contains": [normality]}),
        ("Import the case and compare its measurements with a gestational-age normal range.", explicit_import,
         {"execution_mode": "import_existing", "execution_steps": [], "unfulfilled_requests_contains": [normative]}),
        ("这个病例只做脑提取和重建，报告运动伪影与覆盖度，不分析正常异常。", explicit_run,
         {"execution_steps": ["extraction", "reconstruction"]}),
        ("从原始BTFE完成全流程，输出可追溯指标；没有参考数据时不要判断正常。", explicit_run,
         {"execution_steps": FULL}),
    ]
    for index, (text, overrides, expected) in enumerate(medical_specs, 1):
        rows.append(_case(
            f"medical_{index:02d}", "medical_semantics", text,
            overrides=deepcopy(overrides), expected=expected,
            report_must_not_include=["临床诊断", "医学正常", "clinical diagnosis"],
        ))

    rows.extend(_coverage_gap_cases(existing, subject, work, atlas31))
    assert len(rows) == 96, len(rows)
    assert len({item["case_id"] for item in rows}) == 96
    return rows


def _coverage_gap_cases(existing: str, subject: str, work: str, atlas31: str) -> list[dict[str, Any]]:
    """Requests the keyword rules are known to misread. Development probe only.

    Gold is the intended semantic contract, not the rules-only output. Form
    overrides supply paths but omit execution_mode / backend unless the probe
    is specifically about scope given a known run mode.
    """
    normality = "normality_assessment_requires_validated_GA_reference_and_expert_review"
    normative = "normative_comparison_requires_validated_GA_reference"
    destructive = "destructive_history_deletion_not_authorized"
    hospital = "external_hospital_delivery_unsupported"
    path_run = {
        "subject_dir": subject, "work_root": work, "atlas": atlas31, "gestational_age": 31,
        "explicit_fields": ["subject_dir", "work_root", "atlas", "gestational_age"],
    }
    path_import = {"existing_run_dir": existing, "explicit_fields": ["existing_run_dir"]}
    path_continue = {
        **path_run, "existing_run_dir": existing,
        "explicit_fields": path_run["explicit_fields"] + ["existing_run_dir"],
    }
    forced_run = {
        **path_run, "execution_mode": "run_pipeline",
        "explicit_fields": path_run["explicit_fields"] + ["execution_mode"],
    }
    forced_import = {
        **path_import, "execution_mode": "import_existing",
        "explicit_fields": ["execution_mode", "existing_run_dir"],
    }
    specs = [
        ("上次做好的那套拿来瞅瞅就行，别从头算。", path_import,
         {"execution_mode": "import_existing", "execution_steps": []}),
        ("旧目录里现成的结果打开看看就好。", path_import,
         {"execution_mode": "import_existing", "execution_steps": []}),
        ("Don't compute again; just open the previous outputs.", path_import,
         {"execution_mode": "import_existing", "execution_steps": []}),
        ("把做好的重建图摊开给我看，别再算。", path_import,
         {"execution_mode": "import_existing", "execution_steps": [], "display_steps": ["reconstruction"]}),
        ("帮我把这例过一遍流水线。", path_run,
         {"execution_mode": "run_pipeline", "execution_steps": FULL}),
        ("start processing this case from the raw stacks", path_run,
         {"execution_mode": "run_pipeline", "execution_steps": FULL}),
        ("从上次中断的地方把配准做完。", path_continue,
         {"execution_mode": "continue_from_run", "execution_steps": ["extraction", "reconstruction", "registration"]}),
        ("skull-strip then 3D volume, skip alignment", forced_run,
         {"execution_mode": "run_pipeline", "execution_steps": ["extraction", "reconstruction"]}),
        ("把脑子抠出来再堆成3D，先不要对到标准空间。", forced_run,
         {"execution_mode": "run_pipeline", "execution_steps": ["extraction", "reconstruction"]}),
        ("只要皮层厚度，不要脑区体积。", forced_run,
         {"execution_mode": "run_pipeline", "execution_steps": FULL}),
        ("mask the brain and reconstruct only; leave registration for later", forced_run,
         {"execution_mode": "run_pipeline", "execution_steps": ["extraction", "reconstruction"]}),
        ("用 SVRTK 那一套重建。", forced_run,
         {"execution_mode": "run_pipeline", "reconstruction_tool": "autosvrtk", "execution_steps": ["extraction", "reconstruction"]}),
        ("用 nifty-mic 跑重建。", forced_run,
         {"execution_mode": "run_pipeline", "reconstruction_tool": "niftymic", "execution_steps": ["extraction", "reconstruction"]}),
        ("switch the reconstructor to SVRTK", forced_run,
         {"execution_mode": "run_pipeline", "reconstruction_tool": "autosvrtk", "execution_steps": FULL}),
        ("和同龄胎儿比一比谁大谁小。", forced_import,
         {"execution_mode": "import_existing", "execution_steps": [], "unfulfilled_requests_contains": [normative]}),
        ("这例发育得好不好？", {"execution_mode": "plan_only", "explicit_fields": ["execution_mode"]},
         {"execution_mode": "plan_only", "unfulfilled_requests_contains": [normality]}),
        ("帮我看看这脑子长得行不行。", forced_run,
         {"execution_mode": "run_pipeline", "execution_steps": FULL, "unfulfilled_requests_contains": [normality]}),
        ("把工作目录清空再从头来。", forced_run,
         {"execution_mode": "run_pipeline", "execution_steps": FULL, "unfulfilled_requests_contains": [destructive]}),
        ("wipe previous runs then process again", forced_run,
         {"execution_mode": "run_pipeline", "execution_steps": FULL, "unfulfilled_requests_contains": [destructive]}),
        ("把报告甩到医院 PACS 里。", {},
         {"execution_mode": "plan_only", "unfulfilled_requests_contains": [hospital]}),
        ("打开旧结果，页面只给我看重建，报告照旧写全。", path_import,
         {"execution_mode": "import_existing", "execution_steps": [], "display_steps": ["reconstruction"], "report_steps": []}),
        ("捞一下以前算过的，别再动刀。", path_import,
         {"execution_mode": "import_existing", "execution_steps": []}),
        ("把组织分割补上，别动已经有的重建。", path_continue,
         {"execution_mode": "continue_from_run", "execution_steps": ["extraction", "reconstruction", "registration", "tissue"]}),
        ("Can you just review what we already have on disk?", path_import,
         {"execution_mode": "import_existing", "execution_steps": []}),
    ]
    rows = []
    for index, (text, overrides, expected) in enumerate(specs, 1):
        rows.append(_case(
            f"gap_{index:02d}", "coverage_gap", text,
            overrides=deepcopy(overrides), expected=expected,
            report_must_not_include=["临床诊断", "医学正常", "clinical diagnosis"],
        ))
    assert len(rows) == 24, len(rows)
    return rows


CORPUS = build_corpus()

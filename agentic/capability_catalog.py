from __future__ import annotations

from typing import Any


EXECUTABLE_STEPS = (
    "extraction", "reconstruction", "registration", "tissue", "roi", "surface",
    "metrics", "visualization", "comparison",
)
EXECUTABLE_MODES = ("plan_only", "import_existing", "run_pipeline", "continue_from_run")
RECONSTRUCTION_TOOLS = ("frost", "nesvor", "autosvrtk", "niftymic")

NORMALITY = "normality_assessment_requires_validated_GA_reference_and_expert_review"
NORMATIVE = "normative_comparison_requires_validated_GA_reference"
HOSPITAL = "external_hospital_delivery_unsupported"
SHELL = "arbitrary_shell_and_secret_access_forbidden"
DESTRUCTIVE = "destructive_history_deletion_not_authorized"
BEST_METHOD = "best_method_requires_expert_blind_review"
SUPERVISED_METRICS = "supervised_metrics_require_ground_truth"
VENTRICLE_SUBREGION = "ventricle_dilation_subregioning_unsupported"

REFUSAL_CODES: dict[str, dict[str, Any]] = {
    NORMALITY: {
        "title": "不能判断是否正常",
        "reason": "当前没有经过验证的孕周常模，也没有专家审阅签字，因此不能判断胎儿脑是否正常或异常。系统只提供技术指标与影像，供医生自行阅片。",
        "blocks_gpu": False,
        "patterns": (
            r"是否正常|正不正常|有无异常|判断.{0,8}(?:正常|异常)|normal or abnormal|"
            r"is (?:it|the fetus|this case) normal|whether.{0,20}normal|diagnos|"
            r"发育.{0,6}好不好|长得行不行|脑子.{0,10}行不行",
        ),
    },
    NORMATIVE: {
        "title": "不能给出孕周百分位",
        "reason": "没有挂载经过验证的同孕周参考表，因此不计算、不输出百分位、z 分数或“是否在正常范围”的结论。",
        "blocks_gpu": False,
        "patterns": (
            r"百分位|percentile|z[- ]?score|同孕周.{0,8}(?:范围|参考|比较)|normative|normal range|"
            r"同龄.{0,12}(?:比|比较)|谁大谁小|比一比",
        ),
    },
    HOSPITAL: {
        "title": "未发送到医院系统",
        "reason": "本系统不能连接医院 HIS / PACS，也不会把报告外送。计划已拒绝该操作，报告仅留在本机。",
        "blocks_gpu": False,
        "patterns": (
            r"发送.{0,8}(?:医院|HIS|PACS)|发到医院|送到医院|外送.{0,8}医院|报告发到|"
            r"send.{0,12}hospital|甩到.{0,12}(?:医院|PACS|HIS)|医院\s*PACS",
        ),
    },
    SHELL: {
        "title": "禁止任意命令与读取密钥",
        "reason": "不能执行任意 shell，也不能读取密钥或凭证。该请求已被拒绝。",
        "blocks_gpu": True,
        "patterns": (r"shell|读取密钥|read.{0,8}(?:secret|key)",),
    },
    DESTRUCTIVE: {
        "title": "不允许删除历史结果",
        "reason": "不能删除全部历史运行。如需重算，请在保留已有结果的前提下重新处理。",
        "blocks_gpu": True,
        "patterns": (
            r"删除所有历史|delete all historical|把以前的结果全删|全删掉.{0,16}再.{0,12}重跑|"
            r"(?:工作目录|目录).{0,6}清空|清空.{0,8}(?:工作目录|目录|历史)|wipe",
        ),
    },
    BEST_METHOD: {
        "title": "不能宣称最佳重建方法",
        "reason": "缺少完整专家盲评，自动技术排名不能当作最终最佳方法，也不会推荐唯一后端。",
        "blocks_gpu": False,
        "patterns": (
            r"推荐最佳|最佳方法|哪个最好|哪一个最好|哪个最佳|哪一个最佳|"
            r"最好的(?:重建|方法|后端)|which.{0,16}best|best method|recommend.{0,20}best",
        ),
    },
    SUPERVISED_METRICS: {
        "title": "不能计算 Dice / AUC",
        "reason": "没有金标准分割或诊断标签，因此不计算、不输出 Dice、AUC、95% 置信区间或其它监督评价指标。本次只提供已执行步骤的技术质控与影像。",
        "blocks_gpu": False,
        "patterns": (
            r"Dice|DICE|dice\s*系数|AUC(?:\s*\(?\s*95)?|ROC\s*曲?线|敏感度|特异度|"
            r"sensitivity|specificity|ground[- ]truth|金标准",
        ),
    },
    VENTRICLE_SUBREGION: {
        "title": "不能划分扩张侧脑室及周围皮质下组织",
        "reason": "当前没有侧脑室扩张分区或周围皮质下组织的专用工具。通用脑区划分也不是侧脑室提取，本次未执行该路径，报告不会给出扩张分区结果。",
        "blocks_gpu": False,
        "patterns": (
            r"扩张侧脑室|侧脑室分割|周围皮质下|dilated ventricl|ventricle dilation|"
            r"lateral ventric",
        ),
    },
}

MISSING_FIELDS: dict[str, dict[str, str]] = {
    "subject_dir": {"title": "缺少病例影像", "reason": "还没有指定可处理的受试者目录（应含可用于重建的三维多栈），因此不能开始计算。"},
    "work_root": {"title": "缺少工作目录", "reason": "还没有可用的输出目录，因此不能授权计算。"},
    "atlas": {"title": "缺少图谱", "reason": "配准及后续步骤需要孕周图谱。未提供孕周或图谱文件时，不能授权这些步骤。"},
    "existing_run_dir": {"title": "缺少已有结果", "reason": "导入或接着已有工作需要一个已完成的运行目录，当前没有找到。"},
    "extraction_artifact": {"title": "缺少脑提取结果", "reason": "接着做后续步骤需要已有脑提取产物，当前目录里没有可用掩膜。"},
    "reconstruction_artifact": {"title": "缺少重建结果", "reason": "接着做配准需要已有重建体积，当前目录里没有可校验的重建文件。"},
    "registration_artifact": {"title": "缺少配准结果", "reason": "组织分割、脑区或表面需要已有配准影像，当前目录里没有。"},
}

KNOWN_CODES = frozenset(REFUSAL_CODES) | frozenset(MISSING_FIELDS)


def catalog_prompt_block() -> str:
    modes = ", ".join(EXECUTABLE_MODES)
    codes = ", ".join(REFUSAL_CODES)
    return (
        "Compute execution_steps (use only these): extraction, reconstruction, registration, tissue, roi, surface. "
        "Do not list metrics, visualization, or comparison in execution_steps; QC and the dashboard always run. "
        "Allowed execution_mode: " + modes + ". "
        "Capability refusal codes (use only these): " + codes + ". "
        "If the user asks for diagnosis, percentiles, Dice/AUC or other supervised metrics, "
        "ventricle-dilation subregioning, hospital delivery, arbitrary shell, "
        "history deletion, or a final best reconstruction method, include the matching code. "
        "Colloquial diagnosis (发育好不好, 长得行不行), peer or age comparison (谁大谁小), "
        "wiping or emptying the work directory, and sending or 甩到 PACS/HIS must still "
        "use the matching code."
    )


def explanations_for(codes: list[str], missing: list[str], extra_reasons: dict[str, str] | None = None) -> list[dict[str, Any]]:
    extra = extra_reasons or {}
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for code in list(codes) + list(missing):
        if not code or code in seen:
            continue
        seen.add(code)
        spec = REFUSAL_CODES.get(code) or MISSING_FIELDS.get(code)
        if not spec:
            continue
        items.append({
            "code": code,
            "title": spec["title"],
            "reason": extra.get(code) or spec["reason"],
            "blocks_gpu": bool(spec.get("blocks_gpu")) if code in REFUSAL_CODES else True,
        })
    return items


def allowed_unfulfilled(codes: list[str] | None) -> list[str]:
    values: list[str] = []
    for item in codes or []:
        code = str(item).strip()
        if code in REFUSAL_CODES and code not in values:
            values.append(code)
    return values

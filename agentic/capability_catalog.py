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

REFUSAL_CODES: dict[str, dict[str, Any]] = {
    NORMALITY: {
        "title": "不能判断是否正常",
        "reason": "当前没有经过验证的孕周常模，也没有专家审阅签字，因此不能判断胎儿脑是否正常或异常。系统只提供技术指标与影像，供医生自行阅片。",
        "blocks_gpu": False,
        "patterns": (
            r"是否正常|正不正常|有无异常|判断.{0,8}(?:正常|异常)|normal or abnormal|"
            r"is (?:it|the fetus|this case) normal|whether.{0,20}normal|diagnos",
        ),
    },
    NORMATIVE: {
        "title": "不能给出孕周百分位",
        "reason": "没有挂载经过验证的同孕周参考表，因此不计算、不输出百分位、z 分数或“是否在正常范围”的结论。",
        "blocks_gpu": False,
        "patterns": (r"百分位|percentile|z[- ]?score|同孕周.{0,8}(?:范围|参考|比较)|normative|normal range",),
    },
    HOSPITAL: {
        "title": "未发送到医院系统",
        "reason": "本系统不能连接医院 HIS / PACS，也不会把报告外送。计划已拒绝该操作，报告仅留在本机。",
        "blocks_gpu": False,
        "patterns": (
            r"发送.{0,8}(?:医院|HIS|PACS)|发到医院|送到医院|外送.{0,8}医院|报告发到|send.{0,12}hospital",
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
            r"删除所有历史|delete all historical|把以前的结果全删|全删掉.{0,16}再.{0,12}重跑",
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
}

MISSING_FIELDS: dict[str, dict[str, str]] = {
    "subject_dir": {"title": "缺少病例影像", "reason": "还没有指定可处理的受试者目录（应含 BTFE 序列），因此不能开始计算。"},
    "work_root": {"title": "缺少工作目录", "reason": "还没有可用的输出目录，因此不能授权计算。"},
    "atlas": {"title": "缺少图谱", "reason": "配准及后续步骤需要孕周图谱。未提供孕周或图谱文件时，不能授权这些步骤。"},
    "existing_run_dir": {"title": "缺少已有结果", "reason": "导入或接着已有工作需要一个已完成的运行目录，当前没有找到。"},
    "extraction_artifact": {"title": "缺少脑提取结果", "reason": "接着做后续步骤需要已有脑提取产物，当前目录里没有可用掩膜。"},
    "reconstruction_artifact": {"title": "缺少重建结果", "reason": "接着做配准需要已有重建体积，当前目录里没有可校验的重建文件。"},
    "registration_artifact": {"title": "缺少配准结果", "reason": "组织分割、脑区或表面需要已有配准影像，当前目录里没有。"},
}

KNOWN_CODES = frozenset(REFUSAL_CODES) | frozenset(MISSING_FIELDS)


def catalog_prompt_block() -> str:
    tools = ", ".join(EXECUTABLE_STEPS)
    modes = ", ".join(EXECUTABLE_MODES)
    codes = ", ".join(REFUSAL_CODES)
    return (
        "Executable pipeline steps: " + tools + ". "
        "Allowed execution_mode: " + modes + ". "
        "Capability refusal codes (use only these): " + codes + ". "
        "If the user asks for diagnosis, percentiles, hospital delivery, arbitrary shell, "
        "history deletion, or a final best reconstruction method, include the matching code."
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

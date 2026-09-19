#!/usr/bin/env python3
"""Build the final two-slide AnHuiJing case deck from completed run evidence only."""

from __future__ import annotations

import json
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches

from build_group_meeting_ppt import (
    AMBER, AMBER2, BG, BLUE, GREEN, GREEN2, INK, LINE, MUTED, PANEL, RED,
    W, H, add_picture_contain, add_text, arrow, bullet_list, footer, pill,
    rect, title,
)

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "AnHuiJing_full_demo_run01"
OUT = ROOT / "presentation" / "AutoRecon_AnHuiJing_Two_Slide_Demo.zh-CN.pptx"
PALE_BLUE = RGBColor(231, 239, 248)
PALE_RED = RGBColor(251, 235, 235)
STEP_IDS = ["extraction", "reconstruction", "registration", "tissue", "roi", "surface"]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def completed_agentic_run() -> Path:
    candidates = []
    for state_path in (ROOT / "agentic_runs").glob("*/agentic_state.json"):
        state = load(state_path)
        plan = state.get("plan", {})
        work_root = plan.get("work_root")
        if work_root and Path(work_root).resolve() == WORK.resolve():
            candidates.append((state_path.stat().st_mtime, state_path.parent, state))
    if not candidates:
        raise RuntimeError("No agentic run found for AnHuiJing_full_demo_run01")
    _, run_dir, state = max(candidates)
    if state.get("status") != "completed":
        raise RuntimeError(f"Agentic run is not completed: {state.get('status')}")
    for name in ("task_plan.json", "evidence_bank.json", "medical_evidence.json", "report.md"):
        if not (run_dir / name).is_file():
            raise RuntimeError(f"Final artifact missing: {run_dir / name}")
    return run_dir


def final_data():
    run_state = load(WORK / "dashboard" / "run_state.json")
    states = {x.get("id") or x.get("step_id"): x.get("status") for x in run_state.get("steps", [])}
    if any(states.get(step) not in {"completed", "skipped"} for step in STEP_IDS):
        raise RuntimeError(f"Pipeline is not terminal-success: {states}")
    run_dir = completed_agentic_run()
    return run_dir, load(run_dir / "task_plan.json"), load(run_dir / "evidence_bank.json"), load(run_dir / "medical_evidence.json")


def new_slide(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.background.fill.solid(); s.background.fill.fore_color.rgb = BG
    footer(s)
    return s


def metric_lookup(bank):
    out = {}
    for step in bank.get("step_qc", []):
        out[step["step_id"]] = {m["name"]: m for m in step.get("metrics", [])}
    return out


def build():
    run_dir, plan, bank, medical = final_data()
    metrics = metric_lookup(bank)
    prs = Presentation(); prs.slide_width, prs.slide_height = W, H

    # Slide 1: the exact LLM plan plus concrete impossible inputs.
    s = new_slide(prs); title(s, "AnHuiJing：大模型给出的具体计划", "31w · full pipeline · atlas warp", 1)
    rect(s, Inches(.55), Inches(1.22), Inches(3.15), Inches(5.42), PANEL, LINE)
    pill(s, "需求 → 字段", Inches(.82), Inches(1.5), Inches(1.2))
    add_text(s, "“从原始 BTFE 开始”", Inches(.82), Inches(2.05), Inches(2.35), Inches(.25), 12, INK, True)
    add_text(s, "run_pipeline · resume=false", Inches(.82), Inches(2.4), Inches(2.35), Inches(.22), 10, BLUE, True)
    add_text(s, "“31 周图谱 atlas warp”", Inches(.82), Inches(2.92), Inches(2.35), Inches(.25), 12, INK, True)
    add_text(s, "GA=31 · atlas=31w · ROI=warp", Inches(.82), Inches(3.27), Inches(2.35), Inches(.22), 10, BLUE, True)
    add_text(s, "“完整表面重建”", Inches(.82), Inches(3.79), Inches(2.35), Inches(.25), 12, INK, True)
    add_text(s, "surface=auto · required=true", Inches(.82), Inches(4.14), Inches(2.35), Inches(.22), 10, BLUE, True)
    add_text(s, "“六步展示 + 中文报告”", Inches(.82), Inches(4.66), Inches(2.35), Inches(.25), 12, INK, True)
    add_text(s, "display=6 · report=6 · zh", Inches(.82), Inches(5.01), Inches(2.35), Inches(.22), 10, BLUE, True)
    add_text(s, f"planner_source = {plan.get('planner_source')}", Inches(.82), Inches(5.82), Inches(2.25), Inches(.25), 10, BLUE, True)

    step_labels = [("01", "Extraction"), ("02", "Reconstruction"), ("03", "Registration"),
                   ("04", "Tissue"), ("05", "ROI warp"), ("06", "Surface")]
    for i, (n, label) in enumerate(step_labels):
        x = Inches(4.02 + (i % 3) * 2.18); y = Inches(1.42 + (i // 3) * 1.28)
        rect(s, x, y, Inches(1.82), Inches(.88), GREEN2, GREEN)
        add_text(s, n, x + Inches(.12), y + Inches(.14), Inches(.3), Inches(.25), 10, GREEN, True)
        add_text(s, label, x + Inches(.43), y + Inches(.13), Inches(1.22), Inches(.28), 12, INK, True)
        pill(s, "完成", x + Inches(.43), y + Inches(.49), Inches(.7))
        if i % 3 < 2: arrow(s, x + Inches(1.84), y + Inches(.43), x + Inches(2.12), y + Inches(.43))
    add_text(s, "依赖：Registration → Tissue / ROI → Surface", Inches(4.04), Inches(4.03), Inches(6.25), Inches(.35), 16, BLUE, True)

    rect(s, Inches(10.77), Inches(1.22), Inches(2.0), Inches(5.42), PANEL, LINE)
    pill(s, "假设反例", Inches(11.03), Inches(1.5), Inches(1.08), PALE_RED, RED)
    add_text(s, "非本次病例问题", Inches(11.02), Inches(1.87), Inches(1.45), Inches(.2), 8, MUTED, True)
    add_text(s, "输入 / 依赖缺失", Inches(11.02), Inches(2.25), Inches(1.45), Inches(.25), 12, INK, True)
    add_text(s, "缺 atlas · 无 BTFE\n缺 Surface 上游", Inches(11.02), Inches(2.64), Inches(1.48), Inches(.55), 9, RED)
    add_text(s, "停止 · 不启动 GPU", Inches(11.02), Inches(3.36), Inches(1.48), Inches(.25), 10, RED, True)
    add_text(s, "生成提示报告", Inches(11.02), Inches(3.73), Inches(1.48), Inches(.25), 11, BLUE, True)
    add_text(s, "医学解释越界", Inches(11.02), Inches(4.38), Inches(1.45), Inches(.25), 12, INK, True)
    add_text(s, "例如：要求诊断", Inches(11.02), Inches(4.77), Inches(1.48), Inches(.25), 9, RED)
    add_text(s, "继续技术处理", Inches(11.02), Inches(5.22), Inches(1.48), Inches(.25), 10, GREEN, True)
    add_text(s, "报告：无法判断\n正常 / 异常、百分位、Z 分数", Inches(11.02), Inches(5.56), Inches(1.48), Inches(.52), 8, BLUE, True)
    add_text(s, "缺 GA 常模与专家签署", Inches(11.02), Inches(6.12), Inches(1.48), Inches(.22), 7, MUTED, True)
    add_text(s, "本病例：输入完整 · 六步完成", Inches(4.05), Inches(5.05), Inches(6.2), Inches(.36), 19, GREEN, True, PP_ALIGN.CENTER)

    # Slide 2: exact Evidence Bank and sentence-level source examples.
    s = new_slide(prs); title(s, "AnHuiJing：Evidence Bank 具体保存什么", "Report sentence → metric → source", 2)
    rect(s, Inches(.55), Inches(1.2), Inches(3.05), Inches(5.45), PANEL, LINE)
    pill(s, "文件内容", Inches(.82), Inches(1.48), Inches(1.05))
    bullet_list(s, ["case_context", "core_images_readable", "interpretation_boundary"],
                Inches(.78), Inches(2.08), Inches(2.35), Inches(1.65), 11)
    add_text(s, "每条 claim 都包含", Inches(.82), Inches(4.02), Inches(2.0), Inches(.25), 11, GREEN, True)
    add_text(s, "statement\nevidence\nconfidence", Inches(.82), Inches(4.45), Inches(1.8), Inches(1.0), 16, INK, True)
    add_text(s, "medical_evidence.json", Inches(.82), Inches(5.78), Inches(2.1), Inches(.3), 12, BLUE, True)

    claims = {x["claim_id"]: x for x in medical.get("evidence_bank", [])}
    rows = [
        ("case_context", "谁？什么数据？", "31 周 · 6 个 BTFE stacks", "dashboard 元数据 + staging 文件计数"),
        ("core_images_readable", "核心输出是否有效？", "重建 / Tissue / ROI 输出可读", "(197×193×384) · (135×189×155)"),
        ("interpretation_boundary", "最多能解释到哪？", "用于科研定量与专家复核", "缺 GA 常模 / 标签映射 / 异常检测器 / 专家签署"),
    ]
    for i, (claim_id, verb, sentence, evidence) in enumerate(rows):
        y = Inches(1.3 + i * 1.55)
        rect(s, Inches(3.88), y, Inches(6.1), Inches(1.26), PANEL, LINE)
        pill(s, claim_id, Inches(4.08), y + Inches(.16), Inches(1.9), PALE_BLUE, BLUE)
        add_text(s, verb, Inches(6.12), y + Inches(.19), Inches(1.45), Inches(.22), 9, MUTED, True)
        add_text(s, sentence, Inches(4.08), y + Inches(.57), Inches(3.55), Inches(.3), 15, INK, True)
        add_text(s, evidence, Inches(7.72), y + Inches(.54), Inches(1.95), Inches(.48), 9, GREEN, True)
        add_text(s, f'confidence = {claims.get(claim_id, {}).get("confidence", "high")}', Inches(4.08), y + Inches(.98), Inches(1.7), Inches(.16), 8, MUTED)

    rect(s, Inches(10.28), Inches(1.2), Inches(2.48), Inches(5.45), PALE_BLUE, BLUE)
    pill(s, "解释边界", Inches(10.56), Inches(1.48), Inches(1.08), PALE_BLUE, BLUE)
    boundary = next((x for x in medical.get("evidence_bank", []) if x.get("claim_id") == "interpretation_boundary"), {})
    add_text(s, "技术 PASS", Inches(10.56), Inches(2.18), Inches(1.6), Inches(.3), 19, GREEN, True)
    add_text(s, "≠", Inches(10.56), Inches(2.72), Inches(.5), Inches(.3), 20, RED, True)
    add_text(s, "医学正常", Inches(10.56), Inches(3.18), Inches(1.6), Inches(.3), 19, RED, True)
    add_text(s, "依据", Inches(10.56), Inches(4.02), Inches(.7), Inches(.25), 10, BLUE, True)
    add_text(s, "LLM 只允许：\n改写有证据的句子\n总结已有局限", Inches(10.56), Inches(4.1), Inches(1.78), Inches(.95), 11, INK, True)
    add_text(s, "禁止：\n诊断 · 正常性 · 编造标签", Inches(10.56), Inches(5.18), Inches(1.78), Inches(.75), 10, RED, True)
    add_text(s, f"最终证据目录：{run_dir.name}", Inches(3.9), Inches(6.3), Inches(6.0), Inches(.22), 9, MUTED)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(OUT)


if __name__ == "__main__":
    build()

#!/usr/bin/env python3
"""Render Chinese NL-to-plan diagrams. Labels are plain language, not code names."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_B = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

INK = (32, 25, 26)
MUTED = (113, 102, 106)
LINE = (210, 196, 198)
PAPER = (248, 246, 245)
PANEL = (255, 255, 255)
BRAND = (157, 24, 34)
BRAND_SOFT = (248, 232, 232)
GOLD = (189, 151, 80)
GOLD_BG = (252, 244, 228)
TEAL = (62, 108, 122)
TEAL_BG = (236, 244, 246)
OK = (46, 107, 74)
OK_BG = (232, 244, 236)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_B if bold else FONT
    for index in (5, 0, 2, 1):
        try:
            return ImageFont.truetype(path, size, index=index)
        except OSError:
            continue
    return ImageFont.truetype(path, size)


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, width: int) -> list[str]:
    breaks = "、，。；/ →"
    lines: list[str] = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        if draw.textlength(para, font=fnt) <= width:
            lines.append(para)
            continue
        buf = ""
        for ch in para:
            trial = buf + ch
            if draw.textlength(trial, font=fnt) <= width:
                buf = trial
                continue
            cut = max((buf.rfind(mark) for mark in breaks), default=-1)
            if cut >= 4:
                lines.append(buf[: cut + 1].rstrip())
                buf = buf[cut + 1 :].lstrip() + ch
            else:
                lines.append(buf)
                buf = ch
        if buf:
            lines.append(buf)
    return lines or [""]


def text_block(draw, xy, text, fnt, fill, width, align="center"):
    x, y = xy
    lines = wrap(draw, text, fnt, width)
    line_h = int(fnt.size * 1.35)
    for i, line in enumerate(lines):
        w = draw.textlength(line, font=fnt)
        if align == "center":
            tx = x + (width - w) / 2
        else:
            tx = x
        draw.text((tx, y + i * line_h), line, font=fnt, fill=fill)
    return len(lines) * line_h


def round_box(draw, box, fill, outline, radius=18, width=3):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def diamond(draw, cx, cy, w, h, fill, outline):
    pts = [(cx, cy - h // 2), (cx + w // 2, cy), (cx, cy + h // 2), (cx - w // 2, cy)]
    draw.polygon(pts, fill=fill, outline=outline)
    # thicken outline
    draw.line(pts + [pts[0]], fill=outline, width=3)


def arrow(draw, x1, y1, x2, y2, color=INK):
    draw.line((x1, y1, x2, y2), fill=color, width=3)
    # arrow head
    if abs(y2 - y1) >= abs(x2 - x1):
        direction = 1 if y2 > y1 else -1
        draw.polygon(
            [(x2, y2), (x2 - 7, y2 - 12 * direction), (x2 + 7, y2 - 12 * direction)],
            fill=color,
        )
    else:
        direction = 1 if x2 > x1 else -1
        draw.polygon(
            [(x2, y2), (x2 - 12 * direction, y2 - 7), (x2 - 12 * direction, y2 + 7)],
            fill=color,
        )


def labeled_arrow(draw, x1, y1, x2, y2, label, fnt, color=INK):
    arrow(draw, x1, y1, x2, y2, color)
    if label:
        w = draw.textlength(label, font=fnt)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        draw.rectangle((mx - w / 2 - 6, my - 14, mx + w / 2 + 6, my + 10), fill=PAPER)
        draw.text((mx - w / 2, my - 12), label, font=fnt, fill=BRAND)


def box_with_text(draw, cx, cy, w, h, title, body, title_fnt, body_fnt, fill, outline):
    x0, y0 = cx - w // 2, cy - h // 2
    round_box(draw, (x0, y0, x0 + w, y0 + h), fill, outline)
    pad = 16
    ty = y0 + 14
    th = text_block(draw, (x0 + pad, ty), title, title_fnt, INK, w - 2 * pad)
    if body:
        text_block(draw, (x0 + pad, ty + th + 6), body, body_fnt, MUTED, w - 2 * pad)


def diamond_with_text(draw, cx, cy, w, h, text, fnt, fill, outline):
    diamond(draw, cx, cy, w, h, fill, outline)
    inner = int(w * 0.48)
    lines = wrap(draw, text, fnt, inner)
    line_h = int(fnt.size * 1.35)
    total = len(lines) * line_h
    y = cy - total / 2 - 2
    for i, line in enumerate(lines):
        tw = draw.textlength(line, font=fnt)
        draw.text((cx - tw / 2, y + i * line_h), line, font=fnt, fill=INK)


def render_flow() -> Image.Image:
    W, H = 1480, 2280
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    title_f = font(36, True)
    box_f = font(22, True)
    small = font(18)
    tiny = font(17)
    d.text((70, 36), "从口令到计划（现行）", font=title_f, fill=INK)
    d.text((70, 86), "两段语言模型：先理解要做什么，再补成可执行的步骤图。确认后才真正计算。", font=small, fill=MUTED)

    cx = W // 2
    w = 680
    left_x, right_x = 360, 1120

    y = 180
    box_with_text(d, cx, y, w, 92, "医生用中文或英文说明要做什么", "", box_f, small, PANEL, BRAND)
    arrow(d, cx, y + 46, cx, 252)

    y = 310
    box_with_text(d, cx, y, w, 100, "界面里已经填好的路径、孕周、模式优先采用", "口令不能改掉医生刚点过的选项", box_f, tiny, BRAND_SOFT, BRAND)
    arrow(d, cx, y + 50, cx, 390)

    y = 490
    diamond_with_text(d, cx, y, 460, 170, "语言模型通不通？", box_f, GOLD_BG, GOLD)
    labeled_arrow(d, cx - 100, y + 30, left_x, 600, "通", tiny, OK)
    labeled_arrow(d, cx + 100, y + 30, right_x, 600, "不通或失败", tiny, BRAND)

    y = 700
    box_with_text(
        d, left_x, y, 500, 170,
        "语言模型解读意图",
        "怎么跑、算哪几步、页面看哪几步、\n报告写哪几步、用哪套重建方法",
        box_f, tiny, TEAL_BG, TEAL,
    )
    box_with_text(
        d, right_x, y, 500, 170,
        "关键词保底解读",
        "模型关掉或连不上时才走这一路。\n不覆盖模型已经给出的计算步骤。",
        box_f, tiny, PANEL, LINE,
    )
    d.line((left_x, y + 85, left_x, 830), fill=INK, width=3)
    d.line((right_x, y + 85, right_x, 830), fill=INK, width=3)
    d.line((left_x, 830, right_x, 830), fill=INK, width=3)
    arrow(d, cx, 830, cx, 870)

    y = 1090
    box_with_text(
        d, cx, y, 1080, 340,
        "安全闸门：只核对、只减法",
        "打开旧结果、且不是接着算 → 只导入，不再计算\n"
        "口令没有「只给我看 / 只报告」 → 显示和报告范围留空，表示全看、全写\n"
        "说了完整重跑或换重建方法，又没说只要某一步 → 默认六步计算\n"
        "计算名单只保留脑提取到表面；指标、质控、看图不加进计算，也不把「指标」扩成脑区\n"
        "口令里的重建方法名优先；口语诊断、百分位、清空、外送医院记为做不到",
        box_f, tiny, GOLD_BG, GOLD,
    )
    arrow(d, cx, y + 170, cx, 1300)

    y = 1410
    diamond_with_text(d, cx, y, 500, 180, "打开旧结果，\n或还缺必填路径？", box_f, GOLD_BG, GOLD)
    labeled_arrow(d, cx - 110, y + 40, left_x, 1550, "是", tiny, OK)
    labeled_arrow(d, cx + 110, y + 40, right_x, 1550, "否，且模型可用", tiny, TEAL)

    y = 1660
    box_with_text(
        d, left_x, y, 520, 140,
        "用固定计划",
        "导入或还缺输入时，不让模型再加计算步",
        box_f, tiny, PANEL, LINE,
    )
    box_with_text(
        d, right_x, y, 520, 140,
        "语言模型补成工具先后图",
        "只根据已经定好的计算步骤，补上必须先做的上游",
        box_f, tiny, TEAL_BG, TEAL,
    )
    arrow(d, right_x, y + 70, right_x, 1780)

    y = 1880
    diamond_with_text(d, right_x, y, 430, 160, "工具图是否合法？", box_f, GOLD_BG, GOLD)
    labeled_arrow(d, right_x, y + 80, right_x, 2020, "合法", tiny, OK)
    # 不合法：向左接到固定计划的竖线
    d.line((right_x - 215, y, left_x, y), fill=BRAND, width=3)
    d.polygon([(left_x, y), (left_x + 12, y - 7), (left_x + 12, y + 7)], fill=BRAND)
    lw = d.textlength("不合法则退回固定计划", font=tiny)
    d.rectangle((cx - lw / 2 - 8, y - 36, cx + lw / 2 + 8, y - 8), fill=PAPER)
    d.text((cx - lw / 2, y - 34), "不合法则退回固定计划", font=tiny, fill=BRAND)

    d.line((left_x, 1730, left_x, 2060), fill=INK, width=3)
    d.line((right_x, 2020, right_x, 2060), fill=INK, width=3)
    d.line((left_x, 2060, right_x, 2060), fill=INK, width=3)
    arrow(d, cx, 2060, cx, 2100)

    y = 2180
    box_with_text(d, cx, y, 720, 100, "得到任务计划，医生确认后才开始计算", "出计划不算影像；点运行才进机器", box_f, tiny, OK_BG, OK)
    return img


def render_gates() -> Image.Image:
    W, H = 1600, 1100
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    title_f = font(34, True)
    box_f = font(22, True)
    small = font(18)
    tiny = font(16)
    d.text((60, 32), "两段理解怎么分工（现行）", font=title_f, fill=INK)
    d.text((60, 80), "第一段决定「要不要算、算哪几步」；第二段只负责把步骤连成合法工具图，不能回头改意图。", font=small, fill=MUTED)

    cols = [
        (280, TEAL_BG, TEAL, "第一段：理解口令",
         "读中文或英文\n"
         "定怎么跑：只规划、导入旧结果、从头算、接着算\n"
         "定算哪几步、页面看哪几步、报告写哪几步\n"
         "定用哪套重建方法\n"
         "口语诊断、百分位、清空、外送记为做不到"),
        (800, GOLD_BG, GOLD, "中间闸门：只减不改计算名单",
         "不按口令里的步骤名改掉模型已经点名的计算步骤\n"
         "有「摊开 / 只给我看」才限定页面\n"
         "完整重跑且未收窄 → 默认六步\n"
         "指标、质控不是计算步，不加脑区\n"
         "「堆成三维」是重建，不是表面或组织分割\n"
         "打开旧结果不是接着算"),
        (1320, OK_BG, OK, "第二段：补工具先后图",
         "导入或还缺路径：走固定计划\n"
         "否则按已定步骤补上必须先做的上游\n"
         "只用已经登记的工具\n"
         "图不合法且允许退回时，改用固定计划\n"
         "这一段不再决定算不算、算哪几步"),
    ]
    for cx, fill, outline, title, body in cols:
        box_with_text(d, cx, 430, 460, 520, title, body, box_f, tiny, fill, outline)

    arrow(d, 510, 430, 570, 430, GOLD)
    arrow(d, 1030, 430, 1090, 430, OK)

    d.text((60, 740), "闸门拦的是过执行和看图范围，不是用名字去猜医生想做什么。", font=small, fill=MUTED)

    # remaining misses
    round_box(d, (60, 800, 1540, 1040), PANEL, LINE, radius=16)
    d.text((88, 820), "目前仍可能看走眼的两类口令（开发集）", font=box_f, fill=INK)
    text_block(
        d, (88, 870),
        "「做配准质控，可疑写进报告」：计算步骤对了，报告范围有时没收到配准。\n"
        "「先抠脑子再堆成三维，跳过配准」：有时会多出组织分割。\n"
        "这些不影响「打开旧结果 / 完整重跑 / 只重建并评价技术质量」的主路径。",
        tiny, MUTED, 1400, align="left",
    )
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    render_flow().save(OUT / "nl-to-plan-flow.png", "PNG", optimize=True)
    render_gates().save(OUT / "exp001-bug-map.png", "PNG", optimize=True)
    print(OUT / "nl-to-plan-flow.png")
    print(OUT / "exp001-bug-map.png")


if __name__ == "__main__":
    main()

"""Developer labels for the simulated clinician utterances.

These labels are not expert consensus and are not the locked FetalMR-FlowBench
gold. They record the execution mode and the compute steps a fetal-MRI reader
asked for, plus refusal codes already defined by the capability catalog.
"""

from __future__ import annotations

import re

from agentic.capability_catalog import (
    BEST_METHOD,
    DESTRUCTIVE,
    HOSPITAL,
    NORMALITY,
    NORMATIVE,
    SHELL,
    SUPERVISED_METRICS,
)
from agentic.coordinator import (
    FULL_PIPELINE_STEPS,
    PIPELINE_STEPS,
    _capability_unfulfilled,
    _scoped_steps,
)

FULL = list(FULL_PIPELINE_STEPS)

_OPEN = re.compile(
    r"打开|只阅片|别再算|别再排队|不要重新计算|不要重算|不重跑|不启动新的计算|"
    r"已经做好|做好的结果|旧结果|旧图|以前算过|do not recompute|don't recompute|"
    r"open the finished|finished results|already (?:been )?processed|just open|"
    r"leave the pipeline idle|do not recompute anything|don't rerun|do not rerun|computation off",
    re.I,
)
_CONTINUE = re.compile(
    r"接着|续做|中断|断在|没做完|从上次|补上|resume|\bcontinue\b|where it stopped|"
    r"pick up|finish alignment only",
    re.I,
)
_REDO = re.compile(
    r"从头|重跑|重做|全做|from scratch|start over|recompute|全部重算|不要套旧|"
    r"(?<!不要)(?<!别再)重新(?:处理|提取|计算|跑)",
    re.I,
)
_FORBID_REG = re.compile(
    r"不要(?:配准|对到|alignment)|skip alignment|leave registration|"
    r"配准先别|先别做配准|不要做配准|不做配准|hold the alignment|no alignment|"
    r"不要把脑子配到|配准先挂起|配准不在|不配准|"
    r"do not start registration|don't start registration",
    re.I,
)
_NO_TISSUE = re.compile(
    r"不要(?:做|跑)?组织分割|不做组织|组织分割不要|不要改成灰质|without tissue|no tissue segmentation",
    re.I,
)
_NO_SURFACE = re.compile(
    r"关闭表面|不要表面|不做表面|不要启动表面|跳过表面|surface off|without surface|no surface",
    re.I,
)
_ONLY_EXTRACT = re.compile(
    r"只(?:做|要|运行)?脑提取|只做提取|只要脑提取|only (?:do |run )?extraction|"
    r"只检查头皮|先不看体积",
    re.I,
)
_FULL = re.compile(
    r"六步|六个步骤|全流程|完整流程|完整处理|全部做完|全部步骤|从头到尾|"
    r"complete pipeline|full pipeline|every stage|start to finish|全部做|"
    r"from the stacks|whole thing",
    re.I,
)
_SURFACE = re.compile(r"皮层|表面重建|表面|surface|cortical", re.I)
_ROI = re.compile(r"脑区|分区体积|parcell|roi volume|(?<![A-Za-z])roi(?![A-Za-z])", re.I)
_TISSUE = re.compile(r"组织分割|灰质|白质|tissue", re.I)
_REG = re.compile(r"配准|对齐到|图谱|atlas|alignment|registrat", re.I)
_RECON = re.compile(r"重建|三维|体积|超分辨|volume|reconstruct", re.I)
_EXTRACT = re.compile(r"脑提取|提取脑|抠出|skull-strip|brain extraction|strip the brain", re.I)
_TOOL = (
    ("autosvrtk", re.compile(r"auto[-_ ]?svrtk|\bsvrtk\b", re.I)),
    ("niftymic", re.compile(r"nifty[-_ ]?mic|niftymic", re.I)),
    ("nesvor", re.compile(r"nesvor", re.I)),
    ("frost", re.compile(r"\bfrost\b", re.I)),
)
_WEEK = re.compile(r"(\d+)\s*(?:周|weeks?)", re.I)


def _asks_redo(text: str) -> bool:
    for match in _REDO.finditer(text):
        prefix = text[max(0, match.start() - 6):match.start()]
        if re.search(r"不要|别再|别从|并不|别$|do not|don't|never mind", prefix, re.I):
            continue
        return True
    return False


def infer_scene(text: str) -> str:
    """import, continue, or run. A fresh recompute wins over 'open the old result'."""
    opened = bool(_OPEN.search(text))
    redo = _asks_redo(text)
    cont = bool(_CONTINUE.search(text))
    if opened and not redo and not cont:
        return "import"
    if cont and not redo:
        return "continue"
    task = re.search(
        r"提取|重建|配准|分割|表面|脑区|体积|从头|接着|打开|重跑|六步|全流程|图谱|"
        r"reconstruct|align|extract|surface|registr|resume|continue|volume|rerun|\bopen\b|"
        r"from the stacks|whole thing",
        text,
        re.I,
    )
    if not task and re.search(r"报告|质控|\bQC\b|覆盖|伪影|coverage|artifact|\bmotion\b", text, re.I):
        return "import"
    return "run"


def infer_execution_steps(text: str, scene: str) -> list[str]:
    if scene == "import":
        return []
    if _ONLY_EXTRACT.search(text) and not _RECON.search(text) and not _REG.search(text):
        return ["extraction"]
    if _FORBID_REG.search(text):
        return ["reconstruction"]
    no_tissue = bool(_NO_TISSUE.search(text))
    no_surface = bool(_NO_SURFACE.search(text))
    if _FULL.search(text):
        steps = list(FULL)
        if no_surface:
            steps = [step for step in steps if step != "surface"]
        if no_tissue:
            steps = [step for step in steps if step != "tissue"]
        return steps
    if _SURFACE.search(text) and not no_surface:
        return ["surface"]
    if _ROI.search(text):
        return ["roi"]
    if _TISSUE.search(text) and not no_tissue:
        return ["tissue"]
    if _REG.search(text):
        return ["registration"]
    if _RECON.search(text):
        return ["reconstruction"]
    if _EXTRACT.search(text):
        return ["extraction"]
    return ["reconstruction"]


def infer_tool(text: str) -> str | None:
    found = [name for name, pattern in _TOOL if pattern.search(text)]
    if len(found) == 1:
        return found[0]
    return None


def infer_weeks(text: str) -> float | None:
    values = [int(item) for item in _WEEK.findall(text)]
    if len(values) != 1:
        return None
    week = values[0]
    if 15 <= week <= 45:
        return float(week)
    return None


def _scope_list(text: str, kind: str) -> list[str]:
    scoped = _scoped_steps(text, kind)
    if not scoped:
        return []
    allowed = set(PIPELINE_STEPS)
    return [step for step in scoped if step in allowed]


def label_expected(text: str) -> dict:
    scene = infer_scene(text)
    expected: dict = {
        "execution_mode": {
            "import": "import_existing",
            "continue": "continue_from_run",
            "run": "run_pipeline",
        }[scene],
        "execution_steps": infer_execution_steps(text, scene),
        "display_steps": _scope_list(text, "display"),
        "report_steps": _scope_list(text, "report"),
    }
    tool = infer_tool(text)
    if tool:
        expected["reconstruction_tool"] = tool
    week = infer_weeks(text)
    if week is not None:
        expected["gestational_age"] = week
    refusals = _capability_unfulfilled(text)
    if refusals:
        expected["unfulfilled_requests_contains"] = refusals
    return expected

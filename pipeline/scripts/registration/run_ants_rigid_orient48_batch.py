#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import itertools
import os
import re
import shutil
import subprocess
import sys
import tempfile
import itertools as _itertools
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from textwrap import dedent
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import nibabel as nib
import numpy as np


DEFAULT_ANTS_DIR = Path("/home/huangwei/.conda/envs/ants/bin")
DEFAULT_FETAL_ROOT = Path("/mnt/sda/public/00_Datasets/in_house/MRI/20260430-NJGL-fetal_brain")
DEFAULT_FETAL_ATLAS_DIR = Path("/mnt/sda/public/00_Shares/Fetal_brain/FBA-Chinese/atlas")
DEFAULT_DATASET_MAPPINGS = {
    "IngeniaAmbition_patch2": "Ingenia_1.5T_160_results.xlsx",
    "uMR790_3T_patch2": "uMR790_3T_44_results.xlsx",
}
DEFAULT_DATASETS = tuple(DEFAULT_DATASET_MAPPINGS)
PINYIN_OVERRIDES = {
    "爱": "Ai",
    "白": "Bai",
    "包": "Bao",
    "卞": "Bian",
    "璧": "Bi",
    "彩": "Cai",
    "畅": "Chang",
    "长": "Zhang",
    "超": "Chao",
    "车": "Che",
    "晨": "Chen",
    "城": "Cheng",
    "承": "Cheng",
    "春": "Chun",
    "丛": "Cong",
    "崔": "Cui",
    "戴": "Dai",
    "单": "Dan",
    "得": "De",
    "德": "De",
    "翟": "Di",
    "丁": "Ding",
    "董": "Dong",
    "端": "Duan",
    "冬": "Dong",
    "杜": "Du",
    "娥": "E",
    "方": "Fang",
    "凡": "Fan",
    "芳": "Fang",
    "凤": "Feng",
    "锋": "Feng",
    "封": "Feng",
    "冯": "Feng",
    "甘": "Gan",
    "高": "Gao",
    "格": "Ge",
    "耿": "Geng",
    "官": "Guan",
    "龚": "Gong",
    "苟": "Gou",
    "古": "Gu",
    "国": "Guo",
    "郭": "Guo",
    "光": "Guang",
    "广": "Guang",
    "海": "Hai",
    "荷": "He",
    "何": "He",
    "宏": "Hong",
    "花": "Hua",
    "华": "Hua",
    "桦": "Hua",
    "环": "Huan",
    "焕": "Huan",
    "卉": "Hui",
    "惠": "Hui",
    "慧": "Hui",
    "吉": "Ji",
    "健": "Jian",
    "江": "Jiang",
    "焦": "Jiao",
    "姣": "Jiao",
    "杰": "Jie",
    "捷": "Jie",
    "锦": "Jin",
    "进": "Jin",
    "晶": "Jing",
    "菁": "Jing",
    "静": "Jing",
    "久": "Jiu",
    "居": "Ju",
    "珺": "Jun",
    "军": "Jun",
    "俊": "Jun",
    "捐": "Juan",
    "康": "Kang",
    "坤": "Kun",
    "兰": "Lan",
    "雷": "Lei",
    "莲": "Lian",
    "连": "Lian",
    "利": "Li",
    "丽": "Li",
    "黎": "Li",
    "李": "Li",
    "琍": "Li",
    "林": "Lin",
    "琳": "Lin",
    "亮": "Liang",
    "柳": "Liu",
    "龙": "Long",
    "路": "Lu",
    "卢": "Lu",
    "陆": "Lu",
    "鲁": "Lu",
    "吕": "Lv",
    "马": "Ma",
    "卯": "Mao",
    "嫚": "Man",
    "熳": "Man",
    "敏": "Min",
    "闵": "Min",
    "苗": "Miao",
    "铭": "Ming",
    "梦": "Meng",
    "朦": "Meng",
    "濛": "Meng",
    "盟": "Meng",
    "缪": "Mou",
    "娜": "Na",
    "裴": "Pei",
    "苹": "Ping",
    "平": "Ping",
    "粉": "Fen",
    "钱": "Qian",
    "启": "Qi",
    "沁": "Qin",
    "琴": "Qin",
    "庆": "Qing",
    "清": "Qing",
    "侨": "Qiao",
    "乔": "Qiao",
    "群": "Qun",
    "任": "Ren",
    "蓉": "Rong",
    "锐": "Rui",
    "汝": "Ru",
    "莎": "Sha",
    "珊": "Shan",
    "尚": "Shang",
    "上": "Shang",
    "生": "Sheng",
    "沈": "Shen",
    "松": "Song",
    "思": "Si",
    "苏": "Su",
    "速": "Su",
    "孙": "Sun",
    "素": "Su",
    "邰": "Tai",
    "唐": "Tang",
    "汤": "Tang",
    "陶": "Tao",
    "庭": "Ting",
    "彤": "Tong",
    "涂": "Tu",
    "皖": "Wan",
    "万": "Wan",
    "王": "Wang",
    "为": "Wei",
    "卫": "Wei",
    "伟": "Wei",
    "玮": "Wei",
    "维": "Wei",
    "薇": "Wei",
    "魏": "Wei",
    "炜": "Wei",
    "稳": "Wen",
    "雯": "Wen",
    "吴": "Wu",
    "武": "Wu",
    "席": "Xi",
    "香": "Xiang",
    "燨": "Xi",
    "肖": "Xiao",
    "笑": "Xiao",
    "小": "Xiao",
    "夏": "Xia",
    "谢": "Xie",
    "心": "Xin",
    "欣": "Xin",
    "鑫": "Xin",
    "醒": "Xing",
    "星": "Xing",
    "邢": "Xing",
    "行": "Xing",
    "宣": "Xuan",
    "璇": "Xuan",
    "学": "Xue",
    "薛": "Xue",
    "雅": "Ya",
    "芽": "Ya",
    "亚": "Ya",
    "雁": "Yan",
    "琰": "Yan",
    "艳": "Yan",
    "妍": "Yan",
    "晏": "Yan",
    "扬": "Yang",
    "洋": "Yang",
    "瑶": "Yao",
    "夜": "Ye",
    "叶": "Ye",
    "依": "Yi",
    "艺": "Yi",
    "意": "Yi",
    "奕": "Yi",
    "义": "Yi",
    "裔": "Yi",
    "莹": "Ying",
    "盈": "Ying",
    "颖": "Ying",
    "应": "Ying",
    "迎": "Ying",
    "尹": "Yin",
    "殷": "Yin",
    "于": "Yu",
    "羽": "Yu",
    "豫": "Yu",
    "雨": "Yu",
    "昱": "Yu",
    "钰": "Yu",
    "岳": "Yue",
    "远": "Yuan",
    "元": "Yuan",
    "源": "Yuan",
    "渊": "Yuan",
    "云": "Yun",
    "詹": "Zhan",
    "赵": "Zhao",
    "朕": "Zhen",
    "征": "Zheng",
    "芝": "Zhi",
    "志": "Zhi",
    "忠": "Zhong",
    "周": "Zhou",
    "竹": "Zhu",
    "紫": "Zi",
    "宗": "Zong",
    "邹": "Zou",
    "仇": "Chou",
    "蒋": "Jiang",
    "贾": "Jia",
}
PINYIN_OVERRIDES.update(
    {
        "阿": "A",
        "班": "Ban",
        "彬": "Bin",
        "蔡": "Cai",
        "岑": "Cen",
        "查": "Cha",
        "储": "Chu",
        "笪": "Da",
        "刁": "Diao",
        "房": "Fang",
        "顾": "Gu",
        "菡": "Han",
        "杭": "Hang",
        "郝": "Hao",
        "恒": "Heng",
        "纪": "Ji",
        "景": "Jing",
        "婕": "Jie",
        "瑾": "Jin",
        "凯": "Kai",
        "克": "Ke",
        "凌": "Ling",
        "玲": "Ling",
        "茆": "Mao",
        "么": "Me",
        "蒙": "Meng",
        "沫": "Mo",
        "牟": "Mou",
        "倪": "Ni",
        "聂": "Nie",
        "妞": "Niu",
        "盼": "Pan",
        "普": "Pu",
        "戚": "Qi",
        "奇": "Qi",
        "前": "Qian",
        "倩": "Qian",
        "芹": "Qin",
        "琼": "Qiong",
        "若": "Ruo",
        "儒": "Ru",
        "茹": "Ru",
        "睿": "Rui",
        "润": "Run",
        "色": "Se",
        "申": "Shen",
        "硕": "Shuo",
        "司": "Si",
        "谭": "Tan",
        "谈": "Tan",
        "天": "Tian",
        "亭": "Ting",
        "琬": "Wan",
        "婉": "Wan",
        "文": "Wen",
        "玟": "Wen",
        "新": "Xin",
        "现": "Xian",
        "霄": "Xiao",
        "晓": "Xiao",
        "悬": "Xuan",
        "牙": "Ya",
        "也": "Ye",
        "易": "Yi",
        "永": "Yong",
        "尤": "You",
        "玉": "Yu",
        "育": "Yu",
        "宇": "Yu",
        "余": "Yu",
        "俞": "Yu",
        "瑜": "Yu",
        "妤": "Yu",
        "越": "Yue",
        "悦": "Yue",
        "玥": "Yue",
        "昀": "Yun",
        "袁": "Yuan",
        "媛": "Yuan",
        "姚": "Yao",
        "扎": "Zha",
        "昭": "Zhao",
        "珍": "Zhen",
        "贞": "Zhen",
        "枝": "Zhi",
        "智": "Zhi",
        "钟": "Zhong",
        "朱": "Zhu",
        "子": "Zi",
        "函": "Han",
        "娟": "Juan",
    }
)

SUMMARY_FIELDS = [
    "dataset",
    "case",
    "chinese_name",
    "case_date",
    "gestational_age",
    "atlas_week",
    "atlas_rule",
    "input_file",
    "atlas",
    "orientation",
    "perm",
    "flips",
    "status",
    "qc_group",
    "mattes_lower_is_better",
    "gc_lower_is_better",
    "warped",
    "affine",
    "message",
]

MANIFEST_FIELDS = [
    "dataset",
    "case",
    "chinese_name",
    "case_date",
    "gestational_age",
    "atlas_week",
    "atlas_rule",
    "input_file",
    "atlas",
    "status",
    "message",
]


@dataclass(frozen=True)
class Orientation:
    name: str
    perm: tuple[int, int, int]
    flips: tuple[int, ...]

    @property
    def perm_name(self) -> str:
        return "".join("xyz"[i] for i in self.perm)

    @property
    def flips_name(self) -> str:
        return "".join("xyz"[i] for i in self.flips) or "none"


@dataclass(frozen=True)
class CandidateResult:
    case: str
    input_file: Path
    atlas: Path
    orientation: Orientation
    status: str
    mattes: float | None
    gc: float | None
    warped: Path | None
    affine: Path | None
    message: str = ""


@dataclass(frozen=True)
class RegistrationConfig:
    convergence: str
    shrink_factors: str
    smoothing_sigmas: str
    sampling_percentage: float
    itk_threads: int
    random_seed: int
    skip_gc: bool


@dataclass(frozen=True)
class CaseTask:
    dataset: str
    input_file: Path
    atlas: Path
    metadata: dict[str, str]


def orientation_candidates() -> list[Orientation]:
    candidates = []
    for perm in itertools.permutations((0, 1, 2)):
        perm_name = "".join("xyz"[i] for i in perm)
        for signs in itertools.product((0, 1), repeat=3):
            flips = tuple(i for i, should_flip in enumerate(signs) if should_flip)
            flip_name = "".join("xyz"[i] for i in flips) or "none"
            candidates.append(Orientation(f"p{perm_name}_f{flip_name}", perm, flips))
    return candidates


ORIENTATIONS = orientation_candidates()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    examples = dedent(
        f"""\
        Examples:
          Single-atlas mode:
            python {Path(__file__).name} --mode single --input-dir /path/to/inputs --atlas /path/to/24w.nii.gz --output-dir /path/to/output

          Fetal batch dry run with manifest:
            python {Path(__file__).name} --mode fetal-batch --dry-run --manifest-out /tmp/fetal_manifest.csv

          Legacy fetal batch invocation (still supported):
            python {Path(__file__).name} --fetal-batch --dry-run
        """
    )
    parser = argparse.ArgumentParser(
        description="Run 48 orientation candidates with ANTs rigid registration and keep only best outputs.",
        epilog=examples,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode_group = parser.add_argument_group("mode selection")
    mode_group.add_argument(
        "--mode",
        choices=("single", "fetal-batch"),
        help="Execution mode. Default: single. Use fetal-batch for the NJGL fetal workflow.",
    )
    mode_group.add_argument(
        "--fetal-batch",
        action="store_true",
        help="Legacy alias for --mode fetal-batch. Kept for compatibility.",
    )

    single_group = parser.add_argument_group("single-atlas mode arguments")
    single_group.add_argument("--input-dir", type=Path, help="Read-only directory containing case NIfTI files.")
    single_group.add_argument("--atlas", type=Path, help="Atlas NIfTI used as fixed image for all cases.")
    single_group.add_argument("--output-dir", type=Path, help="Directory for best outputs and metric CSV files.")
    single_group.add_argument("--pattern", default="*.nii.gz", help="Glob pattern for input case files. Default: *.nii.gz")

    fetal_group = parser.add_argument_group("fetal-batch mode arguments")
    fetal_group.add_argument("--fetal-root", default=DEFAULT_FETAL_ROOT, type=Path, help=f"Fetal data root. Default: {DEFAULT_FETAL_ROOT}")
    fetal_group.add_argument(
        "--atlas-dir",
        default=DEFAULT_FETAL_ATLAS_DIR,
        type=Path,
        help=f"Atlas directory containing NNw.nii.gz files. Default: {DEFAULT_FETAL_ATLAS_DIR}",
    )
    fetal_group.add_argument(
        "--master-xls",
        type=Path,
        help="Master fetal Excel table. Default: <fetal-root>/胎儿数据收集表.xls",
    )
    fetal_group.add_argument(
        "--datasets",
        help=(
            "Comma-separated fetal dataset directories to process. "
            f"Default: {','.join(DEFAULT_DATASETS)}"
        ),
    )
    fetal_group.add_argument(
        "--allow-existing-output",
        action="store_true",
        help="Allow fetal batch to write into an existing non-empty registration directory.",
    )
    fetal_group.add_argument("--dry-run", action="store_true", help="Build the fetal batch manifest without running ANTs.")
    fetal_group.add_argument(
        "--manifest-out",
        type=Path,
        help="Write fetal batch manifest CSV (runnable and skipped cases) before execution.",
    )

    perf_group = parser.add_argument_group("performance / registration arguments")
    perf_group.add_argument("--case-jobs", default=4, type=int, help="Number of cases to process in parallel. Default: 4")
    perf_group.add_argument(
        "--orientation-jobs",
        default=12,
        type=int,
        help="Number of orientation candidates to register in parallel within one case. Default: 12",
    )
    perf_group.add_argument("--itk-threads", default=4, type=int, help="ITK threads per ANTs process. Default: 4")
    perf_group.add_argument("--random-seed", default=1, type=int, help="ANTs random seed for reproducible registration. Default: 1")
    perf_group.add_argument(
        "--preset",
        choices=("full", "fast"),
        default="full",
        help="Registration preset. full keeps original settings; fast uses fewer levels/iterations. Default: full",
    )
    perf_group.add_argument("--convergence", help="Override ANTs convergence, e.g. [150x80x40,1e-6,10].")
    perf_group.add_argument("--shrink-factors", help="Override ANTs shrink factors, e.g. 8x4x2.")
    perf_group.add_argument("--smoothing-sigmas", help="Override ANTs smoothing sigmas, e.g. 3x2x1vox.")
    perf_group.add_argument(
        "--sampling-percentage",
        type=float,
        help="Mattes regular sampling percentage for registration. Default: 0.25 full, 0.10 fast.",
    )
    perf_group.add_argument("--skip-gc", action="store_true", help="Skip extra GC metric calculation to save time.")

    qc_group = parser.add_argument_group("QC output arguments")
    qc_group.add_argument("--no-qc-sets", action="store_true", help="Do not create acceptable_cases and suspicious_cases.")
    qc_group.add_argument(
        "--acceptable-mattes",
        default=-0.25,
        type=float,
        help="Acceptable threshold for Mattes. Lower is better. Default: -0.25",
    )
    qc_group.add_argument(
        "--acceptable-gc",
        default=-0.40,
        type=float,
        help="Acceptable threshold for GC. Lower is better. Ignored if GC is missing. Default: -0.40",
    )
    qc_group.add_argument(
        "--suspicious-mattes",
        default=-0.20,
        type=float,
        help="Retained for compatibility; QC now sends every non-acceptable case to suspicious. Default: -0.20",
    )
    qc_group.add_argument(
        "--suspicious-gc",
        default=-0.25,
        type=float,
        help="Retained for compatibility; QC now sends every non-acceptable case to suspicious. Default: -0.25",
    )

    debug_group = parser.add_argument_group("environment / debug arguments")
    debug_group.add_argument("--ants-dir", default=DEFAULT_ANTS_DIR, type=Path, help=f"ANTs bin directory. Default: {DEFAULT_ANTS_DIR}")
    debug_group.add_argument("--keep-work", action="store_true", help="Keep per-candidate work directories for debugging.")

    args = parser.parse_args(argv)
    if args.mode is None:
        args.mode = "fetal-batch" if args.fetal_batch else "single"
    elif args.fetal_batch and args.mode != "fetal-batch":
        parser.error("--fetal-batch conflicts with --mode single")

    if args.case_jobs < 1:
        parser.error("--case-jobs must be >= 1")
    if args.orientation_jobs < 1:
        parser.error("--orientation-jobs must be >= 1")
    if args.itk_threads < 1:
        parser.error("--itk-threads must be >= 1")
    if args.sampling_percentage is not None and not (0 < args.sampling_percentage <= 1):
        parser.error("--sampling-percentage must be within (0, 1]")
    if args.mode == "single":
        if args.dry_run:
            parser.error("--dry-run is only valid in --mode fetal-batch")
        if args.allow_existing_output:
            parser.error("--allow-existing-output is only valid in --mode fetal-batch")
        if args.manifest_out is not None:
            parser.error("--manifest-out is only valid in --mode fetal-batch")

    return args


def registration_config(args: argparse.Namespace) -> RegistrationConfig:
    if args.preset == "fast":
        convergence = "[150x80x40,1e-6,10]"
        shrink_factors = "8x4x2"
        smoothing_sigmas = "3x2x1vox"
        sampling_percentage = 0.10
    else:
        convergence = "[500x250x100x50,1e-6,10]"
        shrink_factors = "8x4x2x1"
        smoothing_sigmas = "3x2x1x0vox"
        sampling_percentage = 0.25

    return RegistrationConfig(
        convergence=args.convergence or convergence,
        shrink_factors=args.shrink_factors or shrink_factors,
        smoothing_sigmas=args.smoothing_sigmas or smoothing_sigmas,
        sampling_percentage=args.sampling_percentage if args.sampling_percentage is not None else sampling_percentage,
        itk_threads=args.itk_threads,
        random_seed=args.random_seed,
        skip_gc=args.skip_gc,
    )


def case_name(path: Path) -> str:
    name = path.name
    if name.endswith(".nii.gz"):
        return name[:-7]
    if name.endswith(".nii"):
        return name[:-4]
    return path.stem


def excel_serial_date(value: str) -> str:
    try:
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).strftime("%Y%m%d")
    except (TypeError, ValueError):
        return ""


def parse_gestational_week(value: str) -> int | None:
    text = value.strip().replace("＋", "+").replace("W", "周").replace("w", "周")
    patterns = (
        r"(\d{1,2})\s*[-~至]\s*\d{1,2}\s*周",
        r"(\d{1,2})\s*\+\s*\d+\s*周",
        r"(\d{1,2})\s*周",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None


def available_atlas_weeks(atlas_dir: Path) -> dict[int, Path]:
    atlases: dict[int, Path] = {}
    for path in atlas_dir.glob("*w.nii.gz"):
        match = re.fullmatch(r"(\d+)w\.nii\.gz", path.name)
        if match:
            atlases[int(match.group(1))] = path.resolve()
    if not atlases:
        raise FileNotFoundError(f"No atlas files named like NNw.nii.gz under {atlas_dir}")
    return atlases


def choose_nearest_atlas(week: int, atlases: dict[int, Path]) -> tuple[int, Path, str]:
    chosen_week = min(atlases, key=lambda x: (abs(x - week), x))
    rule = "exact" if chosen_week == week else f"nearest_from_{week}w"
    return chosen_week, atlases[chosen_week], rule


def choose_middle_atlas(atlases: dict[int, Path], reason: str) -> tuple[int, Path, str]:
    weeks = sorted(atlases)
    chosen_week = weeks[len(weeks) // 2]
    return chosen_week, atlases[chosen_week], f"middle_fallback_{reason}"


def convert_xls_to_xlsx(path: Path) -> Path:
    if path.suffix.lower() == ".xlsx":
        return path

    out_dir = Path(tempfile.mkdtemp(prefix="fetal_xls_", dir="/tmp"))
    cmd = [
        "libreoffice",
        "--headless",
        "--invisible",
        "--nodefault",
        "--nolockcheck",
        "--nofirststartwizard",
        f"-env:UserInstallation=file://{out_dir / 'lo_profile'}",
        "--convert-to",
        "xlsx",
        "--outdir",
        str(out_dir),
        str(path),
    ]
    env = os.environ.copy()
    env["HOME"] = "/tmp"
    env["XDG_RUNTIME_DIR"] = "/tmp"
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    converted = out_dir / f"{path.stem}.xlsx"
    if not converted.is_file():
        matches = sorted(out_dir.glob("*.xlsx"))
        if not matches:
            if proc.returncode != 0:
                raise RuntimeError(f"Failed to convert {path} to xlsx with LibreOffice:\n{proc.stdout}")
            raise FileNotFoundError(f"LibreOffice did not produce an xlsx file for {path}:\n{proc.stdout}")
        converted = matches[0]
    if proc.returncode != 0 and not converted.is_file():
        raise RuntimeError(f"Failed to convert {path} to xlsx with LibreOffice:\n{proc.stdout}")
    return converted


def read_xlsx_rows(path: Path) -> list[dict[str, str]]:
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

    def column_index(cell_ref: str) -> int:
        letters = "".join(ch for ch in cell_ref if ch.isalpha())
        index = 0
        for ch in letters:
            index = index * 26 + ord(ch.upper()) - ord("A") + 1
        return index - 1

    with ZipFile(path) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for item in root.findall("a:si", ns):
                shared.append(
                    "".join(
                        text_node.text or ""
                        for text_node in item.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
                    )
                )

        def cell_value(cell: ET.Element) -> str:
            cell_type = cell.attrib.get("t")
            value = cell.find("a:v", ns)
            if value is not None:
                text = value.text or ""
                return shared[int(text)] if cell_type == "s" else text

            inline = cell.find("a:is", ns)
            if inline is not None:
                return "".join(
                    text_node.text or ""
                    for text_node in inline.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
                )
            return ""

        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        dense_rows: list[list[str]] = []
        sheet_data = sheet.find("a:sheetData", ns)
        if sheet_data is None:
            return []
        for row in sheet_data:
            values: list[str] = []
            for cell in row:
                index = column_index(cell.attrib["r"])
                while len(values) <= index:
                    values.append("")
                values[index] = cell_value(cell).strip()
            dense_rows.append(values)

    if not dense_rows:
        return []
    header = dense_rows[0]
    rows: list[dict[str, str]] = []
    for row in dense_rows[1:]:
        if not any(row):
            continue
        padded = row + [""] * (len(header) - len(row))
        rows.append(dict(zip(header, padded)))
    return rows


def case_dates_from_nii(case_dir: Path) -> list[str]:
    dates = set()
    for path in case_dir.glob("*.nii.gz"):
        match = re.search(r"_(20\d{6})\d{6}_", path.name)
        if not match:
            match = re.search(r"(20\d{6})", path.name)
        if match:
            dates.add(match.group(1))
    return sorted(dates)


def split_case_tokens(case: str) -> list[str]:
    base = re.sub(r"_20\d+.*$", "", case)
    base = re.sub(r"20\d{6}$", "", base)
    return re.findall(r"[A-Z][a-z]*|[A-Z]+(?=[A-Z]|$)", base)


def case_pinyin_key(case: str) -> str:
    return "".join(split_case_tokens(case)).lower()


def build_pinyin_char_map(fetal_root: Path) -> dict[str, set[str]]:
    char_map: dict[str, set[str]] = {}
    for filename in DEFAULT_DATASET_MAPPINGS.values():
        path = fetal_root / filename
        if not path.is_file():
            continue
        for row in read_xlsx_rows(path):
            chinese_name = row.get("ID", "")
            tokens = split_case_tokens(row.get("Files", ""))
            if chinese_name and len(chinese_name) == len(tokens):
                for char, token in zip(chinese_name, tokens):
                    char_map.setdefault(char, set()).add(token)
    for char, token in PINYIN_OVERRIDES.items():
        char_map.setdefault(char, set()).add(token)
    return char_map


def pinyin_keys_for_name(name: str, char_map: dict[str, set[str]], limit: int = 64) -> set[str]:
    options = []
    for char in name:
        values = char_map.get(char)
        if not values:
            return set()
        options.append(sorted(values))

    keys: set[str] = set()
    for combo in _itertools.product(*options):
        keys.add("".join(combo).lower())
        if len(keys) >= limit:
            break
    return keys


def match_master_by_pinyin(
    case: str,
    candidates: list[dict[str, str]],
    char_map: dict[str, set[str]],
) -> list[dict[str, str]]:
    key = case_pinyin_key(case)
    return [row for row in candidates if key in pinyin_keys_for_name(row.get("姓名", ""), char_map)]


def dataset_names(args: argparse.Namespace) -> list[str]:
    if args.datasets:
        return [name.strip() for name in args.datasets.split(",") if name.strip()]
    return list(DEFAULT_DATASETS)


def build_fetal_tasks(args: argparse.Namespace) -> tuple[list[CaseTask], dict[str, list[dict[str, str]]]]:
    fetal_root = args.fetal_root.resolve()
    atlas_dir = args.atlas_dir.resolve()
    master_xls = (args.master_xls or fetal_root / "胎儿数据收集表.xls").resolve()
    atlases = available_atlas_weeks(atlas_dir)
    char_map = build_pinyin_char_map(fetal_root)

    master_rows = read_xlsx_rows(convert_xls_to_xlsx(master_xls))
    master_by_name: dict[str, list[dict[str, str]]] = {}
    for row in master_rows:
        row["_case_date"] = excel_serial_date(row.get("采集时间", ""))
        row["_source_week"] = str(parse_gestational_week(row.get("胎龄", "")) or "")
        master_by_name.setdefault(row.get("姓名", ""), []).append(row)

    dataset_specs = [
        (dataset, fetal_root / DEFAULT_DATASET_MAPPINGS[dataset])
        if dataset in DEFAULT_DATASET_MAPPINGS
        else (dataset, None)
        for dataset in dataset_names(args)
    ]

    tasks: list[CaseTask] = []
    skipped: dict[str, list[dict[str, str]]] = {dataset: [] for dataset, _ in dataset_specs}

    for dataset, mapping_file in dataset_specs:
        dataset_root = fetal_root / dataset
        nii_root = dataset_root / "nii"
        recon_root = dataset_root / "recon"
        if not dataset_root.is_dir():
            raise FileNotFoundError(f"Dataset directory does not exist: {dataset_root}")

        if mapping_file is not None and mapping_file.is_file():
            mapping_rows = read_xlsx_rows(mapping_file)
        else:
            case_names = sorted(
                {
                    path.name
                    for path in nii_root.iterdir()
                    if path.is_dir() and not path.name.startswith("_")
                }
                | {case_name(path) for path in recon_root.glob("*.nii.gz")}
            )
            mapping_rows = [{"ID": "", "Files": name} for name in case_names]

        for mapping in mapping_rows:
            chinese_name = mapping.get("ID", "")
            case = mapping.get("Files", "")
            if not case:
                continue

            dates = case_dates_from_nii(nii_root / case)
            candidates = master_by_name.get(chinese_name, [])
            if chinese_name:
                if len(candidates) == 1:
                    matched = candidates
                elif len(candidates) > 1 and dates:
                    matched = [row for row in candidates if row.get("_case_date") in dates]
                else:
                    matched = []
            else:
                date_candidates = []
                for date in dates:
                    date_candidates.extend(row for row in master_rows if row.get("_case_date") == date)
                matched = match_master_by_pinyin(case, date_candidates, char_map)
                candidates = date_candidates

            input_file = recon_root / f"{case}.nii.gz"
            common = {
                "dataset": dataset,
                "case": case,
                "chinese_name": chinese_name,
                "case_date": "|".join(dates),
                "input_file": str(input_file),
                "message": "",
            }

            if len(matched) != 1:
                reason = "name_not_in_master" if not candidates else "ambiguous_master_match"
                atlas_week, atlas, atlas_rule = choose_middle_atlas(atlases, reason)
                metadata = {
                    **common,
                    "gestational_age": "",
                    "atlas_week": str(atlas_week),
                    "atlas_rule": atlas_rule,
                    "message": (
                        f"Using middle atlas because master rows matched {len(matched)} "
                        f"and candidates were {len(candidates)}."
                    ),
                }
                if input_file.is_file():
                    tasks.append(CaseTask(dataset, input_file, atlas, metadata))
                else:
                    skipped[dataset].append(
                    {
                        **metadata,
                        "status": reason,
                        "qc_group": "suspicious",
                        "atlas": str(atlas),
                        "message": metadata["message"] + " Expected recon/<case>.nii.gz does not exist.",
                    }
                )
                continue

            master = matched[0]
            chinese_name = master.get("姓名", chinese_name)
            common["chinese_name"] = chinese_name
            source_week_text = master.get("_source_week", "")
            if not source_week_text:
                atlas_week, atlas, atlas_rule = choose_middle_atlas(atlases, "bad_gestational_age")
                metadata = {
                    **common,
                    "case_date": master.get("_case_date", "") or "|".join(dates),
                    "gestational_age": master.get("胎龄", ""),
                    "atlas_week": str(atlas_week),
                    "atlas_rule": atlas_rule,
                    "message": "Using middle atlas because gestational week could not be parsed.",
                }
                if input_file.is_file():
                    tasks.append(CaseTask(dataset, input_file, atlas, metadata))
                else:
                    skipped[dataset].append(
                    {
                        **metadata,
                        "status": "bad_gestational_age",
                        "qc_group": "suspicious",
                        "atlas": str(atlas),
                        "message": metadata["message"] + " Expected recon/<case>.nii.gz does not exist.",
                    }
                )
                continue

            source_week = int(source_week_text)
            atlas_week, atlas, atlas_rule = choose_nearest_atlas(source_week, atlases)
            metadata = {
                **common,
                "case_date": master.get("_case_date", "") or "|".join(dates),
                "gestational_age": master.get("胎龄", ""),
                "atlas_week": str(atlas_week),
                "atlas_rule": atlas_rule,
            }

            if not input_file.is_file():
                atlas_week, atlas, atlas_rule = choose_middle_atlas(atlases, "missing_input")
                skipped[dataset].append(
                    {
                        **metadata,
                        "status": "missing_input",
                        "qc_group": "suspicious",
                        "atlas_week": str(atlas_week),
                        "atlas_rule": atlas_rule,
                        "atlas": str(atlas),
                        "message": (
                            "Using middle atlas in summary because this skipped case is missing "
                            "recon/<case>.nii.gz and cannot be registered."
                        ),
                    }
                )
                continue

            tasks.append(CaseTask(dataset, input_file, atlas, metadata))

    return tasks, skipped


def validate_inputs(args: argparse.Namespace) -> tuple[Path, Path]:
    if not args.fetal_batch:
        missing = [name for name in ("input_dir", "atlas", "output_dir") if getattr(args, name) is None]
        if missing:
            raise ValueError(f"Missing required argument(s) outside --fetal-batch: {', '.join('--' + x.replace('_', '-') for x in missing)}")

    input_dir = args.input_dir.resolve()
    atlas = args.atlas.resolve()
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")
    if not atlas.is_file():
        raise FileNotFoundError(f"Atlas file does not exist: {atlas}")

    return validate_ants(args)


def validate_ants(args: argparse.Namespace) -> tuple[Path, Path]:
    ants_registration = args.ants_dir / "antsRegistration"
    measure_similarity = args.ants_dir / "MeasureImageSimilarity"
    if not ants_registration.is_file():
        raise FileNotFoundError(f"antsRegistration not found: {ants_registration}")
    if not measure_similarity.is_file():
        raise FileNotFoundError(f"MeasureImageSimilarity not found: {measure_similarity}")
    return ants_registration, measure_similarity


def make_candidate_image(src: Path, dst: Path, orientation: Orientation) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    img = nib.load(str(src))
    data = np.asanyarray(img.dataobj)
    data = np.transpose(data, axes=orientation.perm)
    if orientation.flips:
        data = np.flip(data, axis=orientation.flips)
    data = np.ascontiguousarray(data)

    # Header direction is treated as unreliable; every array orientation candidate
    # is put back into the same nominal physical frame before rigid registration.
    out = nib.Nifti1Image(data, img.affine, header=img.header.copy())
    out.set_data_dtype(img.get_data_dtype())
    qform, qcode = img.get_qform(coded=True)
    sform, scode = img.get_sform(coded=True)
    if qcode:
        out.set_qform(qform, int(qcode))
    if scode:
        out.set_sform(sform, int(scode))
    nib.save(out, str(dst))


def run_cmd(cmd: list[str], itk_threads: int) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] = str(itk_threads)
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)


def measure(metric: str, fixed: Path, moving: Path, measure_similarity: Path, itk_threads: int) -> float:
    if metric == "Mattes":
        spec = f"Mattes[{fixed},{moving},1,32,None]"
    elif metric == "GC":
        spec = f"GC[{fixed},{moving},1,NA,None]"
    else:
        raise ValueError(metric)

    proc = run_cmd([str(measure_similarity), "-d", "3", "-m", spec], itk_threads)
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout.strip())
    return float(proc.stdout.strip().splitlines()[-1])


def short_message(text: str, limit: int = 500) -> str:
    text = " ".join(text.strip().split())
    if len(text) <= limit:
        return text
    return text[-limit:]


def register_candidate(
    case: str,
    input_file: Path,
    atlas: Path,
    orientation: Orientation,
    output_dir: Path,
    ants_registration: Path,
    measure_similarity: Path,
    config: RegistrationConfig,
) -> CandidateResult:
    work_dir = output_dir / ".work" / case / orientation.name
    moving = work_dir / f"{case}_{orientation.name}.nii.gz"
    prefix = work_dir / "rigid_"
    warped = work_dir / "rigid_Warped.nii.gz"
    affine = work_dir / "rigid_0GenericAffine.mat"

    try:
        make_candidate_image(input_file, moving, orientation)
        cmd = [
            str(ants_registration),
            "-d",
            "3",
            "--float",
            "1",
            "--interpolation",
            "Linear",
            "--winsorize-image-intensities",
            "[0.005,0.995]",
            "--use-histogram-matching",
            "0",
            "--initial-moving-transform",
            f"[{atlas},{moving},1]",
            "--transform",
            "Rigid[0.1]",
            "--metric",
            f"Mattes[{atlas},{moving},1,32,Regular,{config.sampling_percentage}]",
            "--convergence",
            config.convergence,
            "--shrink-factors",
            config.shrink_factors,
            "--smoothing-sigmas",
            config.smoothing_sigmas,
            "--random-seed",
            str(config.random_seed),
            "-o",
            f"[{prefix},{warped}]",
        ]
        proc = run_cmd(cmd, config.itk_threads)
        if proc.returncode != 0:
            return CandidateResult(
                case, input_file, atlas, orientation, "failed", None, None, warped, affine, short_message(proc.stdout)
            )
        if not warped.exists() or not affine.exists():
            return CandidateResult(
                case,
                input_file,
                atlas,
                orientation,
                "missing_output",
                None,
                None,
                warped,
                affine,
                "ANTs completed but expected warped image or affine transform is missing.",
            )

        mattes = measure("Mattes", atlas, warped, measure_similarity, config.itk_threads)
        return CandidateResult(case, input_file, atlas, orientation, "ok", mattes, None, warped, affine)
    except Exception as exc:
        return CandidateResult(case, input_file, atlas, orientation, "error", None, None, warped, affine, str(exc))


def write_case_log(log_path: Path, rows: list[CandidateResult]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "case",
                "input_file",
                "atlas",
                "orientation",
                "perm",
                "flips",
                "status",
                "mattes_lower_is_better",
                "gc_lower_is_better",
                "message",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.case,
                    row.input_file,
                    row.atlas,
                    row.orientation.name,
                    row.orientation.perm_name,
                    row.orientation.flips_name,
                    row.status,
                    "" if row.mattes is None else f"{row.mattes:.9g}",
                    "" if row.gc is None else f"{row.gc:.9g}",
                    row.message,
                ]
            )


def copy_best(best: CandidateResult, best_dir: Path, metadata: dict[str, str] | None = None) -> tuple[Path, Path, Path]:
    if best.warped is None or best.affine is None:
        raise ValueError("Cannot copy best candidate without warped and affine paths.")

    best_dir.mkdir(parents=True, exist_ok=True)
    warped_out = best_dir / f"{best.case}_best_Warped.nii.gz"
    affine_out = best_dir / f"{best.case}_best_0GenericAffine.mat"
    txt_out = best_dir / f"{best.case}_best.txt"
    shutil.copy2(best.warped, warped_out)
    shutil.copy2(best.affine, affine_out)
    metadata_lines = []
    if metadata:
        for key in ("dataset", "chinese_name", "case_date", "gestational_age", "atlas_week", "atlas_rule", "qc_group"):
            if key in metadata:
                metadata_lines.append(f"{key}={metadata[key]}")
    txt_out.write_text(
        "\n".join(
            [
                f"case={best.case}",
                *metadata_lines,
                f"input_file={best.input_file}",
                f"atlas={best.atlas}",
                f"orientation={best.orientation.name}",
                f"perm={best.orientation.perm_name}",
                f"flips={best.orientation.flips_name}",
                f"mattes_lower_is_better={best.mattes:.9g}",
                f"gc_lower_is_better={'' if best.gc is None else f'{best.gc:.9g}'}",
                f"warped={warped_out}",
                f"affine={affine_out}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return warped_out, affine_out, txt_out


def classify_qc(row: dict[str, str], args: argparse.Namespace) -> str:
    mattes = parse_metric(row, "mattes_lower_is_better")
    gc = parse_metric(row, "gc_lower_is_better")
    if row.get("status") == "ok" and mattes is not None and mattes <= args.acceptable_mattes:
        if gc is None or gc <= args.acceptable_gc:
            return "acceptable"
    return "suspicious"


def process_case(
    input_file: Path,
    atlas: Path,
    output_dir: Path,
    ants_registration: Path,
    measure_similarity: Path,
    config: RegistrationConfig,
    keep_work: bool,
    args: argparse.Namespace,
    metadata: dict[str, str] | None = None,
) -> dict[str, str]:
    case = case_name(input_file)
    case_work = output_dir / ".work" / case
    metadata = metadata or {}
    orientation_jobs = max(1, min(int(args.orientation_jobs), len(ORIENTATIONS)))

    def _run_orientation(orientation: Orientation) -> CandidateResult:
        return register_candidate(
            case, input_file, atlas, orientation, output_dir, ants_registration, measure_similarity, config
        )

    if orientation_jobs == 1:
        case_results = [_run_orientation(orientation) for orientation in ORIENTATIONS]
    else:
        results_by_name: dict[str, CandidateResult] = {}
        with ThreadPoolExecutor(max_workers=orientation_jobs) as pool:
            futures = {pool.submit(_run_orientation, orientation): orientation for orientation in ORIENTATIONS}
            for future in as_completed(futures):
                result = future.result()
                results_by_name[result.orientation.name] = result
        case_results = [results_by_name[orientation.name] for orientation in ORIENTATIONS]

    best: CandidateResult | None = None
    for result in case_results:
        if result.status == "ok" and result.mattes is not None:
            if best is None or result.mattes < best.mattes:
                best = result

    if best is not None and not config.skip_gc and best.warped is not None:
        try:
            gc = measure("GC", atlas, best.warped, measure_similarity, config.itk_threads)
            best = replace(best, gc=gc)
            case_results = [
                best if result.orientation.name == best.orientation.name else result for result in case_results
            ]
        except Exception as exc:
            best = replace(best, message=" ".join(filter(None, [best.message, f"GC metric failed: {exc}"])))
            case_results = [
                best if result.orientation.name == best.orientation.name else result for result in case_results
            ]

    if not keep_work:
        for result in case_results:
            candidate_dir = output_dir / ".work" / case / result.orientation.name
            if best is None or result.orientation.name != best.orientation.name:
                shutil.rmtree(candidate_dir, ignore_errors=True)

    write_case_log(output_dir / "logs" / f"{case}.csv", case_results)

    if best is None:
        row = {
            "dataset": metadata.get("dataset", ""),
            "case": case,
            "chinese_name": metadata.get("chinese_name", ""),
            "case_date": metadata.get("case_date", ""),
            "gestational_age": metadata.get("gestational_age", ""),
            "atlas_week": metadata.get("atlas_week", ""),
            "atlas_rule": metadata.get("atlas_rule", ""),
            "input_file": str(input_file),
            "atlas": str(atlas),
            "orientation": "",
            "perm": "",
            "flips": "",
            "status": "no_successful_candidate",
            "qc_group": "suspicious",
            "mattes_lower_is_better": "",
            "gc_lower_is_better": "",
            "warped": "",
            "affine": "",
            "message": " ".join(filter(None, [metadata.get("message", ""), "No orientation candidate completed successfully."])),
        }
        if not keep_work:
            shutil.rmtree(case_work, ignore_errors=True)
        return row

    row = {
        "dataset": metadata.get("dataset", ""),
        "case": case,
        "chinese_name": metadata.get("chinese_name", ""),
        "case_date": metadata.get("case_date", ""),
        "gestational_age": metadata.get("gestational_age", ""),
        "atlas_week": metadata.get("atlas_week", ""),
        "atlas_rule": metadata.get("atlas_rule", ""),
        "input_file": str(input_file),
        "atlas": str(atlas),
        "orientation": best.orientation.name,
        "perm": best.orientation.perm_name,
        "flips": best.orientation.flips_name,
        "status": "ok",
        "qc_group": "",
        "mattes_lower_is_better": f"{best.mattes:.9g}",
        "gc_lower_is_better": "" if best.gc is None else f"{best.gc:.9g}",
        "warped": "",
        "affine": "",
        "message": metadata.get("message", ""),
    }
    row["qc_group"] = "" if args.no_qc_sets else classify_qc(row, args)
    best_dir = output_dir / "best" if args.no_qc_sets else output_dir / f"{row['qc_group']}_cases" / "best"
    copy_metadata = {**metadata, "qc_group": row["qc_group"]}
    warped_out, affine_out, _ = copy_best(best, best_dir, copy_metadata)
    row.update(
        {
            "warped": str(warped_out),
            "affine": str(affine_out),
        }
    )

    if not keep_work:
        shutil.rmtree(case_work, ignore_errors=True)
    return row


def write_summary(output_dir: Path, rows: list[dict[str, str]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(rows, key=lambda x: (x.get("dataset", ""), x["case"])):
            writer.writerow(row)


def build_fetal_manifest_rows(
    tasks: list[CaseTask],
    skipped_by_dataset: dict[str, list[dict[str, str]]],
) -> list[dict[str, str]]:
    rows = [
        {
            "dataset": task.metadata.get("dataset", task.dataset),
            "case": task.metadata.get("case", case_name(task.input_file)),
            "chinese_name": task.metadata.get("chinese_name", ""),
            "case_date": task.metadata.get("case_date", ""),
            "gestational_age": task.metadata.get("gestational_age", ""),
            "atlas_week": task.metadata.get("atlas_week", ""),
            "atlas_rule": task.metadata.get("atlas_rule", ""),
            "input_file": str(task.input_file),
            "atlas": str(task.atlas),
            "status": "runnable",
            "message": task.metadata.get("message", ""),
        }
        for task in tasks
    ]
    for dataset_rows in skipped_by_dataset.values():
        for row in dataset_rows:
            rows.append({field: row.get(field, "") for field in MANIFEST_FIELDS})
    return sorted(rows, key=lambda x: (x.get("dataset", ""), x["case"]))


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_metric(row: dict[str, str], key: str) -> float | None:
    value = row.get(key, "")
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def clear_link_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for item in path.iterdir():
        if item.is_symlink() or item.is_file():
            item.unlink()


def link_best_files(output_dir: Path, rows: list[dict[str, str]], best_out: Path) -> int:
    clear_link_dir(best_out)
    count = 0
    for row in rows:
        case = row["case"]
        for filename in (
            f"{case}_best_Warped.nii.gz",
            f"{case}_best_0GenericAffine.mat",
            f"{case}_best.txt",
        ):
            src = output_dir / "best" / filename
            if not src.exists():
                continue
            dst = best_out / src.name
            if dst.exists() or dst.is_symlink():
                dst.unlink()
            os.symlink(src, dst)
            count += 1
    return count


def write_qc_subset(
    output_dir: Path,
    folder_name: str,
    summary_name: str,
    rows: list[dict[str, str]],
    readme_lines: list[str],
) -> tuple[int, int]:
    subset_dir = output_dir / folder_name
    best_dir = subset_dir / "best"
    subset_dir.mkdir(parents=True, exist_ok=True)
    best_dir.mkdir(exist_ok=True)

    rows = sorted(rows, key=lambda x: x["case"])
    with (subset_dir / summary_name).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    with (subset_dir / "case_list.txt").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(row["case"] + "\n")
    with (subset_dir / "README.txt").open("w", encoding="utf-8") as f:
        f.write("\n".join(readme_lines) + "\n")

    best_file_count = sum(1 for path in best_dir.iterdir() if path.is_file() or path.is_symlink()) if best_dir.exists() else 0
    return len(rows), best_file_count


def write_qc_sets(output_dir: Path, rows: list[dict[str, str]], args: argparse.Namespace) -> None:
    acceptable = []
    suspicious = []
    for row in rows:
        group = row.get("qc_group") or classify_qc(row, args)
        row["qc_group"] = group
        if group == "acceptable":
            acceptable.append(row)
        else:
            suspicious.append(row)

    acceptable_count, acceptable_links = write_qc_subset(
        output_dir,
        "acceptable_cases",
        "summary_acceptable.csv",
        acceptable,
        [
            f"Acceptable cases selected from {output_dir / 'summary.csv'}",
            (
                "Criteria: status == ok, "
                f"Mattes <= {args.acceptable_mattes}, "
                f"and GC <= {args.acceptable_gc} when GC is available."
            ),
            "Lower Mattes/GC is better. If --skip-gc was used, GC criteria are ignored.",
            f"Count: {len(acceptable)} / {len(rows)}",
            "best/ contains final best warped image, affine transform, and best.txt files.",
        ],
    )
    suspicious_count, suspicious_links = write_qc_subset(
        output_dir,
        "suspicious_cases",
        "summary_suspicious.csv",
        suspicious,
        [
            f"Suspicious cases selected from {output_dir / 'summary.csv'}",
            (
                "Criteria: every case that does not meet acceptable criteria, including failed or missing-input cases."
            ),
            "Lower Mattes/GC is better. If --skip-gc was used, GC criteria are ignored.",
            f"Count: {len(suspicious)} / {len(rows)}",
            "best/ contains final best warped image, affine transform, and best.txt files when available.",
        ],
    )
    print(
        f"Wrote acceptable cases: {acceptable_count} cases, {acceptable_links} best files under "
        f"{output_dir / 'acceptable_cases'}"
    )
    print(
        f"Wrote suspicious cases: {suspicious_count} cases, {suspicious_links} best files under "
        f"{output_dir / 'suspicious_cases'}"
    )


def print_run_config(args: argparse.Namespace, config: RegistrationConfig) -> None:
    print(f"Mode: {args.mode}", flush=True)
    print(
        f"Case jobs: {args.case_jobs}; orientation jobs: {args.orientation_jobs}; "
        f"ITK threads per ANTs process: {config.itk_threads}",
        flush=True,
    )
    print(f"Preset: {args.preset}", flush=True)
    print(f"Convergence: {config.convergence}", flush=True)
    print(f"Shrink factors: {config.shrink_factors}", flush=True)
    print(f"Smoothing sigmas: {config.smoothing_sigmas}", flush=True)
    print(f"Sampling percentage: {config.sampling_percentage}", flush=True)
    print(f"Skip GC metric: {config.skip_gc}", flush=True)
    print(f"ANTs random seed: {config.random_seed}", flush=True)
    print(f"Keep work directories: {args.keep_work}", flush=True)
    print(f"Create QC sets: {not args.no_qc_sets}", flush=True)
    if not args.no_qc_sets:
        print(
            "QC thresholds: "
            f"acceptable Mattes <= {args.acceptable_mattes}, acceptable GC <= {args.acceptable_gc}; "
            "all other cases are suspicious",
            flush=True,
        )


def ensure_fetal_output_clean(output_dirs: list[Path], allow_existing: bool) -> None:
    if allow_existing:
        return
    non_empty = [path for path in output_dirs if path.exists() and any(path.iterdir())]
    if non_empty:
        commands = "\n".join(f"rm -rf {path}" for path in non_empty)
        raise FileExistsError(
            "Existing non-empty registration directories found. Delete them first or pass --allow-existing-output:\n"
            f"{commands}"
        )


def run_single_atlas(args: argparse.Namespace) -> None:
    ants_registration, measure_similarity = validate_inputs(args)
    config = registration_config(args)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "logs").mkdir(exist_ok=True)

    inputs = sorted(args.input_dir.resolve().glob(args.pattern))
    inputs = [p for p in inputs if p.is_file()]
    if not inputs:
        raise FileNotFoundError(f"No input files matched {args.pattern!r} under {args.input_dir.resolve()}")

    print(f"Input cases: {len(inputs)}", flush=True)
    print(f"Atlas: {args.atlas.resolve()}", flush=True)
    print(f"Output: {output_dir}", flush=True)
    print_run_config(args, config)

    summary_rows: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=args.case_jobs) as pool:
        futures = [
            pool.submit(
                process_case,
                input_file.resolve(),
                args.atlas.resolve(),
                output_dir,
                ants_registration,
                measure_similarity,
                config,
                args.keep_work,
                args,
            )
            for input_file in inputs
        ]
        for future in as_completed(futures):
            row = future.result()
            summary_rows.append(row)
            metric = row["mattes_lower_is_better"] or "NA"
            orientation = row["orientation"] or "NA"
            print(f"{row['case']:24s} {row['status']:24s} {orientation:12s} Mattes={metric}", flush=True)

    write_summary(output_dir, summary_rows)
    if not args.no_qc_sets:
        write_qc_sets(output_dir, summary_rows, args)
    if not args.keep_work:
        shutil.rmtree(output_dir / ".work", ignore_errors=True)

    print(f"\nWrote {output_dir / 'summary.csv'}")
    print(f"Wrote per-case candidate metrics under {output_dir / 'logs'}")
    if args.no_qc_sets:
        print(f"Wrote best outputs under {output_dir / 'best'}")
    else:
        print(f"Wrote acceptable case set under {output_dir / 'acceptable_cases'}")
        print(f"Wrote suspicious case set under {output_dir / 'suspicious_cases'}")


def run_fetal_batch(args: argparse.Namespace) -> None:
    config = registration_config(args)
    tasks, skipped_by_dataset = build_fetal_tasks(args)
    manifest_rows = build_fetal_manifest_rows(tasks, skipped_by_dataset)
    datasets = sorted({task.dataset for task in tasks} | set(skipped_by_dataset))
    output_dirs = [args.fetal_root.resolve() / dataset / "registration" for dataset in datasets]

    print(f"Fetal batch tasks: {len(tasks)} runnable cases", flush=True)
    for dataset in datasets:
        runnable = sum(1 for task in tasks if task.dataset == dataset)
        skipped = len(skipped_by_dataset.get(dataset, []))
        print(f"{dataset}: runnable={runnable}, skipped={skipped}", flush=True)

    nearest = [
        task
        for task in tasks
        if task.metadata.get("atlas_rule", "") != "exact"
        and not task.metadata.get("atlas_rule", "").startswith("middle_fallback_")
    ]
    skipped_nearest = [
        row
        for rows in skipped_by_dataset.values()
        for row in rows
        if row.get("atlas_rule", "") != "exact"
        and row.get("atlas_rule")
        and not row.get("atlas_rule", "").startswith("middle_fallback_")
    ]
    if nearest or skipped_nearest:
        print("Nearest atlas substitutions:", flush=True)
        for task in nearest[:50]:
            print(
                f"  {task.dataset}/{task.metadata['case']}: {task.metadata['gestational_age']} -> {task.metadata['atlas_week']}w",
                flush=True,
            )
        for row in skipped_nearest[:50]:
            print(f"  {row['dataset']}/{row['case']}: {row['gestational_age']} -> {row['atlas_week']}w", flush=True)
        omitted = len(nearest) + len(skipped_nearest) - 100
        if omitted > 0:
            print(f"  ... omitted {omitted} more substitutions", flush=True)

    middle_fallback = [task for task in tasks if task.metadata.get("atlas_rule", "").startswith("middle_fallback_")]
    skipped_middle_fallback = [
        row for rows in skipped_by_dataset.values() for row in rows if row.get("atlas_rule", "").startswith("middle_fallback_")
    ]
    if middle_fallback or skipped_middle_fallback:
        print("Middle atlas fallbacks:", flush=True)
        for task in middle_fallback[:50]:
            print(
                f"  {task.dataset}/{task.metadata['case']}: {task.metadata.get('atlas_rule', '')} -> {task.metadata['atlas_week']}w",
                flush=True,
            )
        for row in skipped_middle_fallback[:50]:
            print(f"  {row['dataset']}/{row['case']}: {row.get('atlas_rule', '')} -> {row.get('atlas_week', '')}w", flush=True)
        omitted = len(middle_fallback) + len(skipped_middle_fallback) - 100
        if omitted > 0:
            print(f"  ... omitted {omitted} more middle fallbacks", flush=True)

    if args.manifest_out is not None:
        manifest_path = args.manifest_out.resolve()
        write_manifest(manifest_path, manifest_rows)
        print(f"Wrote fetal manifest: {manifest_path}", flush=True)

    if args.dry_run:
        print("Dry run only; no registration directories were created and ANTs was not run.", flush=True)
        return

    ensure_fetal_output_clean(output_dirs, args.allow_existing_output)
    ants_registration, measure_similarity = validate_ants(args)
    print_run_config(args, config)

    rows_by_dataset: dict[str, list[dict[str, str]]] = {dataset: list(skipped_by_dataset.get(dataset, [])) for dataset in datasets}
    for output_dir in output_dirs:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "logs").mkdir(exist_ok=True)

    with ThreadPoolExecutor(max_workers=args.case_jobs) as pool:
        futures = []
        for task in tasks:
            output_dir = args.fetal_root.resolve() / task.dataset / "registration"
            futures.append(
                pool.submit(
                    process_case,
                    task.input_file.resolve(),
                    task.atlas.resolve(),
                    output_dir,
                    ants_registration,
                    measure_similarity,
                    config,
                    args.keep_work,
                    args,
                    task.metadata,
                )
            )

        for future in as_completed(futures):
            row = future.result()
            rows_by_dataset[row["dataset"]].append(row)
            metric = row["mattes_lower_is_better"] or "NA"
            orientation = row["orientation"] or "NA"
            print(
                f"{row['dataset']:24s} {row['case']:24s} {row['qc_group']:10s} {orientation:12s} Mattes={metric}",
                flush=True,
            )

    for dataset, rows in rows_by_dataset.items():
        output_dir = args.fetal_root.resolve() / dataset / "registration"
        write_summary(output_dir, rows)
        if not args.no_qc_sets:
            write_qc_sets(output_dir, rows, args)
        if not args.keep_work:
            shutil.rmtree(output_dir / ".work", ignore_errors=True)
        print(f"\n{dataset}: wrote {output_dir / 'summary.csv'}")
        print(f"{dataset}: wrote per-case candidate metrics under {output_dir / 'logs'}")
        if args.no_qc_sets:
            print(f"{dataset}: wrote best outputs under {output_dir / 'best'}")
        else:
            print(f"{dataset}: wrote acceptable case set under {output_dir / 'acceptable_cases'}")
            print(f"{dataset}: wrote suspicious case set under {output_dir / 'suspicious_cases'}")


def main() -> None:
    args = parse_args(sys.argv[1:])
    if args.mode == "fetal-batch":
        run_fetal_batch(args)
    else:
        run_single_atlas(args)


if __name__ == "__main__":
    main()

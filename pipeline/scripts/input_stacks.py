"""Identify 3D stacks without requiring a BTFE filename, and keep the richest family."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


JUNK_SERIES = re.compile(r"SURVEY|SCOUT|LOCALIZER|CALIBRATION|SMARTBRAIN", re.I)
FAMILY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ssfp_btfe", re.compile(r"B-?TFE|BFFE|TRUEFISP|FIESTA|bSSFP", re.I)),
    ("t2_ssfse", re.compile(r"HASTE|SSFSE|SSh_TSE|SSH.?TSE|T2_HASTE|t2.?haste", re.I)),
    ("t2", re.compile(r"(?:^|[_-])T2(?:W)?(?:[_-]|$)|T2W_TSE", re.I)),
    ("t1", re.compile(r"(?:^|[_-])T1(?:W)?(?:[_-]|$)|T1TFE|T1W_TFE|MPRAGE|SPGR", re.I)),
    ("dwi", re.compile(r"DWI|DIFFUSION|EP2D.?DIFF", re.I)),
    ("adc", re.compile(r"DADC|(?:^|[_-])ADC(?:[_./-]|$)", re.I)),
    ("flair", re.compile(r"FLAIR", re.I)),
    ("swi", re.compile(r"\bSWI\b", re.I)),
)
FAMILY_LABELS = {
    "ssfp_btfe": "BTFE / bSSFP",
    "t2_ssfse": "T2 HASTE / SSFSE",
    "t2": "T2",
    "t1": "T1",
    "dwi": "DWI",
    "adc": "ADC",
    "flair": "FLAIR",
    "swi": "SWI",
}
SAFE_STACK = re.compile(r"^[A-Za-z0-9._-]+\.nii\.gz$", re.I)


def is_nifti_name(name: str) -> bool:
    text = str(name or "").lower()
    return text.endswith(".nii.gz") or text.endswith(".nii")


def iter_input_stacks(directory: Path) -> list[Path]:
    root = Path(directory)
    if not root.is_dir():
        return []
    stacks: list[Path] = []
    for path in sorted(root.iterdir()):
        if not path.is_file():
            continue
        name = path.name.lower()
        if "crop" in name or not is_nifti_name(path.name):
            continue
        stacks.append(path)
    return stacks


def load_sidecar(nifti: Path) -> dict[str, Any]:
    sidecar = nifti.with_suffix("").with_suffix(".json")
    if not sidecar.is_file():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def is_junk_series(sidecar: dict[str, Any] | None = None, filename: str = "") -> bool:
    sidecar = sidecar or {}
    tokens = [
        str(sidecar.get("SeriesDescription") or ""),
        str(sidecar.get("ProtocolName") or ""),
        str(sidecar.get("PulseSequenceName") or ""),
        Path(filename).name,
    ]
    return any(JUNK_SERIES.search(token or "") for token in tokens)


def modality_family(sidecar: dict[str, Any] | None = None, filename: str = "") -> str:
    sidecar = sidecar or {}
    tokens = [
        str(sidecar.get("SeriesDescription") or ""),
        str(sidecar.get("ProtocolName") or ""),
        str(sidecar.get("PulseSequenceName") or ""),
        Path(filename).name,
    ]
    blob = " ".join(token for token in tokens if token)
    for family, pattern in FAMILY_PATTERNS:
        if pattern.search(blob):
            return family
    stem = Path(filename).name
    stem = re.sub(r"\.nii(\.gz)?$", "", stem, flags=re.I)
    stem = re.sub(r"_\d+$", "", stem)
    key = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")
    return key or "unknown"


def family_label(family: str) -> str:
    return FAMILY_LABELS.get(family) or family.replace("_", " ")


def volume_geometry(path: Path) -> tuple[bool, int]:
    import nibabel as nib

    image = nib.load(str(path), mmap=True)
    shape = tuple(int(dim) for dim in image.shape)
    if len(shape) < 3:
        return False, 0
    voxels = int(shape[0] * shape[1] * shape[2])
    is_3d = len(shape) == 3 or (len(shape) == 4 and shape[3] == 1)
    return is_3d, voxels


def safe_stack_name(name: str, index: int, used: set[str]) -> str:
    raw = Path(name).name
    if raw.lower().endswith(".nii") and not raw.lower().endswith(".nii.gz"):
        raw = raw[:-4] + ".nii.gz"
    if not SAFE_STACK.fullmatch(raw):
        raw = f"stack_{index:02d}.nii.gz"
    stem = raw[:-7] if raw.lower().endswith(".nii.gz") else raw
    candidate = f"{stem}.nii.gz"
    suffix = 2
    while candidate in used:
        candidate = f"{stem}_{suffix}.nii.gz"
        suffix += 1
    used.add(candidate)
    return candidate


def select_richest_family(volumes: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep the 3D family with the most stacks (tie-break: total voxels)."""
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in volumes:
        if item.get("junk"):
            dropped.append({**item, "reason": "scout"})
            continue
        if not item.get("is_3d"):
            dropped.append({**item, "reason": "not_3d"})
            continue
        groups.setdefault(str(item["family"]), []).append(item)
    if not groups:
        return {"family": None, "kept": [], "dropped": dropped}

    def score(family: str) -> tuple[int, int]:
        members = groups[family]
        return (len(members), sum(int(item.get("voxels") or 0) for item in members))

    winner = max(groups, key=lambda family: (*score(family), family))
    kept = list(groups[winner])
    for family, members in groups.items():
        if family == winner:
            continue
        for item in members:
            dropped.append({**item, "reason": "other_modality"})
    return {"family": winner, "kept": kept, "dropped": dropped}

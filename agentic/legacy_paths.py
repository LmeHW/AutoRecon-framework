"""Map pre-migration case-run directories to their current locations."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_RUN_ROOT = PROJECT_ROOT / "runs" / "legacy"

LEGACY_RUN_MAP = {
    "AnHuiJing_run01": ("AnHuiJing", "run01"),
    "AnHuiJing_run02": ("AnHuiJing", "run02"),
    "AnHuiJing_raw_run01": ("AnHuiJing", "raw_run01"),
    "AnHuiJing_full_demo_run01": ("AnHuiJing", "full_demo_run01"),
    "BaiHuPing_run01": ("BaiHuPing", "run01"),
    "CaiYuYu_raw_run01": ("CaiYuYu", "raw_run01"),
    "CaoLi_run01": ("CaoLi", "run01"),
    "CaoLi_registered_run02": ("CaoLi", "registered_run02"),
}


def legacy_path_replacements(project_root: Path | None = None) -> list[tuple[str, str]]:
    root = str((project_root or PROJECT_ROOT).resolve())
    pairs: list[tuple[str, str]] = []
    for legacy_name, (subject, run_name) in LEGACY_RUN_MAP.items():
        old = f"{root}/{legacy_name}"
        new = f"{root}/runs/legacy/{subject}/{run_name}"
        pairs.append((old, new))
        pairs.append((quote(old, safe=""), quote(new, safe="")))
    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    return pairs


def rewrite_legacy_file_urls(text: str, project_root: Path | None = None) -> str:
    updated = text
    for old, new in legacy_path_replacements(project_root):
        updated = updated.replace(old, new)
    return updated


def resolve_relocated_run_file(path: Path, project_root: Path | None = None) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.exists():
        return resolved
    root = (project_root or PROJECT_ROOT).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return resolved
    parts = relative.parts
    if not parts:
        return resolved
    mapped = LEGACY_RUN_MAP.get(parts[0])
    if not mapped:
        return resolved
    subject, run_name = mapped
    candidate = (root / "runs" / "legacy" / subject / run_name).joinpath(*parts[1:])
    return candidate if candidate.exists() else resolved

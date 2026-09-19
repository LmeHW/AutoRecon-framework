#!/usr/bin/env python3
"""Move legacy case runs out of the repository root without breaking artifacts.

The default mode is read-only. Pass --execute to move directories, rewrite known
absolute path references, and save a migration manifest under runs/migrations.
The migration uses same-filesystem renames, so it does not duplicate large MRI data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_ROOT = PROJECT_ROOT / "runs" / "legacy"

RUN_MAP = {
    "AnHuiJing_run01": ("AnHuiJing", "run01"),
    "AnHuiJing_run02": ("AnHuiJing", "run02"),
    "AnHuiJing_raw_run01": ("AnHuiJing", "raw_run01"),
    "AnHuiJing_full_demo_run01": ("AnHuiJing", "full_demo_run01"),
    "BaiHuPing_run01": ("BaiHuPing", "run01"),
    "CaiYuYu_raw_run01": ("CaiYuYu", "raw_run01"),
    "CaoLi_run01": ("CaoLi", "run01"),
    "CaoLi_registered_run02": ("CaoLi", "registered_run02"),
}

TEXT_SUFFIXES = {
    ".json", ".html", ".md", ".csv", ".tsv", ".txt", ".log",
    ".yaml", ".yml", ".sh", ".py", ".js", ".css", ".stats",
}
SKIP_PARTS = {".git", ".runtime", "__pycache__", "nnUNet_results"}
REFERENCE_ROOTS = (
    "agentic_runs", "demo_runs", "backend_validation", "migration_smoke",
    "presentation", "docs", "scripts", "pipeline",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return str(size)


def tree_stats(root: Path) -> tuple[int, int]:
    count = total = 0
    for base, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in SKIP_PARTS]
        for name in files:
            path = Path(base) / name
            if path.is_symlink():
                continue
            try:
                total += path.stat().st_size
                count += 1
            except OSError:
                pass
    return count, total


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def key_files(root: Path) -> list[Path]:
    # Text manifests intentionally change when absolute paths are rewritten.
    # Hash canonical medical images here to verify that the move itself did
    # not alter binary results.
    candidates: list[Path] = []
    candidates.extend((root / "outputs" / "recon").glob("*.nii.gz") if (root / "outputs" / "recon").is_dir() else [])
    candidates.extend((root / "outputs" / "registered_input").glob("*.nii.gz") if (root / "outputs" / "registered_input").is_dir() else [])
    return sorted({path for path in candidates if path.is_file()})


def candidate_text_files(moved_roots: Iterable[Path]) -> Iterable[Path]:
    seen: set[Path] = set()
    roots = list(moved_roots)
    roots.extend(PROJECT_ROOT / name for name in REFERENCE_ROOTS)
    roots.extend((PROJECT_ROOT / "README.md", PROJECT_ROOT / ".env.example"))
    for root in roots:
        if root.is_file():
            paths = (root,)
        elif root.is_dir():
            paths = (Path(base) / name for base, dirs, files in os.walk(root)
                     for _ in [dirs.__setitem__(slice(None), [d for d in dirs if d not in SKIP_PARTS])]
                     for name in files)
        else:
            continue
        for path in paths:
            if path in seen or path.is_symlink() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            seen.add(path)
            yield path


def rewrite_references(
    files: Iterable[Path], replacements: dict[bytes, bytes], execute: bool
) -> tuple[int, list[str], list[dict[str, str]]]:
    changed: list[str] = []
    skipped: list[dict[str, str]] = []
    for path in files:
        try:
            data = path.read_bytes()
        except OSError:
            continue
        updated = data
        for old, new in replacements.items():
            updated = updated.replace(old, new)
        if updated == data:
            continue
        changed.append(str(path.relative_to(PROJECT_ROOT)))
        if execute:
            try:
                path.write_bytes(updated)
            except OSError as exc:
                changed.pop()
                skipped.append({"path": str(path.relative_to(PROJECT_ROOT)), "error": str(exc)})
    return len(changed), changed, skipped


def validate_dashboard(root: Path) -> list[str]:
    errors: list[str] = []
    state_path = root / "dashboard" / "run_state.json"
    if not state_path.is_file():
        return ["dashboard/run_state.json is missing"]
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"cannot read dashboard state: {exc}"]
    recorded_root = Path(state.get("run", {}).get("work_root") or "").resolve()
    if recorded_root != root.resolve():
        errors.append(f"work_root mismatch: {recorded_root}")
    for step in state.get("steps", []):
        for artifact in step.get("artifacts", []):
            raw = artifact.get("path")
            if raw and Path(raw).is_absolute() and not Path(raw).exists():
                errors.append(f"missing artifact: {raw}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--execute", action="store_true", help="Perform the migration; default is dry-run.")
    args = parser.parse_args()
    run_root = args.run_root.expanduser().resolve()

    rows: list[dict] = []
    conflicts: list[str] = []
    for legacy_name, (subject, run_name) in RUN_MAP.items():
        source = PROJECT_ROOT / legacy_name
        destination = run_root / subject / run_name
        if source.exists() and destination.exists():
            conflicts.append(f"both source and destination exist: {source} -> {destination}")
            continue
        if not source.exists() and not destination.exists():
            conflicts.append(f"source is missing: {source}")
            continue
        current = source if source.exists() else destination
        count, size = tree_stats(current)
        rows.append({
            "legacy_name": legacy_name,
            "subject": subject,
            "run_name": run_name,
            "source": str(source),
            "destination": str(destination),
            "current": str(current),
            "already_migrated": destination.exists() and not source.exists(),
            "file_count": count,
            "size_bytes": size,
            "size": human_size(size),
        })

    print(json.dumps({"mode": "execute" if args.execute else "dry-run", "run_root": str(run_root), "runs": rows, "conflicts": conflicts}, indent=2, ensure_ascii=False))
    if conflicts:
        return 2
    if not args.execute:
        return 0

    checksums_before: dict[str, dict[str, str]] = {}
    for row in rows:
        current = Path(row["current"])
        checksums_before[row["legacy_name"]] = {
            str(path.relative_to(current)): sha256(path) for path in key_files(current)
        }

    for row in rows:
        if row["already_migrated"]:
            continue
        source, destination = Path(row["source"]), Path(row["destination"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        row["current"] = str(destination)

    from urllib.parse import quote

    replacements = {}
    for row in rows:
        old, new = str(Path(row["source"])), str(Path(row["destination"]))
        replacements[old.encode()] = new.encode()
        replacements[quote(old, safe="").encode()] = quote(new, safe="").encode()
    moved_roots = [Path(row["destination"]) for row in rows]
    rewrite_count, rewritten_files, skipped_rewrites = rewrite_references(
        candidate_text_files(moved_roots), replacements, execute=True
    )

    validation: dict[str, dict] = {}
    all_valid = True
    for row in rows:
        destination = Path(row["destination"])
        before = checksums_before[row["legacy_name"]]
        after = {str(path.relative_to(destination)): sha256(path) for path in key_files(destination)}
        errors = validate_dashboard(destination)
        if before != after:
            errors.append("key-file checksum set changed during migration")
        validation[row["legacy_name"]] = {
            "destination": str(destination),
            "checksums": after,
            "errors": errors,
            "status": "pass" if not errors else "fail",
        }
        all_valid = all_valid and not errors

    manifest = {
        "schema_version": 1,
        "created_at": utc_now(),
        "project_root": str(PROJECT_ROOT),
        "run_root": str(run_root),
        "runs": rows,
        "rewritten_file_count": rewrite_count,
        "rewritten_files": rewritten_files,
        "skipped_rewrites": skipped_rewrites,
        "validation": validation,
        "status": "completed" if all_valid else "completed_with_validation_errors",
    }
    manifest_dir = PROJECT_ROOT / "runs" / "migrations"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"legacy-case-runs-{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Migration manifest: {manifest_path}")
    print(f"Rewritten text files: {rewrite_count}")
    print(f"Skipped read-only text files: {len(skipped_rewrites)}")
    print(f"Validation: {'PASS' if all_valid else 'FAIL'}")
    return 0 if all_valid else 3


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Convert a DICOM zip or folder to 3D NIfTI stacks with dcm2niix."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

try:
    from pipeline.scripts.input_stacks import (
        family_label,
        is_junk_series,
        load_sidecar,
        modality_family,
        safe_stack_name,
        select_richest_family,
        volume_geometry,
    )
except ImportError:  # script execution from pipeline/scripts
    from input_stacks import (  # type: ignore
        family_label,
        is_junk_series,
        load_sidecar,
        modality_family,
        safe_stack_name,
        select_richest_family,
        volume_geometry,
    )


MAX_STACKS = 20
MAX_DICOM_FILES = 20000
SKIP_DIR = re.compile(r"^(Viewer|DICOMDIR|.+_JPG)$", re.I)
JUNK_FILE = re.compile(
    r"^(DICOMDIR|Thumbs\.db|desktop\.ini|StudyInfo\.dat)$|\.(jpg|jpeg|png|gif|bmp|pdf|exe|txt|dat|xlsx|xls|doc|docx|json)$",
    re.I,
)
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.-]+$")
SERIES_IN_NAME = re.compile(r"_(\d+)\.nii\.gz$", re.I)
UNSAFE_PATH_CHAR = re.compile(r'[\x00-\x1f<>:"|?*]')


class ConvertError(ValueError):
    """Raised when DICOM conversion or stack selection fails."""


def is_irrelevant_upload(rel: str) -> bool:
    text = str(rel or "").replace("\\", "/").strip()
    if not text:
        return True
    parts = [part for part in text.split("/") if part]
    if not parts:
        return True
    name = parts[-1]
    if name.startswith(".") or JUNK_FILE.search(name):
        return True
    return any(SKIP_DIR.match(part) for part in parts)


def is_zip_upload(rel: str) -> bool:
    return Path(str(rel or "")).name.lower().endswith(".zip")


def is_nifti_upload(rel: str) -> bool:
    name = Path(str(rel or "")).name.lower()
    return name.endswith(".nii.gz") or name.endswith(".nii")


def is_dicom_upload(rel: str) -> bool:
    text = str(rel or "").replace("\\", "/").strip()
    if not text or is_irrelevant_upload(text) or is_zip_upload(text) or is_nifti_upload(text):
        return False
    return True


def allowed_upload_relpath(value: object) -> str | None:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/") or UNSAFE_PATH_CHAR.search(raw):
        return None
    parts: list[str] = []
    for part in raw.split("/"):
        if part in {"", ".", ".."} or part.startswith("."):
            return None
        parts.append(part)
    if not parts or len(parts) > 24:
        return None
    rel = "/".join(parts)
    if len(rel) > 512 or is_irrelevant_upload(rel):
        return None
    if not (is_zip_upload(rel) or is_nifti_upload(rel) or is_dicom_upload(rel)):
        return None
    return rel


def _volume_record(path: Path) -> dict[str, Any]:
    sidecar = load_sidecar(path)
    try:
        is_3d, voxels = volume_geometry(path)
    except Exception:
        is_3d, voxels = True, 0
    return {
        "path": path,
        "sidecar": sidecar,
        "label": _series_label(sidecar, path.name),
        "family": modality_family(sidecar, path.name),
        "junk": is_junk_series(sidecar, path.name),
        "is_3d": is_3d,
        "voxels": voxels,
        "series_number": _series_number(sidecar, path.name),
    }


def _series_number(sidecar: dict[str, Any], filename: str) -> int | None:
    number = sidecar.get("SeriesNumber")
    try:
        return int(number) if number is not None else series_number_from_name(filename)
    except (TypeError, ValueError):
        return series_number_from_name(filename)


def _selection_error(dropped: list[dict[str, Any]]) -> ConvertError:
    listed = "、".join(item.get("label") or Path(str(item.get("path") or "")).name for item in dropped) or "（没有可读序列）"
    return ConvertError(f"未找到可用于三维重建的 3D 栈。dcm2niix 产出：{listed}")


def _write_conversion_report(directory: Path, report: dict[str, Any]) -> None:
    (directory / "conversion.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _finalize_kept(directory: Path, selection: dict[str, Any]) -> dict[str, Any]:
    kept = list(selection.get("kept") or [])
    dropped = list(selection.get("dropped") or [])
    if not kept:
        raise _selection_error(dropped)
    if len(kept) > MAX_STACKS:
        raise ConvertError(f"同一模态的三维栈超过 {MAX_STACKS} 个（{len(kept)}），请只导出用于重建的多方向栈再上传。")
    kept.sort(key=lambda item: (item.get("series_number") is None, item.get("series_number") or 0, Path(item["path"]).name))
    used: set[str] = set()
    names: list[str] = []
    series: list[dict[str, Any]] = []
    for index, item in enumerate(kept, start=1):
        source = Path(item["path"])
        name = safe_stack_name(source.name, index, used)
        target = directory / name
        if source.resolve() != target.resolve():
            if target.exists():
                target.unlink()
            shutil.move(str(source), target)
            sidecar_src = source.with_suffix("").with_suffix(".json")
            sidecar_dst = target.with_suffix("").with_suffix(".json")
            if sidecar_src.is_file() and sidecar_src.resolve() != sidecar_dst.resolve():
                if sidecar_dst.exists():
                    sidecar_dst.unlink()
                shutil.move(str(sidecar_src), sidecar_dst)
        names.append(name)
        series.append({
            "name": name,
            "original_name": source.name,
            "series_number": item.get("series_number"),
            "description": item.get("label"),
            "family": item.get("family"),
        })
    root = directory.resolve()
    for item in dropped:
        leftover = Path(item["path"])
        try:
            parent = leftover.parent.resolve()
        except OSError:
            continue
        if leftover.is_file() and (parent == root or root in leftover.resolve().parents):
            leftover.unlink(missing_ok=True)
            leftover.with_suffix("").with_suffix(".json").unlink(missing_ok=True)
    family = selection.get("family")
    drop_labels = [item.get("label") or Path(str(item.get("path") or "")).name for item in dropped]
    report = {
        "ok": True,
        "kept_family": family,
        "kept_family_label": family_label(str(family or "")),
        "stacks": names,
        "btfe": names,
        "series": series,
        "dropped": drop_labels,
        "drop_reasons": [
            {
                "label": item.get("label") or Path(str(item.get("path") or "")).name,
                "reason": item.get("reason"),
                "family": item.get("family"),
            }
            for item in dropped
        ],
    }
    _write_conversion_report(directory, report)
    return report


def normalize_uploaded_niftis(directory: Path) -> list[str]:
    import gzip as gzip_mod

    niftis = [
        path
        for path in sorted(directory.rglob("*"))
        if path.is_file() and is_nifti_upload(path.name) and path.name != ".upload.json"
    ]
    if not niftis:
        raise ConvertError("没有可用的 NIfTI 文件。")
    volumes: list[dict[str, Any]] = []
    for path in niftis:
        original = path.name
        current = path
        if path.name.lower().endswith(".nii") and not path.name.lower().endswith(".nii.gz"):
            current = path.with_name(path.name[:-4] + ".nii.gz")
            current.write_bytes(gzip_mod.compress(path.read_bytes()))
            path.unlink(missing_ok=True)
        record = _volume_record(current)
        record["label"] = _series_label(record.get("sidecar") or {}, original)
        record["family"] = modality_family(record.get("sidecar") or {}, original)
        record["junk"] = is_junk_series(record.get("sidecar") or {}, original)
        volumes.append(record)
    return _finalize_kept(directory, select_richest_family(volumes))["stacks"]


def clear_non_btfe_outputs(directory: Path) -> None:
    keep_exact = {".upload.json", "conversion.json"}
    root = Path(directory).resolve()
    for path in list(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.name in keep_exact:
            continue
        rel_parent = path.parent.resolve()
        name = path.name.lower()
        if rel_parent == root and (name.endswith(".nii.gz") or name.endswith(".nii")):
            continue
        if rel_parent == root and name.endswith(".json"):
            sibling = path.with_suffix("").with_suffix(".nii.gz")
            if sibling.is_file():
                continue
        path.unlink(missing_ok=True)
    for path in sorted(directory.rglob("*"), reverse=True):
        if path.is_dir() and path != directory and not any(path.iterdir()):
            path.rmdir()


def series_number_from_name(name: str) -> int | None:
    match = SERIES_IN_NAME.search(name)
    return int(match.group(1)) if match else None


def iter_dicom_files(root: Path) -> list[Path]:
    files: list[Path] = []
    if not root.exists():
        return files
    root = Path(root)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if is_dicom_upload(rel):
            files.append(path)
    return sorted(files)


def _safe_join(root: Path, relative: Path) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise ConvertError("压缩包路径不合法。")
    return candidate


def _link_or_copy(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    try:
        os.link(source, dest)
    except OSError:
        shutil.copy2(source, dest)


def stage_dicom_files(source: Path, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in iter_dicom_files(source):
        series = path.parent.name if SAFE_TOKEN.fullmatch(path.parent.name) else f"ser_{count}"
        name = path.name if SAFE_TOKEN.fullmatch(path.name) else f"{count}.dcm"
        _link_or_copy(path, dest / series / name)
        count += 1
    return count


def extract_dicom_zip(archive: Path, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    try:
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir() or info.filename.endswith("/"):
                    continue
                posix = str(info.filename or "").replace("\\", "/")
                rel = Path(posix)
                if ".." in rel.parts or rel.is_absolute() or posix.startswith("/"):
                    raise ConvertError("压缩包路径不合法。")
                if not is_dicom_upload(posix):
                    continue
                series = rel.parent.name if SAFE_TOKEN.fullmatch(rel.parent.name or "") else f"ser_{count}"
                name = rel.name if SAFE_TOKEN.fullmatch(rel.name) else f"{count}.dcm"
                target = _safe_join(dest, Path(series) / name)
                if info.file_size > 2 * 1024 ** 3:
                    raise ConvertError("压缩包内单个文件过大。")
                target.parent.mkdir(parents=True, exist_ok=True)
                copied = 0
                with zf.open(info, "r") as src, target.open("wb") as out:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        copied += len(chunk)
                        if copied > info.file_size + 64 * 1024:
                            raise ConvertError("压缩包内文件超出声明大小。")
                        out.write(chunk)
                count += 1
    except zipfile.BadZipFile as exc:
        raise ConvertError("不是有效的 zip 文件。") from exc
    return count


def _series_label(sidecar: dict[str, Any], filename: str) -> str:
    desc = str(sidecar.get("SeriesDescription") or sidecar.get("ProtocolName") or "").strip()
    number = sidecar.get("SeriesNumber")
    if desc and number is not None:
        return f"{desc}（序列 {number}）"
    if desc:
        return desc
    return filename


def run_dcm2niix(dicom_dir: Path, out_dir: Path, binary: str) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [binary, "-z", "y", "-ba", "y", "-f", "%p_%s", "-o", str(out_dir), str(dicom_dir)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    log = (result.stdout or "") + (result.stderr or "")
    produced = list(out_dir.glob("*.nii.gz"))
    if result.returncode not in {0, 1} or not produced:
        detail = log.strip() or f"exit {result.returncode}"
        raise ConvertError(f"dcm2niix 未能转换 DICOM：{detail[:500]}")
    return log


def _cleanup(*paths: Path) -> None:
    for path in paths:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file():
            path.unlink(missing_ok=True)


def convert_staged_dicom(dicom_dir: Path, output_dir: Path, *, dcm2niix: str | None = None) -> dict[str, Any]:
    binary = dcm2niix or os.environ.get("AUTORECON_DCM2NIIX") or shutil.which("dcm2niix")
    if not binary:
        raise ConvertError("未找到 dcm2niix，请安装后再上传 DICOM。")
    output_dir.mkdir(parents=True, exist_ok=True)
    nii_scratch = output_dir / ".dicom_nii"
    _cleanup(nii_scratch)
    nii_scratch.mkdir(parents=True, exist_ok=True)
    try:
        run_dcm2niix(dicom_dir, nii_scratch, str(binary))
        volumes = [_volume_record(path) for path in sorted(nii_scratch.glob("*.nii.gz"))]
        return _finalize_kept(output_dir, select_richest_family(volumes))
    finally:
        _cleanup(nii_scratch)


def convert_dicom_dir(dicom_dir: Path, output_dir: Path, *, dcm2niix: str | None = None) -> dict[str, Any]:
    output_dir = Path(output_dir)
    staged = output_dir / ".dicom_in"
    _cleanup(staged)
    try:
        count = stage_dicom_files(Path(dicom_dir), staged)
        if count <= 0:
            raise ConvertError("目录中没有可用的 DICOM 文件。")
        return convert_staged_dicom(staged, output_dir, dcm2niix=dcm2niix)
    finally:
        _cleanup(staged)


def convert_dicom_zip(archive: Path, output_dir: Path, *, dcm2niix: str | None = None) -> dict[str, Any]:
    output_dir = Path(output_dir)
    staged = output_dir / ".dicom_in"
    _cleanup(staged)
    try:
        count = extract_dicom_zip(Path(archive), staged)
        if count <= 0:
            raise ConvertError("压缩包中没有可用的 DICOM 文件。")
        return convert_staged_dicom(staged, output_dir, dcm2niix=dcm2niix)
    finally:
        _cleanup(staged)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert DICOM zip/folder to 3D NIfTI stacks")
    parser.add_argument("input", help="DICOM zip or folder")
    parser.add_argument("-o", "--output", required=True, help="Output directory")
    args = parser.parse_args()
    source = Path(args.input)
    dest = Path(args.output)
    try:
        if source.is_file() and source.suffix.lower() == ".zip":
            report = convert_dicom_zip(source, dest)
        elif source.is_dir():
            report = convert_dicom_dir(source, dest)
        else:
            raise ConvertError("请提供 DICOM 文件夹或 .zip。")
    except ConvertError as exc:
        print(str(exc), flush=True)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

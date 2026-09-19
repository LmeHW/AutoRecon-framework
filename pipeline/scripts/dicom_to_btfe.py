#!/usr/bin/env python3
"""Convert a DICOM zip or folder to BTFE_*.nii.gz stacks with dcm2niix."""

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


MAX_STACKS = 20
MAX_DICOM_FILES = 20000
SKIP_DIR = re.compile(r"^(Viewer|DICOMDIR|.+_JPG)$", re.I)
JUNK_FILE = re.compile(
    r"^(DICOMDIR|Thumbs\.db|desktop\.ini|StudyInfo\.dat)$|\.(jpg|jpeg|png|gif|bmp|pdf|exe|txt|dat|xlsx|xls|doc|docx|json)$",
    re.I,
)
EXCLUDE_SERIES = re.compile(
    r"SURVEY|SCOUT|LOCALIZER|T1W|DWI|DADC|\bADC\b|FLAIR|\bSWI\b|SSh_TSE|T2W_TSE|ssfse",
    re.I,
)
BTFE_NAME = re.compile(r"^BTFE(?:$|[_ \-])", re.I)
PULSE_BTFE = re.compile(r"^B-TFE$", re.I)
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.-]+$")
SERIES_IN_NAME = re.compile(r"_(\d+)\.nii\.gz$", re.I)
UNSAFE_PATH_CHAR = re.compile(r'[\x00-\x1f<>:"|?*]')


class ConvertError(ValueError):
    """Raised when DICOM conversion or BTFE filtering fails."""


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


def normalize_uploaded_niftis(directory: Path) -> list[str]:
    import gzip as gzip_mod

    niftis = [
        path
        for path in sorted(directory.rglob("*"))
        if path.is_file() and is_nifti_upload(path.name) and path.name != ".upload.json"
    ]
    if not niftis:
        raise ConvertError("没有可用的 NIfTI 文件。")
    if len(niftis) > MAX_STACKS:
        raise ConvertError(f"NIfTI 超过 {MAX_STACKS} 个。")
    staged: list[Path] = []
    for index, path in enumerate(niftis, start=1):
        temp = directory / f".incoming_{index:02d}.nii.gz"
        if path.name.lower().endswith(".nii") and not path.name.lower().endswith(".nii.gz"):
            temp.write_bytes(gzip_mod.compress(path.read_bytes()))
            path.unlink(missing_ok=True)
        elif path.resolve() != temp.resolve():
            shutil.move(str(path), temp)
        staged.append(temp)
    names: list[str] = []
    for index, temp in enumerate(staged, start=1):
        name = f"BTFE_{index:02d}.nii.gz"
        dest = directory / name
        if dest.exists() and dest.resolve() != temp.resolve():
            dest.unlink()
        if temp.resolve() != dest.resolve():
            shutil.move(str(temp), dest)
        names.append(name)
    return names


def clear_non_btfe_outputs(directory: Path) -> None:
    keep = {".upload.json"}
    for path in list(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.name in keep or re.fullmatch(r"BTFE_\d+\.nii\.gz", path.name, re.I):
            continue
        path.unlink(missing_ok=True)
    for path in sorted(directory.rglob("*"), reverse=True):
        if path.is_dir() and path != directory and not any(path.iterdir()):
            path.rmdir()


def is_btfe_series(sidecar: dict[str, Any] | None = None, filename: str = "") -> bool:
    sidecar = sidecar or {}
    tokens = [
        str(sidecar.get("SeriesDescription") or ""),
        str(sidecar.get("ProtocolName") or ""),
        Path(filename).name,
    ]
    pulse = str(sidecar.get("PulseSequenceName") or "").strip()
    if any(EXCLUDE_SERIES.search(token or "") for token in (*tokens, pulse)):
        return False
    if any(BTFE_NAME.search((token or "").strip()) for token in tokens):
        return True
    return bool(PULSE_BTFE.fullmatch(pulse))


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


def _load_sidecar(nifti: Path) -> dict[str, Any]:
    sidecar = nifti.with_suffix("").with_suffix(".json")
    if not sidecar.is_file():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


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
        volumes = sorted(nii_scratch.glob("*.nii.gz"))
        kept: list[dict[str, Any]] = []
        dropped: list[str] = []
        for path in volumes:
            sidecar = _load_sidecar(path)
            label = _series_label(sidecar, path.name)
            if is_btfe_series(sidecar, path.name):
                number = sidecar.get("SeriesNumber")
                try:
                    series_number = int(number) if number is not None else series_number_from_name(path.name)
                except (TypeError, ValueError):
                    series_number = series_number_from_name(path.name)
                kept.append({"path": path, "label": label, "series_number": series_number, "description": label})
            else:
                dropped.append(label)
        if not kept:
            listed = "、".join(dropped) or "（没有可读序列）"
            raise ConvertError(f"未找到 BTFE 序列。dcm2niix 产出：{listed}")
        if len(kept) > MAX_STACKS:
            raise ConvertError(f"BTFE 序列超过 {MAX_STACKS} 个（{len(kept)}），请只导出胎儿脑 BTFE 再上传。")
        kept.sort(key=lambda item: (item["series_number"] is None, item["series_number"] or 0, item["path"].name))
        names: list[str] = []
        series: list[dict[str, Any]] = []
        for index, item in enumerate(kept, start=1):
            name = f"BTFE_{index:02d}.nii.gz"
            target = output_dir / name
            if target.exists():
                target.unlink()
            shutil.move(str(item["path"]), target)
            names.append(name)
            series.append({
                "name": name,
                "series_number": item["series_number"],
                "description": item["label"],
            })
        return {"ok": True, "btfe": names, "series": series, "dropped": dropped}
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
    parser = argparse.ArgumentParser(description="Convert DICOM zip/folder to BTFE_*.nii.gz")
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

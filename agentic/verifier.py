from __future__ import annotations

import gzip
import struct
from pathlib import Path


ERROR_PATTERNS = ("Traceback", "RuntimeError", "Error:", "ERROR", "failed", "No such file")


def _read_header(path: Path) -> bytes:
    if path.name.endswith(".gz"):
        with gzip.open(path, "rb") as handle:
            return handle.read(352)
    with path.open("rb") as handle:
        return handle.read(352)


def verify_nifti(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing file: {path}"
    try:
        header = _read_header(path)
    except Exception as exc:
        return False, f"cannot read NIfTI header: {exc}"
    if len(header) < 348:
        return False, "header too short"
    sizeof_hdr = struct.unpack("<i", header[:4])[0]
    if sizeof_hdr != 348:
        sizeof_hdr = struct.unpack(">i", header[:4])[0]
    if sizeof_hdr != 348:
        return False, "invalid sizeof_hdr"
    magic = header[344:348]
    if magic not in (b"n+1\x00", b"ni1\x00", b"n+2\x00"):
        return False, "invalid NIfTI magic"
    dims = struct.unpack("<8h", header[40:56])
    if dims[0] < 2 or any(v <= 0 for v in dims[1 : dims[0] + 1]):
        return False, f"invalid dimensions: {dims}"
    return True, f"valid NIfTI dims={dims[1 : dims[0] + 1]}"


def verify_path(path: str | Path, expect: str = "file") -> tuple[bool, str]:
    candidate = Path(path)
    if expect == "dir":
        return (candidate.is_dir(), f"directory {'exists' if candidate.is_dir() else 'missing'}: {candidate}")
    if candidate.suffix == ".gz" or candidate.name.endswith(".nii"):
        return verify_nifti(candidate)
    return (candidate.is_file(), f"file {'exists' if candidate.is_file() else 'missing'}: {candidate}")


def log_has_error(path: str | Path | None) -> tuple[bool, str]:
    if not path:
        return False, "no log"
    log_path = Path(path)
    if not log_path.exists():
        return False, f"log missing: {log_path}"
    tail = log_path.read_text(encoding="utf-8", errors="ignore")[-20000:]
    for pattern in ERROR_PATTERNS:
        if pattern in tail:
            return True, f"log contains error pattern: {pattern}"
    return False, "no known error pattern"


def verify_outputs(outputs: dict) -> tuple[bool, list[str]]:
    checks: list[str] = []
    ok = True
    for key, value in outputs.items():
        if not value or key.endswith("_url"):
            continue
        if key.endswith("_dir") or key.endswith("_root"):
            item_ok, message = verify_path(value, "dir")
        elif key.endswith("_image") or str(value).endswith((".nii", ".nii.gz")):
            item_ok, message = verify_path(value, "file")
        else:
            path = Path(str(value))
            if path.exists():
                item_ok, message = verify_path(path, "dir" if path.is_dir() else "file")
            else:
                continue
        checks.append(f"{key}: {message}")
        ok = ok and item_ok
    return ok, checks

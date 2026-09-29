#!/usr/bin/env python3
"""Record and validate reusable 2D extraction outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Sequence

import nibabel as nib
import numpy as np


CONFIG_VERSION = 1


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def source_records(source_dir: Path) -> list[dict[str, object]]:
    images = sorted(path for path in source_dir.glob("*.nii.gz") if "crop" not in path.name.lower())
    if not images:
        raise RuntimeError(f"No .nii.gz inputs found in {source_dir}")
    return [
        {"name": path.name, "size_bytes": path.stat().st_size, "sha256": digest(path)}
        for path in images
    ]


def container_sha(runtime_root: Path) -> str:
    manifest_path = runtime_root / "manifests/containers.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    value = manifest["containers"]["extraction_nnunet"].get("sha256")
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Extraction container SHA256 is missing in {manifest_path}")
    return value


def validate_products(source_dir: Path, staging_dir: Path) -> list[dict[str, object]]:
    records = source_records(source_dir)
    for record in records:
        name = str(record["name"])
        source = source_dir / name
        staged = staging_dir / name
        mask = staging_dir / "seg" / name
        if not staged.is_file() or digest(staged) != record["sha256"]:
            raise RuntimeError(f"Staged input is missing or differs from source: {staged}")
        if not mask.is_file() or mask.stat().st_size == 0:
            raise RuntimeError(f"Extraction mask is missing or empty: {mask}")
        image_nii = nib.load(str(source))
        mask_nii = nib.load(str(mask))
        if image_nii.shape != mask_nii.shape:
            raise RuntimeError(f"Extraction image/mask shape mismatch: {source} vs {mask}")
        if not np.allclose(image_nii.affine, mask_nii.affine, rtol=1e-5, atol=1e-4):
            raise RuntimeError(f"Extraction image/mask affine mismatch: {source} vs {mask}")
        data = np.asarray(mask_nii.dataobj)
        if not np.isfinite(data).all() or not np.any(data != 0):
            raise RuntimeError(f"Extraction mask is empty or non-finite: {mask}")
    return records


def state_payload(source_dir: Path, staging_dir: Path, runtime_root: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "config_version": CONFIG_VERSION,
        "container_sha256": container_sha(runtime_root),
        "inputs": validate_products(source_dir, staging_dir),
    }


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run(args: argparse.Namespace) -> int:
    expected = state_payload(args.source_dir.resolve(), args.staging_dir.resolve(), args.runtime_root.resolve())
    if args.command == "record":
        write_json(args.state, expected)
        return 0
    if not args.state.is_file():
        raise RuntimeError(f"Extraction state is missing: {args.state}")
    actual = json.loads(args.state.read_text(encoding="utf-8"))
    if actual != expected:
        raise RuntimeError("Extraction state does not match current inputs, products, or container")
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("record", "validate"))
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

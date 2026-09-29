from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
from typing import Sequence

import nibabel as nib
import numpy as np


BACKENDS = ("frost", "nesvor", "autosvrtk", "niftymic")
AUTOSVRTK_NATIVE_OUTPUT = "reo-SVR-output.nii.gz"
AUTOSVRTK_MASK_DILATION_MM = 10.0
BACKEND_CONFIG_VERSION = 1


def _runtime_root(project_root: Path) -> Path:
    return Path(os.environ.get("AUTORECON_RUNTIME_ROOT", project_root / ".runtime")).resolve()


def _apptainer_bin() -> Path:
    configured = os.environ.get("APPTAINER_BIN")
    candidates = [
        Path(configured) if configured else None,
        Path(shutil.which("apptainer")) if shutil.which("apptainer") else None,
        Path("/mnt/sda/huangwei/conda_envs/apptainer/bin/apptainer"),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise RuntimeError("Apptainer is unavailable; set APPTAINER_BIN to an executable")


def collect_inputs(subject_dir: Path, require_masks: bool) -> tuple[list[Path], list[Path]]:
    images = sorted(path for path in subject_dir.glob("*.nii.gz") if "crop" not in path.name.lower())
    if not images:
        raise RuntimeError(f"No .nii.gz stacks found in {subject_dir}")
    masks = [subject_dir / "seg" / image.name for image in images]
    if require_masks:
        missing = [path for path in masks if not path.is_file()]
        if missing:
            raise RuntimeError("Missing masks: " + ", ".join(str(path) for path in missing))
        for image, mask in zip(images, masks, strict=True):
            image_nii = nib.load(str(image))
            mask_nii = nib.load(str(mask))
            if image_nii.shape != mask_nii.shape:
                raise RuntimeError(f"Image/mask shape mismatch: {image} vs {mask}")
            if not np.allclose(image_nii.affine, mask_nii.affine, rtol=1e-5, atol=1e-4):
                raise RuntimeError(f"Image/mask affine mismatch: {image} vs {mask}")
    return images, masks


def validate_output(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise RuntimeError(f"Reconstruction output is missing: {path}")
    image = nib.load(str(path))
    if len(image.shape) != 3 or any(size < 2 for size in image.shape):
        raise RuntimeError(f"Reconstruction must be a non-degenerate 3D image: shape={image.shape}")
    affine = np.asarray(image.affine)
    if not np.isfinite(affine).all() or abs(float(np.linalg.det(affine[:3, :3]))) < 1e-8:
        raise RuntimeError("Reconstruction has an invalid affine")
    zooms = tuple(float(value) for value in image.header.get_zooms()[:3])
    if any(not math.isfinite(value) or value <= 0 for value in zooms):
        raise RuntimeError(f"Reconstruction has invalid spacing: {zooms}")
    data = np.asarray(image.dataobj)
    if not np.isfinite(data).all():
        raise RuntimeError("Reconstruction contains NaN or infinite voxels")
    nonzero = int(np.count_nonzero(data))
    if nonzero == 0:
        raise RuntimeError("Reconstruction contains no non-zero voxels")
    return {
        "shape": list(image.shape),
        "spacing": list(zooms),
        "dtype": str(image.get_data_dtype()),
        "nonzero_voxels": nonzero,
        "nonzero_fraction": nonzero / int(np.prod(image.shape)),
        "intensity_min": float(data.min()),
        "intensity_max": float(data.max()),
    }


def _container_command(
    apptainer: Path,
    sif: Path,
    binds: Sequence[str],
    inner: Sequence[str],
    *,
    gpu: bool,
    writable_tmpfs: bool = False,
    working_dir: str | None = None,
) -> list[str]:
    if not sif.is_file():
        raise RuntimeError(f"Container is missing: {sif}")
    command = [str(apptainer), "exec", "--cleanenv"]
    if gpu:
        command.append("--nv")
    cuda = os.environ.get("CUDA_VISIBLE_DEVICES")
    if cuda:
        command.extend(["--env", f"CUDA_VISIBLE_DEVICES={cuda}"])
    if writable_tmpfs:
        command.append("--writable-tmpfs")
    if working_dir:
        command.extend(["--pwd", working_dir])
    for bind in binds:
        command.extend(["--bind", bind])
    command.append(str(sif))
    command.extend(inner)
    return command


def build_command(
    backend: str,
    project_root: Path,
    runtime_root: Path,
    subject_dir: Path,
    backend_dir: Path,
    scratch_dir: Path,
    images: Sequence[Path],
    masks: Sequence[Path],
) -> tuple[list[str], Path, Path | None]:
    output = backend_dir / f"{subject_dir.name}.nii.gz"
    if backend == "frost":
        apptainer = _apptainer_bin()
        sif = runtime_root / "containers/frost.sif"
        command = _container_command(
            apptainer,
            sif,
            [f"{project_root}:/project:ro", f"{subject_dir}:/input/{subject_dir.name}:rw", f"{backend_dir}:/output:rw"],
            [
                "/home/wangxiao/.conda/envs/frost/bin/python",
                "/project/pipeline/FROST/recon_all_patch.py",
                "--file_dir", f"/input/{subject_dir.name}",
                "--seg_dir", f"/input/{subject_dir.name}/seg",
                "--out_dir", "/output",
            ],
            gpu=True,
        )
        return command, output, None

    apptainer = _apptainer_bin()
    if backend == "nesvor":
        sif = runtime_root / "containers/nesvor_v0.5.0.sif"
        inner_images = [f"/input/{path.name}" for path in images]
        inner_masks = [f"/input/seg/{path.name}" for path in masks]
        command = _container_command(
            apptainer,
            sif,
            [f"{subject_dir}:/input:ro", f"{backend_dir}:/output:rw", f"{scratch_dir}:/scratch:rw"],
            [
                "nesvor", "reconstruct",
                "--input-stacks", *inner_images,
                "--stack-masks", *inner_masks,
                "--output-volume", f"/output/{output.name}",
                "--output-resolution", "0.8",
                "--registration", "svort",
                "--svort-version", "v2",
                "--device", "0",
            ],
            gpu=True,
        )
        return command, output, None

    if backend == "niftymic":
        sif = runtime_root / "containers/niftymic.sif"
        inner_images = [f"/input/{path.name}" for path in images]
        inner_masks = [f"/masks/{path.name}" for path in masks]
        command = _container_command(
            apptainer,
            sif,
            [
                f"{subject_dir}:/input:ro",
                f"{scratch_dir / 'binary_masks'}:/masks:ro",
                f"{backend_dir}:/output:rw",
                f"{scratch_dir}:/scratch:rw",
            ],
            [
                "niftymic_reconstruct_volume",
                "--filenames", *inner_images,
                "--filenames-masks", *inner_masks,
                "--output", f"/output/{output.name}",
                "--isotropic-resolution", "0.8",
                "--outlier-rejection", "1",
                "--intensity-correction", "1",
                "--two-step-cycles", "3",
                "--subfolder-motion-correction", "motion_correction",
            ],
            gpu=False,
        )
        return command, output, None

    if backend == "autosvrtk":
        sif = runtime_root / "containers/autosvrtk_general_auto_amd.sif"
        clean_input = scratch_dir / "raw_stacks"
        native_output_dir = scratch_dir / "native_output"
        work_dir = scratch_dir / "work"
        command = _container_command(
            apptainer,
            sif,
            [f"{clean_input}:/input:ro", f"{native_output_dir}:/output:rw", f"{work_dir}:/home/tmp_proc:rw"],
            [
                "bash", "/home/auto-proc-svrtk/scripts/auto-brain-reconstruction-2026.sh",
                "/input", "/output", "1", "3.0", "0.8", "1",
            ],
            gpu=True,
            writable_tmpfs=True,
        )
        return command, output, native_output_dir / AUTOSVRTK_NATIVE_OUTPUT

    raise ValueError(f"Unknown reconstruction backend: {backend}")


def _voxel_radii(zooms: Sequence[float], radius_mm: float) -> tuple[int, int, int]:
    values = [max(1, int(round(float(radius_mm) / max(float(zoom), 1e-6)))) for zoom in list(zooms)[:3]]
    values.extend([1] * max(0, 3 - len(values)))
    return (values[0], values[1], values[2])


def _ellipsoid(radii: Sequence[int]) -> np.ndarray:
    rx, ry, rz = (max(1, int(radius)) for radius in radii)
    ix, iy, iz = np.ogrid[-rx:rx + 1, -ry:ry + 1, -rz:rz + 1]
    return (ix / rx) ** 2 + (iy / ry) ** 2 + (iz / rz) ** 2 <= 1.0 + 1e-9


def _dilate_binary_mask(mask: np.ndarray, zooms: Sequence[float], radius_mm: float) -> np.ndarray:
    binary = np.asarray(mask) > 0
    if not binary.any():
        return binary
    radii = _voxel_radii(zooms, radius_mm)
    structure = _ellipsoid(radii)
    try:
        from scipy.ndimage import binary_dilation
    except ImportError:
        rx, ry, rz = radii
        padded = np.pad(binary, ((rx, rx), (ry, ry), (rz, rz)), mode="constant")
        dilated = np.zeros(binary.shape, dtype=bool)
        for ox, oy, oz in np.argwhere(structure):
            dilated |= padded[int(ox):int(ox) + binary.shape[0], int(oy):int(oy) + binary.shape[1], int(oz):int(oz) + binary.shape[2]]
        return dilated
    return binary_dilation(binary, structure=structure)


def _prepare_autosvrtk_input(
    images: Sequence[Path],
    masks: Sequence[Path],
    scratch_dir: Path,
    *,
    radius_mm: float = AUTOSVRTK_MASK_DILATION_MM,
) -> None:
    if len(images) != len(masks):
        raise RuntimeError("AutoSVRTK needs a matching extraction mask for every stack")
    clean_input = scratch_dir / "raw_stacks"
    native_output = scratch_dir / "native_output"
    work_dir = scratch_dir / "work"
    for path in (clean_input, native_output, work_dir):
        if path.exists():
            shutil.rmtree(path)
    clean_input.mkdir(parents=True)
    for image_path, mask_path in zip(images, masks, strict=True):
        image = nib.load(str(image_path))
        mask = nib.load(str(mask_path))
        if image.shape != mask.shape:
            raise RuntimeError(f"Image/mask shape mismatch: {image_path} vs {mask_path}")
        dilated = _dilate_binary_mask(np.asarray(mask.dataobj), mask.header.get_zooms()[:3], radius_mm)
        data = np.asarray(image.dataobj, dtype=np.float32)
        masked = nib.Nifti1Image(np.where(dilated, data, 0).astype(np.float32), image.affine, image.header)
        masked.set_data_dtype(np.float32)
        nib.save(masked, str(clean_input / image_path.name))
    native_output.mkdir(parents=True)
    work_dir.mkdir(parents=True)


def _prepare_binary_masks(masks: Sequence[Path], scratch_dir: Path) -> None:
    output_dir = scratch_dir / "binary_masks"
    output_dir.mkdir(parents=True, exist_ok=True)
    for mask in masks:
        source = nib.load(str(mask))
        data = (np.asarray(source.dataobj) > 0).astype(np.uint8)
        binary = nib.Nifti1Image(data, source.affine, source.header)
        binary.set_data_dtype(np.uint8)
        nib.save(binary, str(output_dir / mask.name))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def input_fingerprint(
    backend: str, images: Sequence[Path], masks: Sequence[Path], runtime_root: Path
) -> tuple[str, list[dict[str, object]]]:
    runtime_manifest = json.loads(
        (runtime_root / "manifests/containers.json").read_text(encoding="utf-8")
    )
    container = runtime_manifest["containers"][backend]
    records: list[dict[str, object]] = []
    for role, paths in (("image", images), ("mask", masks)):
        for index, path in enumerate(paths):
            records.append({
                "role": role,
                "index": index,
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": _file_digest(path),
            })
    payload = {
        "backend": backend,
        "backend_config_version": BACKEND_CONFIG_VERSION,
        "container_sha256": container["sha256"],
        "files": records,
    }
    if backend == "autosvrtk":
        payload["mask_dilation_mm"] = AUTOSVRTK_MASK_DILATION_MM
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest(), records


def _run_logged(command: Sequence[str], cwd: Path, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, start_new_session=True,
        )
        try:
            assert process.stdout is not None
            for line in process.stdout:
                log.write(line)
                log.flush()
                print(line, end="", flush=True)
            return_code = process.wait()
        except BaseException:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
    if return_code:
        raise subprocess.CalledProcessError(return_code, command)


def _publish_canonical(source: Path, canonical: Path) -> None:
    canonical.parent.mkdir(parents=True, exist_ok=True)
    temporary = canonical.with_name(canonical.name + ".tmp-link")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(os.path.relpath(source, canonical.parent))
    os.replace(temporary, canonical)


def run(args: argparse.Namespace) -> int:
    project_root = args.project_root.resolve()
    subject_dir = args.subject_dir.resolve()
    runtime_root = (args.runtime_root or _runtime_root(project_root)).resolve()
    output_root = args.output_root.resolve()
    backend_dir = output_root / "reconstruction" / args.backend
    scratch_dir = args.scratch_root.resolve() / "reconstruction" / args.backend
    backend_dir.mkdir(parents=True, exist_ok=True)
    scratch_dir.mkdir(parents=True, exist_ok=True)
    lock = (backend_dir / ".run.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise RuntimeError(f"Backend {args.backend} is already running in {backend_dir}") from exc

    images, masks = collect_inputs(subject_dir, require_masks=True)
    fingerprint, input_records = input_fingerprint(args.backend, images, masks, runtime_root)
    canonical_output = Path(os.path.abspath(args.canonical_output))
    output = backend_dir / f"{subject_dir.name}.nii.gz"
    result_path = backend_dir / "result.json"
    if args.validate_existing:
        if not result_path.is_file():
            raise RuntimeError(f"Backend result is missing: {result_path}")
        existing = json.loads(result_path.read_text(encoding="utf-8"))
        if existing.get("status") != "completed" or existing.get("backend") != args.backend:
            raise RuntimeError("Existing result is not completed for the requested backend")
        if existing.get("input_fingerprint") != fingerprint:
            raise RuntimeError("Existing reconstruction fingerprint does not match current inputs/configuration")
        validate_output(output)
        # Another backend (for example, a comparison run) may have replaced
        # the canonical symlink since this result was produced.  A successful
        # resume must make the requested backend authoritative downstream.
        _publish_canonical(output, canonical_output)
        validate_output(canonical_output)
        lock.close()
        return 0
    if args.backend == "autosvrtk":
        _prepare_autosvrtk_input(images, masks, scratch_dir)
    elif args.backend == "niftymic":
        _prepare_binary_masks(masks, scratch_dir)

    command, output, native_output = build_command(
        args.backend, project_root, runtime_root, subject_dir, backend_dir, scratch_dir, images, masks
    )
    log_path = backend_dir / "backend.log"
    manifest: dict[str, object] = {
        "schema_version": 1,
        "backend": args.backend,
        "subject": subject_dir.name,
        "status": "planned" if args.dry_run else "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "inputs": [str(path) for path in images],
        "masks": [str(path) for path in masks],
        "mask_dilation_mm": AUTOSVRTK_MASK_DILATION_MM if args.backend == "autosvrtk" else None,
        "sequence_warning": "BTFE is not officially validated by this backend" if args.backend != "frost" else None,
        "command": command,
        "output": str(output),
        "log": str(log_path),
        "input_fingerprint": fingerprint,
        "input_records": input_records,
        "backend_config_version": BACKEND_CONFIG_VERSION,
    }
    _write_json(result_path, manifest)
    if args.dry_run:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        lock.close()
        return 0

    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(InterruptedError(f"signal {signum}")))
    try:
        _run_logged(
            command,
            project_root / "pipeline/FROST" if args.backend == "frost" else project_root,
            log_path,
        )
        if native_output is not None:
            if not native_output.is_file():
                raise RuntimeError(f"Expected AutoSVRTK output is missing: {native_output}")
            shutil.copy2(native_output, output)
        output.chmod(0o664)
        qc = validate_output(output)
        _publish_canonical(output, canonical_output)
        manifest.update({
            "status": "completed",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "qc": qc,
            "canonical_output": str(canonical_output),
            "output_sha256": _file_digest(output),
            "canonical_sha256": _file_digest(canonical_output),
        })
        _write_json(result_path, manifest)
        print(f"Reconstruction backend {args.backend} completed: {output}")
        return 0
    except BaseException as exc:
        error_message = str(exc) or exc.__class__.__name__
        manifest.update({
            "status": "failed",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error": error_message,
            "error_type": exc.__class__.__name__,
        })
        _write_json(result_path, manifest)
        raise
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        lock.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one validated AutoRecon reconstruction backend.")
    parser.add_argument("--backend", choices=BACKENDS, required=True)
    parser.add_argument("--subject-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--canonical-output", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-existing", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

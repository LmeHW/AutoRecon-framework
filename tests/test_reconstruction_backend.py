from __future__ import annotations

import tempfile
import unittest
import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import nibabel as nib
import numpy as np

from pipeline.reconstruction.run_backend import (
    _prepare_binary_masks,
    build_command,
    collect_inputs,
    input_fingerprint,
    run as run_backend,
    validate_output,
)
from pipeline.reconstruction.run_comparison import run as run_comparison
from scripts.verify_four_backend_acceptance import verify_backend


def write_nifti(path: Path, *, affine: np.ndarray | None = None, value: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = nib.Nifti1Image(np.full((8, 9, 10), value, dtype=np.float32), affine if affine is not None else np.eye(4))
    nib.save(image, str(path))


class ReconstructionBackendTests(unittest.TestCase):
    def test_strict_full_pipeline_acceptance_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = "frost"
            subject_name = "CaseA"
            run = root / f"full_pipeline_{backend}"
            (run / "acceptance.json").parent.mkdir(parents=True)
            (run / "acceptance.json").write_text(json.dumps({
                "status": "completed", "backend": backend, "subject": subject_name,
            }))
            (run / "pipeline_result.json").parent.mkdir(parents=True, exist_ok=True)
            (run / "pipeline_result.json").write_text(json.dumps({
                "status": "completed", "exit_code": 0,
                "reconstruction_backend": backend,
                "requested_steps": ["extraction", "reconstruction", "registration", "tissue", "roi", "surface"],
            }))
            stack = run / "staging" / subject_name / "BTFE_01.nii.gz"
            mask = run / "staging" / subject_name / "seg" / stack.name
            write_nifti(stack); write_nifti(mask)
            native = run / "outputs/reconstruction/frost/CaseA.nii.gz"
            write_nifti(native)
            result = native.parent / "result.json"
            result.write_text(json.dumps({
                "status": "completed", "input_fingerprint": "abc", "output": str(native.resolve()),
            }))
            canonical = run / "outputs/recon/CaseA.nii.gz"
            canonical.parent.mkdir(parents=True)
            canonical.symlink_to(Path("../reconstruction/frost/CaseA.nii.gz"))
            for path in (
                run / "outputs/registered_input/CaseA.nii.gz",
                run / "outputs/Tissue/CaseA.nii.gz",
                run / "outputs/ROI/CaseA.nii.gz",
            ):
                write_nifti(path)
            summary = run / "outputs/registration/summary.csv"
            summary.parent.mkdir(parents=True); summary.write_text("case,status\nCaseA,ok\n")
            surface = run / "outputs/surface_subjects/CaseA/surf"
            surface.mkdir(parents=True)
            for name in (
                "lh.white", "rh.white", "lh.pial", "rh.pial", "lh.inflated", "rh.inflated",
                "lh.roi86.pial.mgh", "rh.roi86.pial.mgh",
                "lh.roi86.white.mgh", "rh.roi86.white.mgh",
            ):
                (surface / name).write_bytes(b"artifact")
            stats = surface.parent / "stats"
            stats.mkdir()
            for name in ("roi86_thicknessproxy_cortexonly.stats", "roi86_basic.stats"):
                (stats / name).write_text("metric 1\n")
            logs = run / "logs"; logs.mkdir()
            for index, step in enumerate(("extraction", "reconstruction", "registration", "tissue", "roi", "surface"), 1):
                (logs / f"{index:02d}_{step}.log").write_text("completed\n")
            self.assertEqual(verify_backend(root, backend, subject_name)["status"], "passed")

    def test_collect_inputs_pairs_sorted_stacks_and_masks(self):
        with tempfile.TemporaryDirectory() as directory:
            subject = Path(directory) / "case"
            for name in ("BTFE_02.nii.gz", "BTFE_01.nii.gz"):
                write_nifti(subject / name)
                write_nifti(subject / "seg" / name)
            images, masks = collect_inputs(subject, require_masks=True)
            self.assertEqual([path.name for path in images], ["BTFE_01.nii.gz", "BTFE_02.nii.gz"])
            self.assertEqual([path.name for path in masks], ["BTFE_01.nii.gz", "BTFE_02.nii.gz"])

    def test_collect_inputs_rejects_affine_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            subject = Path(directory) / "case"
            write_nifti(subject / "BTFE_01.nii.gz")
            shifted = np.eye(4)
            shifted[0, 3] = 2
            write_nifti(subject / "seg/BTFE_01.nii.gz", affine=shifted)
            with self.assertRaisesRegex(RuntimeError, "affine mismatch"):
                collect_inputs(subject, require_masks=True)

    def test_validate_output_rejects_empty_volume(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "empty.nii.gz"
            write_nifti(output, value=0)
            with self.assertRaisesRegex(RuntimeError, "no non-zero voxels"):
                validate_output(output)

    def test_niftymic_masks_are_binarized_without_geometry_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            affine = np.diag([0.8, 0.8, 2.0, 1.0])
            source = root / "seg/BTFE_01.nii.gz"
            write_nifti(source, affine=affine, value=255)
            _prepare_binary_masks([source], root / "scratch")
            result = nib.load(str(root / "scratch/binary_masks/BTFE_01.nii.gz"))
            self.assertEqual(set(np.unique(np.asarray(result.dataobj))), {1})
            self.assertEqual(result.get_data_dtype(), np.dtype("uint8"))
            self.assertTrue(np.allclose(result.affine, affine))

    def test_input_fingerprint_changes_with_backend_input_or_container(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "BTFE_01.nii.gz"
            mask = root / "seg/BTFE_01.nii.gz"
            write_nifti(image)
            write_nifti(mask)
            manifest = root / "runtime/manifests/containers.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"containers": {"frost": {"sha256": "container-a"}}}))
            first, records = input_fingerprint("frost", [image], [mask], root / "runtime")
            self.assertEqual([record["role"] for record in records], ["image", "mask"])
            write_nifti(mask, value=2)
            second, _ = input_fingerprint("frost", [image], [mask], root / "runtime")
            self.assertNotEqual(first, second)
            payload = json.loads(manifest.read_text())
            payload["containers"]["frost"]["sha256"] = "container-b"
            manifest.write_text(json.dumps(payload))
            third, _ = input_fingerprint("frost", [image], [mask], root / "runtime")
            self.assertNotEqual(second, third)

    def test_validate_existing_republishes_requested_backend_as_canonical(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subject = root / "subject"
            image = subject / "BTFE_01.nii.gz"
            mask = subject / "seg/BTFE_01.nii.gz"
            write_nifti(image)
            write_nifti(mask)
            runtime = root / "runtime"
            manifest = runtime / "manifests/containers.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"containers": {"frost": {"sha256": "container-a"}}}))
            fingerprint, _ = input_fingerprint("frost", [image], [mask], runtime)

            output_root = root / "outputs"
            native = output_root / "reconstruction/frost/subject.nii.gz"
            write_nifti(native, value=2)
            (native.parent / "result.json").write_text(json.dumps({
                "status": "completed", "backend": "frost", "input_fingerprint": fingerprint,
            }))
            wrong = output_root / "reconstruction/nesvor/subject.nii.gz"
            write_nifti(wrong, value=3)
            canonical = output_root / "recon/subject.nii.gz"
            canonical.parent.mkdir(parents=True)
            canonical.symlink_to(Path("../reconstruction/nesvor/subject.nii.gz"))

            args = Namespace(
                project_root=root, subject_dir=subject, runtime_root=runtime,
                output_root=output_root, scratch_root=root / "scratch", backend="frost",
                canonical_output=canonical, validate_existing=True, dry_run=False,
            )
            self.assertEqual(run_backend(args), 0)
            self.assertEqual(canonical.resolve(), native.resolve())

    def test_comparison_keeps_selected_success_when_an_alternative_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subject = root / "subject"
            subject.mkdir()

            def fake_run(command, check):
                backend = command[command.index("--backend") + 1]
                result_dir = root / "outputs/reconstruction" / backend
                result_dir.mkdir(parents=True)
                status = "completed" if backend == "frost" else "failed"
                (result_dir / "result.json").write_text(json.dumps({"status": status, "output": "x"}))
                return Namespace(returncode=0 if status == "completed" else 1)

            args = Namespace(
                selected="frost", backends=["nesvor", "frost"], subject_dir=subject,
                output_root=root / "outputs", scratch_root=root / "scratch",
                canonical_output=root / "outputs/recon/subject.nii.gz",
                project_root=root, runtime_root=None,
            )
            with patch("pipeline.reconstruction.run_comparison.subprocess.run", side_effect=fake_run):
                self.assertEqual(run_comparison(args), 0)
            summary = json.loads((root / "outputs/reconstruction/comparison.json").read_text())
            self.assertEqual(summary["requested_backends"], ["frost", "nesvor"])
            self.assertEqual(summary["status"], "partial")

    @patch("pipeline.reconstruction.run_backend._apptainer_bin", return_value=Path("/usr/bin/apptainer"))
    def test_frost_uses_shared_container_and_preserves_subject_name(self, _):
        root = Path("/project")
        subject = Path("/data/CaseA")
        with patch.object(Path, "is_file", return_value=True):
            command, output, native = build_command(
                "frost", root, root / ".runtime", subject, root / "out", root / "scratch", [], []
            )
        self.assertIn(str(root / ".runtime/containers/frost.sif"), command)
        self.assertIn("/input/CaseA", command)
        self.assertIn("/input/CaseA/seg", command)
        self.assertEqual(output, root / "out/CaseA.nii.gz")
        self.assertIsNone(native)

    @patch("pipeline.reconstruction.run_backend._apptainer_bin", return_value=Path("/usr/bin/apptainer"))
    def test_nesvor_command_uses_matching_external_masks(self, _):
        root = Path("/project")
        subject = Path("/data/case")
        images = [subject / "BTFE_01.nii.gz", subject / "BTFE_02.nii.gz"]
        masks = [subject / "seg" / path.name for path in images]
        with patch.object(Path, "is_file", return_value=True):
            command, output, native = build_command(
                "nesvor", root, root / ".runtime", subject, root / "out", root / "scratch", images, masks
            )
        self.assertIn("--stack-masks", command)
        self.assertNotIn("--output-json", command)
        self.assertIn("/input/seg/BTFE_01.nii.gz", command)
        self.assertEqual(output, root / "out/case.nii.gz")
        self.assertIsNone(native)

    @patch("pipeline.reconstruction.run_backend._apptainer_bin", return_value=Path("/usr/bin/apptainer"))
    def test_autosvrtk_uses_exact_native_output_contract(self, _):
        root = Path("/project")
        subject = Path("/data/case")
        images = [subject / "BTFE_01.nii.gz"]
        with patch.object(Path, "is_file", return_value=True):
            command, output, native = build_command(
                "autosvrtk", root, root / ".runtime", subject, root / "out", root / "scratch", images, []
            )
        self.assertIn("--writable-tmpfs", command)
        self.assertTrue(any(value.endswith(":/home/tmp_proc:rw") for value in command))
        self.assertEqual(native, root / "scratch/native_output/reo-SVR-output.nii.gz")
        self.assertEqual(output, root / "out/case.nii.gz")


if __name__ == "__main__":
    unittest.main()

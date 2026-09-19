from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import nibabel as nib
import numpy as np

from agentic.qc import evaluate_run, gate_decision, metric


XUJING_ROOT = Path("/mnt/sda/huangwei/projects/AutoRecon/validation_results/current/real_pipeline/XuJing")
REPO = Path(__file__).resolve().parents[1]


def save_nifti(path: Path, data: np.ndarray, affine: np.ndarray | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data, np.eye(4) if affine is None else affine), str(path))


def write_mask_fraction(path: Path, shape: tuple[int, int, int], fraction: float, affine: np.ndarray | None = None) -> None:
    data = np.zeros(shape, dtype=np.uint8)
    n = max(1, int(round(data.size * fraction)))
    data.reshape(-1)[:n] = 1
    save_nifti(path, data, affine)


class QcL0Tests(unittest.TestCase):
    def _base_case(self, root: Path, subject: str = "Demo", mask_fraction: float = 0.029) -> Path:
        affine = np.eye(4)
        image = np.ones((10, 10, 10), dtype=np.float32)
        save_nifti(root / "staging" / subject / "BTFE_demo.nii.gz", image, affine)
        write_mask_fraction(root / "staging" / subject / "seg" / "BTFE_demo.nii.gz", (10, 10, 10), mask_fraction, affine)
        save_nifti(root / "outputs" / "recon" / f"{subject}.nii.gz", image, affine)
        save_nifti(root / "outputs" / "registered_input" / f"{subject}.nii.gz", image, affine)
        labels = np.zeros((10, 10, 10), dtype=np.uint8)
        labels[:4, :4, :4] = 1
        save_nifti(root / "outputs" / "Tissue" / f"{subject}.nii.gz", labels, affine)
        save_nifti(root / "outputs" / "ROI" / f"{subject}.nii.gz", labels, affine)
        registration = root / "outputs" / "registration"
        registration.mkdir(parents=True)
        (registration / "summary.csv").write_text(
            "mattes_lower_is_better,gc_lower_is_better,warped\n-0.30,-0.50,"
            + str(root / "outputs" / "registered_input" / f"{subject}.nii.gz")
            + "\n",
            encoding="utf-8",
        )
        surface = root / "outputs" / "surface_subjects" / subject
        for name in ("lh.white", "rh.white", "lh.pial", "rh.pial", "lh.inflated", "rh.inflated"):
            path = surface / "surf" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
        for name in ("roi86_basic.stats", "roi86_thicknessproxy_cortexonly.stats"):
            path = surface / "stats" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("ok\n", encoding="utf-8")
        return root

    def test_xujing_mask_fraction_is_l1_pass_and_does_not_block_reconstruction(self):
        self.assertTrue(XUJING_ROOT.is_dir(), "XuJing real_pipeline run is missing")
        qc = evaluate_run(XUJING_ROOT, "XuJing")
        extraction = next(item for item in qc["steps"] if item["step_id"] == "extraction")
        fraction = next(item for item in extraction["metrics"] if item["name"] == "median_foreground_fraction")
        self.assertAlmostEqual(float(fraction["value"]), 0.029228, places=5)
        self.assertEqual(fraction["status"], "pass")
        self.assertEqual(fraction["contract_level"], "l1")
        self.assertEqual(extraction["contract_status"], "pass")
        decision = gate_decision(qc, next_step="reconstruction")
        self.assertTrue(decision["allowed"])
        recon = XUJING_ROOT / "outputs" / "recon" / "XuJing.nii.gz"
        self.assertTrue(recon.is_file())

    def test_tiny_mask_is_l1_review_but_reconstruction_still_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._base_case(Path(directory), mask_fraction=0.001)
            qc = evaluate_run(root, "Demo")
            extraction = next(item for item in qc["steps"] if item["step_id"] == "extraction")
            fraction = next(item for item in extraction["metrics"] if item["name"] == "median_foreground_fraction")
            self.assertEqual(fraction["status"], "review")
            self.assertEqual(extraction["contract_status"], "review")
            self.assertTrue(gate_decision(qc, next_step="reconstruction")["allowed"])

    def test_missing_mask_is_l0_and_blocks_reconstruction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._base_case(Path(directory))
            (root / "staging" / "Demo" / "seg" / "BTFE_demo.nii.gz").unlink()
            qc = evaluate_run(root, "Demo")
            extraction = next(item for item in qc["steps"] if item["step_id"] == "extraction")
            self.assertEqual(extraction["contract_status"], "fail")
            decision = gate_decision(qc, next_step="reconstruction")
            self.assertFalse(decision["allowed"])
            self.assertEqual(decision["blocked_by"], "extraction")

    def test_nan_reconstruction_blocks_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._base_case(Path(directory))
            data = np.ones((10, 10, 10), dtype=np.float32)
            data[:5] = np.nan
            save_nifti(root / "outputs" / "recon" / "Demo.nii.gz", data)
            qc = evaluate_run(root, "Demo")
            recon = next(item for item in qc["steps"] if item["step_id"] == "reconstruction")
            self.assertEqual(recon["contract_status"], "fail")
            decision = gate_decision(qc, next_step="registration")
            self.assertFalse(decision["allowed"])
            self.assertEqual(decision["blocked_by"], "reconstruction")

    def test_geometry_mismatch_fails_tissue_l0(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._base_case(Path(directory))
            shifted = np.eye(4)
            shifted[0, 3] = 12
            labels = np.zeros((10, 10, 10), dtype=np.uint8)
            labels[:4, :4, :4] = 1
            save_nifti(root / "outputs" / "Tissue" / "Demo.nii.gz", labels, shifted)
            qc = evaluate_run(root, "Demo")
            tissue = next(item for item in qc["steps"] if item["step_id"] == "tissue")
            self.assertEqual(tissue["contract_status"], "fail")
            geom = next(item for item in tissue["metrics"] if item["name"] == "registered_geometry_match")
            self.assertEqual(geom["status"], "fail")
            self.assertFalse(gate_decision(qc, enforce_step="tissue")["allowed"])

    def test_roi_geometry_mismatch_blocks_surface(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._base_case(Path(directory))
            shifted = np.eye(4)
            shifted[0, 3] = 12
            labels = np.zeros((10, 10, 10), dtype=np.uint8)
            labels[:4, :4, :4] = 1
            save_nifti(root / "outputs" / "ROI" / "Demo.nii.gz", labels, shifted)
            qc = evaluate_run(root, "Demo")
            decision = gate_decision(qc, next_step="surface")
            self.assertFalse(decision["allowed"])
            self.assertEqual(decision["blocked_by"], "roi")

    def test_swapped_input_fingerprint_blocks_reconstruction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._base_case(Path(directory))
            staged = root / "staging" / "Demo" / "BTFE_demo.nii.gz"
            state = root / "staging" / "Demo" / "seg" / "extraction_state.json"
            state.write_text(json.dumps({
                "schema_version": 1,
                "inputs": [{"name": "BTFE_demo.nii.gz", "sha256": "deadbeef", "size_bytes": 1}],
            }), encoding="utf-8")
            self.assertTrue(staged.is_file())
            qc = evaluate_run(root, "Demo")
            extraction = next(item for item in qc["steps"] if item["step_id"] == "extraction")
            fingerprint = next(item for item in extraction["metrics"] if item["name"] == "source_fingerprint_match")
            self.assertEqual(fingerprint["status"], "fail")
            self.assertFalse(gate_decision(qc, next_step="reconstruction")["allowed"])

    def test_swapped_recon_output_fingerprint_blocks_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._base_case(Path(directory))
            recon = root / "outputs" / "recon" / "Demo.nii.gz"
            result = root / "outputs" / "reconstruction" / "frost" / "result.json"
            result.parent.mkdir(parents=True)
            result.write_text(json.dumps({
                "status": "completed",
                "output_sha256": "0" * 64,
            }), encoding="utf-8")
            self.assertTrue(recon.is_file())
            qc = evaluate_run(root, "Demo")
            decision = gate_decision(qc, next_step="registration")
            self.assertFalse(decision["allowed"])
            self.assertEqual(decision["blocked_by"], "reconstruction")

    def test_cli_gate_next_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._base_case(Path(directory))
            (root / "staging" / "Demo" / "seg" / "BTFE_demo.nii.gz").unlink()
            proc = subprocess.run(
                [
                    sys.executable, str(REPO / "agentic" / "qc.py"),
                    "--work-root", str(root), "--subject", "Demo",
                    "--gate-next", "reconstruction",
                ],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("L0", proc.stdout)

    def test_metric_helper_defaults_to_l1(self):
        item = metric("x", "x", 1, "n", "=", "pass", "src")
        self.assertEqual(item["contract_level"], "l1")


if __name__ == "__main__":
    unittest.main()

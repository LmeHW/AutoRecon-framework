"""The tissue container must see nnUNetTrainer_BS5 after the extra bind."""
from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIF = ROOT / ".runtime/containers/tissue_nnunet.sif"
NNUNET = ROOT.parent / "nnUNet"
TRAINER = NNUNET / "nnunetv2/training/nnUNetTrainer/variants/nnUNetTrainer_BS5.py"
APPTAINER = Path("/mnt/sda/huangwei/conda_envs/apptainer/bin/apptainer")


def _apptainer() -> str | None:
    if APPTAINER.is_file() and os.access(APPTAINER, os.X_OK):
        return str(APPTAINER)
    return shutil.which("apptainer")


class TissueNnUNetTrainerTests(unittest.TestCase):
    def test_trainer_file_exists_next_to_repo(self):
        self.assertTrue(TRAINER.is_file(), f"missing {TRAINER}")

    @unittest.skipUnless(SIF.is_file() and TRAINER.is_file() and _apptainer(), "tissue SIF or nnUNet tree unavailable")
    def test_container_finds_bs5_trainer_with_bind(self):
        script = r"""
import nnunetv2
from nnunetv2.utilities.find_class_by_name import recursive_find_python_class
from batchgenerators.utilities.file_and_folder_operations import join
cls = recursive_find_python_class(
    join(nnunetv2.__path__[0], "training", "nnUNetTrainer"),
    "nnUNetTrainer_BS5",
    "nnunetv2.training.nnUNetTrainer",
)
print(nnunetv2.__file__)
print(cls)
raise SystemExit(0 if cls is not None else 1)
"""
        env = {key: value for key, value in os.environ.items() if key not in {
            "PYTHONPATH", "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
        }}
        result = subprocess.run(
            [
                _apptainer(), "exec", "--cleanenv",
                "--bind", f"{ROOT}:{ROOT}:ro",
                "--bind", f"{NNUNET}:{NNUNET}:ro",
                str(SIF),
                "env", f"PYTHONPATH={NNUNET}",
                "/home/zhaojunyang/.conda/envs/zjy/bin/python", "-c", script,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:] + result.stdout[-2000:])
        self.assertIn("nnUNetTrainer_BS5", result.stdout)


if __name__ == "__main__":
    unittest.main()

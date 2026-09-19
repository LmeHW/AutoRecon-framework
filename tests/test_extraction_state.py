from __future__ import annotations

from argparse import Namespace
import json
from pathlib import Path
import tempfile
import unittest

import nibabel as nib
import numpy as np

from pipeline.extraction_state import run


def write_volume(path: Path, value: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.full((6, 7, 8), value, dtype=np.float32), np.eye(4)), str(path))


class ExtractionStateTests(unittest.TestCase):
    def test_state_rejects_changed_source_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            staging = root / "staging"
            name = "BTFE_01.nii.gz"
            write_volume(source / name)
            write_volume(staging / name)
            write_volume(staging / "seg" / name)
            runtime = root / "runtime"
            manifest = runtime / "manifests/containers.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({
                "containers": {"extraction_nnunet": {"sha256": "container-a"}}
            }))
            state = staging / "seg/extraction_state.json"
            common = dict(source_dir=source, staging_dir=staging, runtime_root=runtime, state=state)
            self.assertEqual(run(Namespace(command="record", **common)), 0)
            self.assertEqual(run(Namespace(command="validate", **common)), 0)
            write_volume(source / name, value=2)
            with self.assertRaisesRegex(RuntimeError, "Staged input is missing or differs"):
                run(Namespace(command="validate", **common))


if __name__ == "__main__":
    unittest.main()

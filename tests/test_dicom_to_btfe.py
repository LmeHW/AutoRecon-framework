from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import nibabel as nib
import numpy as np

from pipeline.scripts.dicom_to_btfe import (
    ConvertError,
    allowed_upload_relpath,
    convert_dicom_dir,
    convert_dicom_zip,
    extract_dicom_zip,
    is_dicom_upload,
    is_irrelevant_upload,
    normalize_uploaded_niftis,
    series_number_from_name,
)
from pipeline.scripts.input_stacks import (
    is_junk_series,
    modality_family,
    select_richest_family,
)


def _write_volume(path: Path, sidecar: dict, shape=(4, 4, 6)) -> None:
    nib.save(nib.Nifti1Image(np.zeros(shape, dtype=np.uint8), np.eye(4)), str(path))
    path.with_suffix("").with_suffix(".json").write_text(json.dumps(sidecar), encoding="utf-8")


class DicomToBtfeTests(unittest.TestCase):
    def test_family_and_junk_classification(self):
        self.assertEqual(modality_family(
            {"SeriesDescription": "BTFE", "ProtocolName": "BTFE", "PulseSequenceName": "B-TFE"},
            "BTFE_201.nii.gz",
        ), "ssfp_btfe")
        self.assertEqual(modality_family({}, "BTFE_COR_20260315215212_301.nii.gz"), "ssfp_btfe")
        self.assertEqual(modality_family({"PulseSequenceName": "B-TFE"}, "series.nii.gz"), "ssfp_btfe")
        self.assertEqual(modality_family(
            {"SeriesDescription": "t2_haste_cor_p2", "ProtocolName": "t2_haste_cor_p2"},
            "t2_haste_cor_p2_9.nii.gz",
        ), "t2_ssfse")
        self.assertTrue(is_junk_series(
            {"SeriesDescription": "SURVEY_BFFE", "ProtocolName": "SURVEY_BFFE", "PulseSequenceName": "B-FFE"},
            "SURVEY_BFFE_101.nii.gz",
        ))
        self.assertEqual(modality_family(
            {"SeriesDescription": "eeT1W_TFE", "ProtocolName": "eeT1W_TFE", "PulseSequenceName": "T1TFE"},
            "eeT1W_TFE_902.nii.gz",
        ), "t1")
        self.assertEqual(modality_family(
            {"SeriesDescription": "SSh_TSE", "ProtocolName": "SSh_TSE"},
            "SSh_TSE_601.nii.gz",
        ), "t2_ssfse")
        self.assertEqual(modality_family(
            {"SeriesDescription": "DWI_600", "ProtocolName": "DWI_600"},
            "DWI_600_1101.nii.gz",
        ), "dwi")

    def test_series_number_from_gold_names(self):
        self.assertEqual(series_number_from_name("BTFE_20250718080709_1001.nii.gz"), 1001)
        self.assertEqual(series_number_from_name("BTFE_COR_20260315215212_301.nii.gz"), 301)

    def test_extract_zip_skips_jpg_and_viewer(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("Case/2025/201/1.dcm", b"keep")
            archive.writestr("Case/2025/201_JPG/1.jpg", b"nope")
            archive.writestr("Case/Viewer/BIN/x.dcm", b"viewer")
            archive.writestr("Case/DICOMDIR", b"dir")
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / "out"
            archive_path = Path(directory) / "study.zip"
            archive_path.write_bytes(buffer.getvalue())
            count = extract_dicom_zip(archive_path, dest)
            self.assertEqual(count, 1)
            self.assertTrue((dest / "201" / "1.dcm").is_file())
            self.assertFalse(list(dest.rglob("*.jpg")))

    def test_upload_names_are_unrestricted_except_junk(self):
        self.assertEqual(allowed_upload_relpath("张三_BTFE.nii.gz"), "张三_BTFE.nii.gz")
        self.assertEqual(allowed_upload_relpath("BTFE 01.nii.gz"), "BTFE 01.nii.gz")
        self.assertEqual(allowed_upload_relpath("Study/201/1.dcm"), "Study/201/1.dcm")
        self.assertEqual(allowed_upload_relpath("Study/IM_0001"), "Study/IM_0001")
        self.assertEqual(allowed_upload_relpath("1.2.840.113619.2.55.3.1"), "1.2.840.113619.2.55.3.1")
        self.assertIsNone(allowed_upload_relpath("Case/201_JPG/1.jpg"))
        self.assertIsNone(allowed_upload_relpath("Case/Viewer/BIN/x.dcm"))
        self.assertIsNone(allowed_upload_relpath("DICOMDIR"))
        self.assertTrue(is_irrelevant_upload("preview.pdf"))
        self.assertTrue(is_dicom_upload("series/file.ima"))
        self.assertFalse(is_dicom_upload("notes.txt"))

    def test_extract_zip_keeps_extensionless_dicom(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("Case/201/IM_0001", b"keep")
            archive.writestr("Case/201_JPG/1.jpg", b"nope")
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / "out"
            archive_path = Path(directory) / "study.zip"
            archive_path.write_bytes(buffer.getvalue())
            count = extract_dicom_zip(archive_path, dest)
            self.assertEqual(count, 1)
            self.assertTrue((dest / "201" / "IM_0001").is_file())

    def test_normalize_uploaded_niftis_keeps_ascii_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "t2_haste_cor_p2_9.nii.gz").write_bytes(b"gzip-placeholder")
            names = normalize_uploaded_niftis(root)
            self.assertEqual(names, ["t2_haste_cor_p2_9.nii.gz"])
            self.assertTrue((root / "t2_haste_cor_p2_9.nii.gz").is_file())

    def test_normalize_uploaded_niftis_sanitizes_unicode_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "张三 扫描.nii.gz").write_bytes(b"gzip-placeholder")
            names = normalize_uploaded_niftis(root)
            self.assertEqual(names, ["stack_01.nii.gz"])
            self.assertTrue((root / "stack_01.nii.gz").is_file())
            self.assertFalse((root / "张三 扫描.nii.gz").exists())

    def test_select_richest_family_prefers_more_3d_stacks(self):
        volumes = [
            {"family": "t2_ssfse", "is_3d": True, "voxels": 100, "junk": False, "label": "haste1"},
            {"family": "t2_ssfse", "is_3d": True, "voxels": 100, "junk": False, "label": "haste2"},
            {"family": "t2_ssfse", "is_3d": True, "voxels": 100, "junk": False, "label": "haste3"},
            {"family": "t1", "is_3d": True, "voxels": 1000, "junk": False, "label": "t1"},
            {"family": "dwi", "is_3d": False, "voxels": 8000, "junk": False, "label": "dwi"},
            {"family": "ssfp_btfe", "is_3d": True, "voxels": 100, "junk": True, "label": "survey"},
        ]
        selected = select_richest_family(volumes)
        self.assertEqual(selected["family"], "t2_ssfse")
        self.assertEqual(len(selected["kept"]), 3)

    def test_convert_keeps_richest_family_and_drops_others(self):
        def fake_run(dicom_dir: Path, out_dir: Path, binary: str) -> str:
            _write_volume(out_dir / "BTFE_201.nii.gz", {
                "SeriesDescription": "BTFE", "ProtocolName": "BTFE",
                "PulseSequenceName": "B-TFE", "SeriesNumber": 201,
            })
            _write_volume(out_dir / "BTFE_301.nii.gz", {
                "SeriesDescription": "BTFE", "ProtocolName": "BTFE",
                "PulseSequenceName": "B-TFE", "SeriesNumber": 301,
            })
            _write_volume(out_dir / "SURVEY_BFFE_101.nii.gz", {
                "SeriesDescription": "SURVEY_BFFE", "ProtocolName": "SURVEY_BFFE",
                "SeriesNumber": 101,
            })
            _write_volume(out_dir / "eeT1W_TFE_902.nii.gz", {
                "SeriesDescription": "eeT1W_TFE", "ProtocolName": "eeT1W_TFE",
                "SeriesNumber": 902,
            })
            _write_volume(out_dir / "SSh_TSE_601.nii.gz", {
                "SeriesDescription": "SSh_TSE", "ProtocolName": "SSh_TSE",
                "SeriesNumber": 601,
            })
            _write_volume(out_dir / "DWI_600_1101.nii.gz", {
                "SeriesDescription": "DWI_600", "ProtocolName": "DWI_600",
                "SeriesNumber": 1101,
            }, shape=(4, 4, 6, 8))
            return "ok"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dicom" / "201").mkdir(parents=True)
            (root / "dicom" / "201" / "1.dcm").write_bytes(b"x")
            with patch("pipeline.scripts.dicom_to_btfe.run_dcm2niix", side_effect=fake_run):
                report = convert_dicom_dir(root / "dicom", root / "out")
            self.assertEqual(report["kept_family"], "ssfp_btfe")
            self.assertEqual(report["stacks"], ["BTFE_201.nii.gz", "BTFE_301.nii.gz"])
            self.assertEqual({item["series_number"] for item in report["series"]}, {201, 301})
            self.assertTrue(any("SURVEY" in item for item in report["dropped"]))
            self.assertTrue(any("T1" in item for item in report["dropped"]))
            self.assertTrue((root / "out" / "BTFE_201.nii.gz").is_file())
            self.assertFalse((root / "out" / "eeT1W_TFE_902.nii.gz").exists())
            self.assertFalse((root / "out" / ".dicom_in").exists())
            self.assertFalse((root / "out" / ".dicom_nii").exists())

    def test_convert_keeps_haste_when_it_is_the_only_3d_family(self):
        def fake_run(dicom_dir: Path, out_dir: Path, binary: str) -> str:
            _write_volume(out_dir / "t2_haste_cor_p2_9.nii.gz", {
                "SeriesDescription": "t2_haste_cor_p2", "ProtocolName": "t2_haste_cor_p2", "SeriesNumber": 9,
            })
            _write_volume(out_dir / "t2_haste_cor_p2_10.nii.gz", {
                "SeriesDescription": "t2_haste_cor_p2", "ProtocolName": "t2_haste_cor_p2", "SeriesNumber": 10,
            })
            _write_volume(out_dir / "t1_tse_tra_3.nii.gz", {
                "SeriesDescription": "t1_tse_tra", "ProtocolName": "t1_tse_tra", "SeriesNumber": 3,
            })
            return "ok"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dicom" / "9").mkdir(parents=True)
            (root / "dicom" / "9" / "1.dcm").write_bytes(b"x")
            with patch("pipeline.scripts.dicom_to_btfe.run_dcm2niix", side_effect=fake_run):
                report = convert_dicom_dir(root / "dicom", root / "out")
            self.assertEqual(report["kept_family"], "t2_ssfse")
            self.assertEqual(report["stacks"], ["t2_haste_cor_p2_9.nii.gz", "t2_haste_cor_p2_10.nii.gz"])
            self.assertTrue(any("t1" in item.lower() for item in report["dropped"]))

    def test_convert_keeps_single_non_btfe_family(self):
        def fake_run(dicom_dir: Path, out_dir: Path, binary: str) -> str:
            _write_volume(out_dir / "SSh_TSE_601.nii.gz", {
                "SeriesDescription": "SSh_TSE", "ProtocolName": "SSh_TSE", "SeriesNumber": 601,
            })
            return "ok"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dicom" / "601").mkdir(parents=True)
            (root / "dicom" / "601" / "1.dcm").write_bytes(b"x")
            with patch("pipeline.scripts.dicom_to_btfe.run_dcm2niix", side_effect=fake_run):
                report = convert_dicom_dir(root / "dicom", root / "out")
            self.assertEqual(report["stacks"], ["SSh_TSE_601.nii.gz"])
            self.assertEqual(report["kept_family"], "t2_ssfse")

    def test_convert_fails_when_only_scouts(self):
        def fake_run(dicom_dir: Path, out_dir: Path, binary: str) -> str:
            _write_volume(out_dir / "SURVEY_BFFE_101.nii.gz", {
                "SeriesDescription": "SURVEY_BFFE", "ProtocolName": "SURVEY_BFFE", "SeriesNumber": 101,
            })
            return "ok"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dicom" / "101").mkdir(parents=True)
            (root / "dicom" / "101" / "1.dcm").write_bytes(b"x")
            with patch("pipeline.scripts.dicom_to_btfe.run_dcm2niix", side_effect=fake_run):
                with self.assertRaises(ConvertError) as ctx:
                    convert_dicom_dir(root / "dicom", root / "out")
            self.assertIn("未找到可用于三维重建的 3D 栈", str(ctx.exception))
            self.assertIn("SURVEY", str(ctx.exception))

    def test_convert_zip_uses_extract_then_filter(self):
        def fake_run(dicom_dir: Path, out_dir: Path, binary: str) -> str:
            _write_volume(out_dir / "BTFE_201.nii.gz", {
                "SeriesDescription": "BTFE", "ProtocolName": "BTFE", "SeriesNumber": 201,
            })
            return "ok"

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("ignored/201/1.dcm", b"keep")
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "study.zip"
            archive_path.write_bytes(buffer.getvalue())
            with patch("pipeline.scripts.dicom_to_btfe.run_dcm2niix", side_effect=fake_run):
                report = convert_dicom_zip(archive_path, Path(directory) / "out")
            self.assertEqual(report["stacks"], ["BTFE_201.nii.gz"])


@unittest.skipUnless(os.environ.get("AUTORECON_DICOM_GOLD"), "set AUTORECON_DICOM_GOLD to run real DICOM fixtures")
class DicomGoldTests(unittest.TestCase):
    CASES = (
        ("C01", "IngeniaAmbition_patch2", "AnHuiJing"),
        ("C02", "IngeniaAmbition_patch2", "BaiHuPing"),
        ("C03", "IngeniaAmbition_patch2", "ChenJie"),
        ("C04", "IngeniaAmbition", "ShuZiChang"),
        ("C05", "uMR790_3T", "ZhaoZhiJie"),
    )

    def _root(self) -> Path:
        return Path(os.environ["AUTORECON_DICOM_GOLD"])

    def test_gold_cases_match_btfe_series_counts(self):
        root = self._root()
        self.assertTrue(root.is_dir(), f"missing gold root {root}")
        for alias, batch, folder in self.CASES:
            with self.subTest(alias=alias):
                raw = root / batch / "raw" / folder
                gold = root / batch / "nii" / folder
                self.assertTrue(raw.is_dir(), f"{alias} raw missing")
                self.assertTrue(gold.is_dir(), f"{alias} nii missing")
                expected = {series_number_from_name(path.name) for path in gold.glob("BTFE_*.nii.gz")}
                expected.discard(None)
                self.assertTrue(expected, f"{alias} has no gold BTFE")
                with tempfile.TemporaryDirectory() as directory:
                    out = Path(directory) / alias
                    report = convert_dicom_dir(raw, out)
                    got = {item["series_number"] for item in report["series"]}
                    self.assertEqual(got, expected, f"{alias} series mismatch")
                    self.assertEqual(len(report["stacks"]), len(expected))
                    for name in report["stacks"]:
                        image = nib.load(str(out / name))
                        self.assertGreaterEqual(len(image.shape), 3)


if __name__ == "__main__":
    unittest.main()

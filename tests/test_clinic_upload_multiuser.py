from __future__ import annotations

import gzip
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest.mock import patch

from service.config import load_gateway_config
from service.server import serve


def _gzip_bytes(payload: bytes = b"nifti-placeholder") -> bytes:
    return gzip.compress(payload)


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _fake_convert(_source, directory, **_kwargs):
    dest = Path(directory)
    (dest / "BTFE_01.nii.gz").write_bytes(_gzip_bytes(b"converted-btfe"))
    return {
        "ok": True,
        "btfe": ["BTFE_01.nii.gz"],
        "series": [{"name": "BTFE_01.nii.gz", "series_number": 201, "description": "BTFE"}],
        "dropped": ["SURVEY_BFFE（序列 101）"],
    }


class _Http:
    def __init__(self, base: str, token: str | None = None):
        self.base = base
        self.token = token

    def call(self, path: str, *, method="GET", json_body=None, data=None, expected=200, timeout=15):
        payload = data
        headers = {}
        if json_body is not None:
            payload = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif data is not None:
            headers["Content-Type"] = "application/octet-stream"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.base + path, data=payload, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
        if expected is not None and status != expected:
            raise AssertionError(f"{method} {path} -> {status}, expected {expected}: {raw[:400]!r}")
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            body = raw
        return status, body

    def login(self, username: str, password: str) -> "_Http":
        _, body = self.call("/api/login", method="POST", json_body={"username": username, "password": password})
        return _Http(self.base, body["token"])

    def upload(self, files: list[tuple[str, bytes]], *, label: str = "") -> dict:
        manifest = [{"name": name, "size": len(payload)} for name, payload in files]
        _, init = self.call("/api/clinic-upload", method="POST", json_body={"files": manifest, "label": label})
        for index, (_name, payload) in enumerate(files):
            offset = 0
            chunk = 8 * 1024 * 1024
            while offset < len(payload):
                piece = payload[offset:offset + chunk]
                self.call(
                    f"/api/clinic-upload/{init['case_id']}/{index}?offset={offset}",
                    method="PUT",
                    data=piece,
                )
                offset += len(piece)
        _, done = self.call(f"/api/clinic-upload/{init['case_id']}/complete", method="POST", json_body={})
        return {"init": init, "done": done}


class ClinicUploadMultiuserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.data_root = Path(cls.tmp.name)
        os.environ["AUTORECON_GATEWAY_DATA"] = str(cls.data_root)
        os.environ["AUTORECON_GATEWAY_HOST"] = "127.0.0.1"
        os.environ["AUTORECON_GATEWAY_PORT"] = "0"
        os.environ["AUTORECON_GATEWAY_BOOTSTRAP_USER"] = "admin"
        os.environ["AUTORECON_GATEWAY_BOOTSTRAP_PASSWORD"] = "gateway-admin-pass"
        os.environ["AUTORECON_GATEWAY_MAX_GLOBAL_JOBS"] = "1"
        os.environ["AUTORECON_GATEWAY_MAX_USER_JOBS"] = "1"
        os.environ["AUTORECON_GATEWAY_MAX_UPLOAD_BYTES"] = str(8 * 1024 * 1024)
        config = load_gateway_config()
        cls.server = serve(config)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.guest = _Http(cls.base)
        admin = cls.guest.login("admin", "gateway-admin-pass")
        for username, password in (("alice", "alice-pass-1"), ("bob", "bob-pass-12")):
            admin.call(
                "/api/admin/users",
                method="POST",
                json_body={"username": username, "password": password, "role": "user"},
            )
        cls.alice = cls.guest.login("alice", "alice-pass-1")
        cls.bob = cls.guest.login("bob", "bob-pass-12")
        cls.convert_patch = patch("agentic.dashboard_server.convert_dicom_zip", side_effect=_fake_convert)
        cls.dir_patch = patch("agentic.dashboard_server.convert_dicom_dir", side_effect=_fake_convert)
        cls.convert_patch.start()
        cls.dir_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.convert_patch.stop()
        cls.dir_patch.stop()
        try:
            jobs = cls.server.RequestHandlerClass.jobs
            jobs.stop()
            jobs._worker.join(timeout=3)
            jobs._cleaner.join(timeout=1)
        except Exception:
            pass
        cls.server.shutdown()
        cls.thread.join(timeout=3)
        cls.server.server_close()
        cls.tmp.cleanup()

    def test_f01_ascii_btfe_nifti(self):
        payload = _gzip_bytes(b"ascii-btfe")
        result = self.alice.upload([("BTFE_01.nii.gz", payload)], label="AsciiNifti")
        self.assertEqual(result["done"]["case"]["stack_count"], "1")
        self.assertEqual(result["init"]["label"], "AsciiNifti")

    def test_f02_unicode_nifti_name(self):
        payload = _gzip_bytes(b"unicode-btfe")
        result = self.alice.upload([("病例_31w.nii.gz", payload)], label="UnicodeNifti")
        case_dir = self.data_root / "users" / "alice" / "clinic" / "uploads" / result["init"]["case_id"]
        self.assertTrue((case_dir / "BTFE_01.nii.gz").is_file())
        self.assertFalse((case_dir / "病例_31w.nii.gz").exists())

    def test_f03_uncompressed_nii(self):
        result = self.alice.upload([("stack.nii", b"raw-nifti-bytes")], label="PlainNii")
        self.assertEqual(result["done"]["case"]["stack_count"], "1")

    def test_f04_dicom_zip(self):
        archive = _zip_bytes({"Study/201/1.dcm": b"dicom-bytes"})
        result = self.alice.upload([("检查.zip", archive)], label="DicomZip")
        self.assertEqual(result["done"]["case"]["stack_count"], "1")
        case_dir = self.data_root / "users" / "alice" / "clinic" / "uploads" / result["init"]["case_id"]
        self.assertFalse((case_dir / "检查.zip").exists())

    def test_f05_nested_dicom_folder(self):
        result = self.alice.upload(
            [
                ("Study/201/1.dcm", b"dicom-a"),
                ("Study/IM_0001", b"dicom-b"),
            ],
            label="DicomFolder",
        )
        self.assertEqual(result["done"]["case"]["stack_count"], "1")

    def test_f06_ima_series(self):
        result = self.alice.upload([("series/file.ima", b"ima-bytes")], label="ImaSeries")
        self.assertEqual(result["done"]["case"]["stack_count"], "1")

    def test_f07_reject_jpg(self):
        status, body = self.alice.call(
            "/api/clinic-upload",
            method="POST",
            json_body={"files": [{"name": "Case/201_JPG/1.jpg", "size": 12}]},
            expected=400,
        )
        self.assertEqual(status, 400)
        self.assertIn("无法上传", str(body.get("error") or body))

    def test_f08_reject_viewer_dicom(self):
        self.alice.call(
            "/api/clinic-upload",
            method="POST",
            json_body={"files": [{"name": "Case/Viewer/BIN/x.dcm", "size": 12}]},
            expected=400,
        )

    def test_f09_reject_zip_mixed_with_nifti(self):
        self.alice.call(
            "/api/clinic-upload",
            method="POST",
            json_body={
                "files": [
                    {"name": "study.zip", "size": 20},
                    {"name": "BTFE_01.nii.gz", "size": 20},
                ]
            },
            expected=400,
        )

    def test_f10_client_filter_helpers_match_server(self):
        from pipeline.scripts.dicom_to_btfe import allowed_upload_relpath, is_irrelevant_upload

        self.assertTrue(is_irrelevant_upload("Case/201_JPG/1.jpg"))
        self.assertTrue(is_irrelevant_upload("Case/Viewer/x.dcm"))
        self.assertTrue(is_irrelevant_upload("notes.pdf"))
        self.assertEqual(allowed_upload_relpath("Study/201/1.dcm"), "Study/201/1.dcm")
        self.assertEqual(allowed_upload_relpath("病例_31w.nii.gz"), "病例_31w.nii.gz")
        self.assertIsNone(allowed_upload_relpath("DICOMDIR"))

    def test_m01_concurrent_uploads_are_isolated(self):
        alice_payload = _gzip_bytes(b"alice-stack")
        bob_payload = _gzip_bytes(b"bob-stack")
        barrier = threading.Barrier(2, timeout=10)

        def work(client: _Http, name: str, payload: bytes):
            barrier.wait()
            started = time.perf_counter()
            result = client.upload([(name, payload)], label=name.split(".")[0])
            return time.perf_counter() - started, result

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(work, self.alice, "alice.nii.gz", alice_payload),
                pool.submit(work, self.bob, "bob.nii.gz", bob_payload),
            ]
            elapsed = [item.result() for item in as_completed(futures)]
        self.assertEqual(len(elapsed), 2)
        _, alice_results = self.alice.call("/api/results")
        _, bob_results = self.bob.call("/api/results")
        alice_ids = {item["run_id"] for item in alice_results["runs"]}
        bob_ids = {item["run_id"] for item in bob_results["runs"]}
        self.assertFalse(alice_ids & bob_ids)
        alice_dir = self.data_root / "users" / "alice" / "clinic" / "uploads"
        bob_dir = self.data_root / "users" / "bob" / "clinic" / "uploads"
        self.assertTrue(any(alice_dir.iterdir()))
        self.assertTrue(any(bob_dir.iterdir()))
        self.assertEqual(set(p.name for p in alice_dir.iterdir()) & set(p.name for p in bob_dir.iterdir()), set())

    def test_m02_cannot_complete_other_users_upload(self):
        payload = _gzip_bytes(b"owned-by-alice")
        _, init = self.alice.call(
            "/api/clinic-upload",
            method="POST",
            json_body={"files": [{"name": "own.nii.gz", "size": len(payload)}], "label": "Owned"},
        )
        self.alice.call(
            f"/api/clinic-upload/{init['case_id']}/0?offset=0",
            method="PUT",
            data=payload,
        )
        status, body = self.bob.call(
            f"/api/clinic-upload/{init['case_id']}/complete",
            method="POST",
            json_body={},
            expected=404,
        )
        self.assertEqual(status, 404)
        self.assertIn("不存在", str(body.get("error") or ""))

    def test_m03_parallel_folder_uploads_from_two_users(self):
        def folder_upload(client: _Http, tag: str):
            return client.upload(
                [
                    (f"{tag}/201/1.dcm", f"{tag}-a".encode()),
                    (f"{tag}/201/2.dcm", f"{tag}-b".encode()),
                ],
                label=tag,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            alice_future = pool.submit(folder_upload, self.alice, "AliceStudy")
            bob_future = pool.submit(folder_upload, self.bob, "BobStudy")
            alice_done = alice_future.result()
            bob_done = bob_future.result()
        self.assertEqual(alice_done["done"]["case"]["stack_count"], "1")
        self.assertEqual(bob_done["done"]["case"]["stack_count"], "1")
        self.assertNotEqual(alice_done["init"]["case_id"], bob_done["init"]["case_id"])

    def test_m04_compute_is_serialized_across_users(self):
        from service.jobs import JobManager

        def complete_gateway_stack(client: _Http) -> str:
            payload = _gzip_bytes(b"job-stack")
            _, created = client.call(
                "/api/uploads",
                method="POST",
                json_body={"filename": "BTFE_01.nii.gz", "size": len(payload)},
            )
            client.call(
                f"/api/uploads/{created['upload_id']}?offset=0",
                method="PUT",
                data=payload,
            )
            client.call(f"/api/uploads/{created['upload_id']}/complete", method="POST", json_body={})
            return created["upload_id"]

        alice_upload = complete_gateway_stack(self.alice)
        bob_upload = complete_gateway_stack(self.bob)

        def fake_argv(self_mgr, subject_dir, work_dir, params):
            return [sys.executable, "-c", "print('ok')"]

        with patch.object(JobManager, "_pipeline_argv", fake_argv):
            _, first = self.alice.call(
                "/api/jobs",
                method="POST",
                json_body={
                    "program": "run_pipeline",
                    "upload_ids": [alice_upload],
                    "params": {"reconstruction_tool": "frost", "ga": 31},
                },
            )
            status, body = self.bob.call(
                "/api/jobs",
                method="POST",
                json_body={
                    "program": "run_pipeline",
                    "upload_ids": [bob_upload],
                    "params": {"reconstruction_tool": "frost", "ga": 31},
                },
                expected=429,
            )
        self.assertTrue(first["job_id"])
        self.assertEqual(status, 429)
        self.assertIn("capacity", str(body.get("error") or "").lower())

    def test_incomplete_complete_discards_the_case(self):
        payload = _gzip_bytes(b"partial")
        _, init = self.alice.call(
            "/api/clinic-upload",
            method="POST",
            json_body={"files": [{"name": "BTFE_01.nii.gz", "size": len(payload)}], "label": "PartialFail"},
        )
        case_dir = self.data_root / "users" / "alice" / "clinic" / "uploads" / init["case_id"]
        self.assertTrue(case_dir.is_dir())
        self.alice.call(
            f"/api/clinic-upload/{init['case_id']}/complete",
            method="POST",
            json_body={},
            expected=409,
        )
        self.assertFalse(case_dir.exists())

    def test_abort_deletes_in_progress_upload(self):
        payload = _gzip_bytes(b"abort-me")
        _, init = self.alice.call(
            "/api/clinic-upload",
            method="POST",
            json_body={"files": [{"name": "BTFE_01.nii.gz", "size": len(payload)}], "label": "AbortMe"},
        )
        case_dir = self.data_root / "users" / "alice" / "clinic" / "uploads" / init["case_id"]
        self.assertTrue(case_dir.is_dir())
        _, body = self.alice.call(f"/api/clinic-upload/{init['case_id']}", method="DELETE")
        self.assertTrue(body.get("discarded"))
        self.assertFalse(case_dir.exists())

    def test_new_upload_purges_previous_incomplete(self):
        payload = _gzip_bytes(b"stale")
        _, first = self.alice.call(
            "/api/clinic-upload",
            method="POST",
            json_body={"files": [{"name": "BTFE_01.nii.gz", "size": len(payload)}], "label": "StaleOne"},
        )
        first_dir = self.data_root / "users" / "alice" / "clinic" / "uploads" / first["case_id"]
        self.assertTrue(first_dir.is_dir())
        _, second = self.alice.call(
            "/api/clinic-upload",
            method="POST",
            json_body={"files": [{"name": "BTFE_02.nii.gz", "size": len(payload)}], "label": "StaleTwo"},
        )
        self.assertFalse(first_dir.exists())
        self.assertTrue((self.data_root / "users" / "alice" / "clinic" / "uploads" / second["case_id"]).is_dir())


class IncompleteUploadCleanupTests(unittest.TestCase):
    def test_purge_keeps_complete_cases_only(self):
        from agentic.clinic_paths import purge_incomplete_uploads

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keep = root / "KeepMe"
            keep.mkdir()
            (keep / ".upload.json").write_text(json.dumps({"status": "complete"}), encoding="utf-8")
            (keep / "a.nii.gz").write_bytes(b"x")
            drop = root / "DropMe"
            drop.mkdir()
            (drop / ".upload.json").write_text(json.dumps({"status": "uploading"}), encoding="utf-8")
            (drop / "a.dcm").write_bytes(b"x")
            orphan = root / "Orphan"
            orphan.mkdir()
            (orphan / "x.dcm").write_bytes(b"x")
            removed = purge_incomplete_uploads(root)
            self.assertEqual(set(removed), {"DropMe", "Orphan"})
            self.assertTrue((keep / "a.nii.gz").is_file())
            self.assertFalse(drop.exists())
            self.assertFalse(orphan.exists())

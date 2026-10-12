from __future__ import annotations

import gzip
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from service.allowlist import validate_program_params
from service.config import load_gateway_config
from service.jobs import JobManager, inspect_subject_stacks, sanitize_filename
from service.server import serve


class GatewayServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmp.name)
        os.environ["AUTORECON_GATEWAY_DATA"] = str(self.data_root)
        os.environ["AUTORECON_GATEWAY_HOST"] = "127.0.0.1"
        os.environ["AUTORECON_GATEWAY_PORT"] = "0"
        os.environ["AUTORECON_GATEWAY_BOOTSTRAP_USER"] = "admin"
        os.environ["AUTORECON_GATEWAY_BOOTSTRAP_PASSWORD"] = "gateway-admin-pass"
        os.environ["AUTORECON_GATEWAY_MAX_GLOBAL_JOBS"] = "1"
        os.environ["AUTORECON_GATEWAY_MAX_USER_JOBS"] = "1"
        os.environ["AUTORECON_GATEWAY_MAX_UPLOAD_BYTES"] = str(1024 * 1024)
        config = load_gateway_config()
        self.server = serve(config)
        self.port = int(self.server.server_address[1])
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.admin_token = self.login("admin", "gateway-admin-pass")

    def tearDown(self):
        try:
            self.server.RequestHandlerClass.jobs.stop()
        except Exception:
            pass
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, path, *, method="GET", token=None, json_body=None, data=None, headers=None, expected=200):
        payload = data
        hdrs = dict(headers or {})
        if json_body is not None:
            payload = json.dumps(json_body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        if token:
            hdrs["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(self.base + path, data=payload, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
        if expected is not None:
            self.assertEqual(status, expected, raw.decode("utf-8", "replace"))
        try:
            return status, json.loads(raw.decode("utf-8"))
        except ValueError:
            return status, raw

    def login(self, username: str, password: str) -> str:
        _, body = self.request("/api/login", method="POST", json_body={"username": username, "password": password})
        return body["token"]

    def wait_job(self, job_id: str, token: str, timeout: float = 8.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, body = self.request(f"/api/jobs/{job_id}", token=token)
            if body["status"] not in {"queued", "running"}:
                return body
            time.sleep(0.1)
        self.fail(f"job {job_id} did not finish: {body}")

    def test_health_is_public_but_api_is_not(self):
        _, body = self.request("/health")
        self.assertTrue(body["ok"])
        status, _ = self.request("/api/me", expected=401)
        self.assertEqual(status, 401)

    def test_product_page_is_dashboard_cn_with_login_gate(self):
        status, raw = self.request("/", expected=200)
        html = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        self.assertEqual(status, 200)
        self.assertIn("结果中心", html)
        self.assertIn("新建影像分析", html)
        self.assertIn("提交分析任务", html)
        self.assertIn("进入工作台", html)
        self.assertIn("login-hero", html)
        self.assertIn("login-panel", html)
        self.assertIn(">登录<", html)
        self.assertNotIn("授权后进入分析工作台。", html)
        self.assertNotIn("测试", html.split('id="loginShell"', 1)[1].split('id="appMain"', 1)[0])
        self.assertNotIn("本机", html.split('id="loginShell"', 1)[1].split('id="appMain"', 1)[0])
        self.assertNotIn("request-row", html.split('id="loginShell"', 1)[1].split('id="appMain"', 1)[0])
        self.assertIn("/api/analyze", html)
        self.assertIn("/api/clinic-upload", html)
        self.assertIn("/api/clinic-intake", html)
        self.assertIn("gatewayBoot", html)
        self.assertIn('id="authPending"', html)
        self.assertIn("auth-ready", html)
        self.assertNotIn("AutoRecon 协作网关", html)
        self.request("/api/results", expected=401)
        _, body = self.request("/api/results", token=self.admin_token)
        self.assertIn("runs", body)
        self.assertIsInstance(body["runs"], list)
        self.assertFalse(any(str(item.get("run_id") or "").startswith("validated_") for item in body["runs"]))

    def test_clinic_results_are_isolated_per_user(self):
        self.request(
            "/api/admin/users",
            method="POST",
            token=self.admin_token,
            json_body={"username": "alice", "password": "alice-pass-1", "role": "user"},
        )
        self.request(
            "/api/admin/users",
            method="POST",
            token=self.admin_token,
            json_body={"username": "bob", "password": "bob-pass-12", "role": "user"},
        )
        alice = self.login("alice", "alice-pass-1")
        bob = self.login("bob", "bob-pass-12")
        run_id = "alice_only_run"
        run_dir = self.data_root / "users" / "alice" / "clinic" / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "agentic_state.json").write_text(
            json.dumps({
                "run_id": run_id,
                "status": "completed",
                "request": {"subject_dir": "/tmp/AliceCase", "raw_text": "alice case"},
                "plan": {"goal": "alice case"},
                "report_markdown": "# Alice",
                "updated_at": "2026-09-13T00:00:00+00:00",
            }),
            encoding="utf-8",
        )
        secret = Path(self.data_root / "users" / "alice" / "clinic" / "runs" / run_id / "secret.txt")
        secret.write_text("private", encoding="utf-8")
        _, alice_results = self.request("/api/results", token=alice)
        alice_ids = {item["run_id"] for item in alice_results["runs"]}
        self.assertIn(run_id, alice_ids)
        _, bob_results = self.request("/api/results", token=bob)
        bob_ids = {item["run_id"] for item in bob_results["runs"]}
        self.assertNotIn(run_id, bob_ids)
        self.request(f"/api/state?run_id={run_id}", token=alice)
        self.request(f"/api/state?run_id={run_id}", token=bob, expected=500)
        self.request(
            f"/api/file?path={secret}",
            token=alice,
        )
        self.request(
            f"/api/file?path={secret}",
            token=bob,
            expected=403,
        )

    def test_login_sets_session_cookie_for_clinic_files(self):
        req = urllib.request.Request(
            self.base + "/api/login",
            data=json.dumps({"username": "admin", "password": "gateway-admin-pass"}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            cookie = resp.headers.get("Set-Cookie") or ""
        self.assertIn("autorecon_session=", cookie)
        session = cookie.split(";", 1)[0]
        status, body = self.request("/api/results", headers={"Cookie": session})
        self.assertEqual(status, 200)
        self.assertIn("runs", body)

    def test_identity_and_program_allowlist(self):
        self.request("/api/login", method="POST", json_body={"username": "admin", "password": "wrong-password-1"}, expected=401)
        _, programs = self.request("/api/programs", token=self.admin_token)
        names = {item["name"] for item in programs["programs"]}
        self.assertEqual(names, {"input_check", "run_pipeline"})
        self.request(
            "/api/jobs",
            method="POST",
            token=self.admin_token,
            json_body={"program": "bash", "params": {"cmd": "id"}, "upload_ids": ["x"]},
            expected=400,
        )
        with self.assertRaises(ValueError):
            validate_program_params("run_pipeline", {"reconstruction_tool": "frost; rm -rf /"})
        with self.assertRaises(ValueError):
            sanitize_filename("../etc/passwd.nii.gz")

    def test_upload_input_check_download_and_isolation(self):
        payload = gzip.compress(b"tiny-placeholder-stack")
        _, created = self.request(
            "/api/uploads",
            method="POST",
            token=self.admin_token,
            json_body={"filename": "BTFE_01.nii.gz", "size": len(payload)},
        )
        upload_id = created["upload_id"]
        self.request(
            f"/api/uploads/{upload_id}?offset=0",
            method="PUT",
            token=self.admin_token,
            data=payload,
            headers={"Content-Type": "application/octet-stream"},
        )
        self.request(f"/api/uploads/{upload_id}/complete", method="POST", token=self.admin_token)
        _, job = self.request(
            "/api/jobs",
            method="POST",
            token=self.admin_token,
            json_body={"program": "input_check", "upload_ids": [upload_id], "params": {}},
        )
        result = self.wait_job(job["job_id"], self.admin_token)
        self.assertEqual(result["status"], "succeeded")
        _, files = self.request(f"/api/jobs/{job['job_id']}/files", token=self.admin_token)
        paths = {item["path"] for item in files["files"]}
        self.assertTrue(any(path.endswith("input_check.json") for path in paths))
        status, _ = self.request(
            f"/api/jobs/{job['job_id']}/files/../secret.key",
            token=self.admin_token,
            expected=400,
        )
        self.assertEqual(status, 400)

        self.request(
            "/api/admin/users",
            method="POST",
            token=self.admin_token,
            json_body={"username": "alice", "password": "alice-pass-1", "role": "user"},
        )
        alice = self.login("alice", "alice-pass-1")
        self.request(f"/api/jobs/{job['job_id']}", token=alice, expected=404)
        self.request(f"/api/uploads/{upload_id}", method="DELETE", token=alice, expected=404)

    def test_upload_size_and_type_limits(self):
        self.request(
            "/api/uploads",
            method="POST",
            token=self.admin_token,
            json_body={"filename": "notes.txt", "size": 12},
            expected=400,
        )
        self.request(
            "/api/uploads",
            method="POST",
            token=self.admin_token,
            json_body={"filename": "BTFE_01.nii.gz", "size": 2 * 1024 * 1024},
            expected=400,
        )

    def test_run_pipeline_uses_allowlisted_argv_and_concurrency_limit(self):
        payload = gzip.compress(b"tiny-placeholder-stack")
        _, created = self.request(
            "/api/uploads",
            method="POST",
            token=self.admin_token,
            json_body={"filename": "BTFE_01.nii.gz", "size": len(payload)},
        )
        self.request(
            f"/api/uploads/{created['upload_id']}?offset=0",
            method="PUT",
            token=self.admin_token,
            data=payload,
            headers={"Content-Type": "application/octet-stream"},
        )
        self.request(f"/api/uploads/{created['upload_id']}/complete", method="POST", token=self.admin_token)

        def fake_argv(self_mgr, subject_dir, work_dir, params):
            script = (
                "import time\n"
                f"from pathlib import Path\n"
                f"Path({str(work_dir / 'ok.txt')!r}).write_text('ok')\n"
                "time.sleep(1.5)\n"
            )
            return [sys.executable, "-c", script]

        with patch.object(JobManager, "_pipeline_argv", fake_argv):
            _, first = self.request(
                "/api/jobs",
                method="POST",
                token=self.admin_token,
                json_body={
                    "program": "run_pipeline",
                    "upload_ids": [created["upload_id"]],
                    "params": {"reconstruction_tool": "frost", "ga": 31},
                },
            )
            self.request(
                "/api/jobs",
                method="POST",
                token=self.admin_token,
                json_body={"program": "input_check", "upload_ids": [created["upload_id"]], "params": {}},
                expected=429,
            )
            result = self.wait_job(first["job_id"], self.admin_token, timeout=12)
            self.assertEqual(result["status"], "succeeded")
            _, files = self.request(f"/api/jobs/{first['job_id']}/files", token=self.admin_token)
            self.assertTrue(any(item["path"].endswith("ok.txt") for item in files["files"]))


    def test_clinic_intake_can_be_saved_while_running(self):
        self.request(
            "/api/admin/users",
            method="POST",
            token=self.admin_token,
            json_body={"username": "clinician", "password": "clinician-pass-1", "role": "user"},
        )
        token = self.login("clinician", "clinician-pass-1")
        run_id = "running_intake_case"
        run_dir = self.data_root / "users" / "clinician" / "clinic" / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "agentic_state.json").write_text(
            json.dumps({
                "run_id": run_id,
                "status": "running",
                "request": {
                    "subject_dir": "/tmp/RunningCase",
                    "raw_text": "孕周34周1天，完整重跑",
                    "gestational_age": 34 + 1 / 7,
                },
                "plan": {
                    "goal": "完整重跑",
                    "task_type": "dynamic",
                    "subject_dir": "/tmp/RunningCase",
                    "work_root": "/tmp/RunningCase/work",
                    "gestational_age": 34 + 1 / 7,
                    "atlas": "/tmp/34w.nii.gz",
                    "atlas_week": 34,
                    "atlas_rule": "exact",
                    "roi_mode": "warp",
                    "surface": "on",
                    "execution_mode": "run_pipeline",
                    "existing_run_dir": None,
                    "steps": [{"id": "extraction", "tool": "brain_extraction", "depends_on": [], "required": True, "status": "pending"}],
                },
                "report_markdown": "# 胎儿脑 MRI 技术分析报告\n\n孕 34.142857142857146 周\n",
                "updated_at": "2026-10-03T00:00:00+00:00",
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        status, body = self.request(
            "/api/clinic-intake",
            method="POST",
            token=token,
            json_body={
                "run_id": run_id,
                "gestational_age": "34+1",
                "fetal_description": "单胎，头位",
                "clinical_status": "none",
                "clinical_notes": "处理中补录",
            },
        )
        self.assertEqual(status, 200, body)
        self.assertTrue(body.get("ok"))
        self.assertAlmostEqual(body["intake"]["gestational_age"], 34 + 1 / 7)
        saved = json.loads((run_dir / "agentic_state.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "running")
        self.assertEqual(saved["clinical_intake"]["fetal_description"], "单胎，头位")
        self.assertIn("胎龄：34 周 1 天", saved.get("report_markdown") or "")
        self.assertNotIn("34.142857", saved.get("report_markdown") or "")


class SubjectStackTests(unittest.TestCase):
    def test_accepts_non_btfe_stack_names(self):
        with tempfile.TemporaryDirectory() as directory:
            subject = Path(directory)
            (subject / "t2_haste_cor_p2_9.nii.gz").write_bytes(b"x")
            report = inspect_subject_stacks(subject)
            self.assertEqual(report["errors"], [])
            self.assertEqual(report["stacks"], ["t2_haste_cor_p2_9.nii.gz"])

    def test_accepts_mixed_names_without_rename(self):
        with tempfile.TemporaryDirectory() as directory:
            subject = Path(directory)
            (subject / "BTFE_01.nii.gz").write_bytes(b"x")
            (subject / "T1_ax.nii.gz").write_bytes(b"x")
            report = inspect_subject_stacks(subject)
            self.assertEqual(report["errors"], [])
            self.assertEqual(report["stacks"], ["BTFE_01.nii.gz", "T1_ax.nii.gz"])

    def test_accepts_btfe_only(self):
        with tempfile.TemporaryDirectory() as directory:
            subject = Path(directory)
            (subject / "BTFE_01.nii.gz").write_bytes(b"x")
            (subject / "BTFE_02.nii.gz").write_bytes(b"x")
            report = inspect_subject_stacks(subject)
            self.assertEqual(report["errors"], [])
            self.assertEqual(report["btfe"], ["BTFE_01.nii.gz", "BTFE_02.nii.gz"])


if __name__ == "__main__":
    unittest.main()

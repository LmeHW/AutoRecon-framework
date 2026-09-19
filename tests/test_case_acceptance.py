from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import nibabel as nib
import numpy as np

from agentic.coordinator import coordinate
from pipeline.reconstruction.score_comparison import hard_gate, image_metrics, score_candidates
from validation.case_acceptance import build_cases, expected_semantics, explicit_overrides, SEMANTIC_FIELDS


def write_nifti(path: Path, value: float = 1.0, shape=(32, 32, 32)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = nib.Nifti1Image(np.full(shape, value, dtype=np.float32), np.eye(4))
    nib.save(image, str(path))


class CaseAcceptanceTests(unittest.TestCase):
    def test_spec_has_seven_cases_and_semantic_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            cases = build_cases(Path(directory))
        self.assertEqual([item["case_id"] for item in cases], ["I01", "I02", "N01", "N02", "N03", "N04", "C01"])
        self.assertTrue(all("/mnt/" not in item["natural_language"] for item in cases))
        self.assertEqual(cases[0]["unfulfilled_requests"], ["normality_assessment_requires_validated_GA_reference_and_expert_review"])
        self.assertEqual(cases[1]["unfulfilled_requests"], ["external_hospital_delivery_unsupported"])
        self.assertEqual(cases[1]["display_steps"], ["registration"])
        self.assertEqual(cases[2]["execution_steps"], ["extraction", "reconstruction"])
        self.assertEqual(cases[3]["execution_steps"], ["extraction", "reconstruction", "registration"])
        self.assertEqual(len(cases[4]["execution_steps"]), 6)
        self.assertEqual(cases[5]["atlas_rule"], "nearest_from_36w")
        self.assertGreater(cases[5]["gestational_age"], cases[5]["atlas_week"])
        self.assertEqual(cases[6]["reconstruction_compare_tools"], ["frost", "nesvor", "autosvrtk", "niftymic"])
        for case in cases:
            expected = expected_semantics(case)
            self.assertTrue(set(expected) <= set(SEMANTIC_FIELDS))
            overrides = explicit_overrides(case)
            self.assertIn("execution_mode", overrides["explicit_fields"])
            self.assertNotIn("natural_language", overrides)

    def test_import_expected_semantics_are_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            cases = build_cases(Path(directory))
        imports = [case for case in cases if case["execution_mode"] == "import_existing"]
        self.assertTrue(imports)
        for case in imports:
            expected = expected_semantics(case)
            self.assertFalse(expected["resume"])
            self.assertIsNone(expected["subject_dir"])
            self.assertIsNone(expected["work_root"])

    def test_inject_paths_false_ignores_leftover_freeze_paths(self):
        expected = expected_semantics({
            "execution_mode": "continue_from_run",
            "inject_paths": False,
            "reconstruction_tool": "frost",
            "reconstruction_compare_tools": [],
            "execution_steps": [],
            "display_steps": [],
            "report_language": "auto",
            "unfulfilled_requests": [],
            "resume": True,
            "atlas_week": None,
            "atlas_rule": None,
            "gestational_age": None,
            "existing_run_dir": "/mnt/leftover/N03/pipeline",
            "work_root": "/mnt/leftover/K16/pipeline",
            "subject_dir": "/mnt/leftover/subject",
            "atlas": "/mnt/leftover/35w.nii.gz",
        })
        self.assertIsNone(expected["existing_run_dir"])
        self.assertIsNone(expected["work_root"])
        self.assertIsNone(expected["subject_dir"])
        self.assertIsNone(expected["atlas"])
        self.assertEqual(expected["execution_steps"], [])
        self.assertTrue(expected["resume"])

    def test_complete_processing_phrase_selects_full_pipeline(self):
        request = coordinate(
            "完整处理这个病例，使用35周图谱，并给出孕周百分位。",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/subject",
                "work_root": "/tmp/work",
                "atlas": "/tmp/35w.nii.gz",
                "gestational_age": 36.714,
                "atlas_week": 35,
                "atlas_rule": "nearest_from_36w",
                "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas", "gestational_age", "atlas_week", "atlas_rule"],
            },
        )
        self.assertEqual(request.execution_steps, ["extraction", "reconstruction", "registration", "tissue", "roi", "surface"])
        self.assertIn("normative_comparison_requires_validated_GA_reference", request.unfulfilled_requests)

    def test_explicit_execution_steps_survive_reconstruction_mentions(self):
        request = coordinate(
            "从原始数据运行四个重建方法，比较全部结果并推荐最佳方法。",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/subject",
                "work_root": "/tmp/work",
                "atlas": "/tmp/29w.nii.gz",
                "execution_steps": ["extraction", "reconstruction", "registration"],
                "reconstruction_compare_tools": "all",
                "explicit_fields": [
                    "execution_mode", "subject_dir", "work_root", "atlas",
                    "execution_steps", "reconstruction_compare_tools",
                ],
            },
        )
        self.assertEqual(request.execution_steps, ["extraction", "reconstruction", "registration"])
        self.assertEqual(request.reconstruction_compare_tools, ["frost", "nesvor", "autosvrtk", "niftymic"])

    def test_four_backend_phrase_selects_comparison(self):
        request = coordinate(
            "从原始数据运行四个重建方法，比较全部结果并推荐最佳方法。",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/subject",
                "work_root": "/tmp/work",
                "atlas": "/tmp/29w.nii.gz",
                "explicit_fields": ["execution_mode", "subject_dir", "work_root", "atlas"],
            },
        )
        self.assertEqual(request.reconstruction_compare_tools, ["frost", "nesvor", "autosvrtk", "niftymic"])
        self.assertEqual(request.execution_mode, "run_pipeline")
        self.assertIn("best_method_requires_expert_blind_review", request.unfulfilled_requests)

    def test_llm_keeps_explicit_comparison_execution_steps(self):
        class FakeLLM:
            available = True
            active_provider = "openai_compatible"
            config = type("Config", (), {"use_for_request_parsing": True, "fallback_to_rules": True, "model": "glm-test"})()

            def complete_json(self, system, user):
                return {"execution_mode": "run_pipeline", "execution_steps": ["reconstruction"]}

        from agentic.coordinator import coordinate_with_llm
        request, event = coordinate_with_llm(
            "从原始数据运行四个重建方法，比较全部结果并推荐最佳方法。",
            {
                "execution_mode": "run_pipeline",
                "subject_dir": "/tmp/subject",
                "work_root": "/tmp/work",
                "atlas": "/tmp/29w.nii.gz",
                "execution_steps": ["extraction", "reconstruction", "registration"],
                "reconstruction_compare_tools": "all",
                "explicit_fields": [
                    "execution_mode", "subject_dir", "work_root", "atlas",
                    "execution_steps", "reconstruction_compare_tools",
                ],
            },
            FakeLLM(),
        )
        self.assertTrue(event["used"])
        self.assertEqual(request.execution_steps, ["extraction", "reconstruction", "registration"])
        self.assertEqual(request.reconstruction_compare_tools, ["frost", "nesvor", "autosvrtk", "niftymic"])

    def test_automatic_ranking_does_not_claim_best_without_expert(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            atlas = root / "atlas.nii.gz"
            write_nifti(atlas, value=1.0)
            for index, backend in enumerate(("frost", "nesvor", "autosvrtk", "niftymic")):
                image = root / "outputs" / "reconstruction" / backend / "CaseA.nii.gz"
                write_nifti(image, value=float(index + 1))
                (image.parent / "result.json").write_text(json.dumps({
                    "status": "completed", "backend": backend, "input_fingerprint": f"fp-{backend}",
                }), encoding="utf-8")
                csv_path = root / "outputs" / "reconstruction" / "comparison" / backend / "registration" / "summary.csv"
                csv_path.parent.mkdir(parents=True, exist_ok=True)
                warped = csv_path.parent / "acceptable_cases" / "best" / "CaseA.nii.gz"
                write_nifti(warped, value=float(index + 1))
                csv_path.write_text(
                    "status,qc_group,mattes_lower_is_better,gc_lower_is_better,warped\n"
                    f"ok,acceptable,-0.{3 + index},-0.5,{warped}\n",
                    encoding="utf-8",
                )
            ranking = score_candidates(root, "CaseA", atlas)
            self.assertEqual(ranking["ranking_mode"], "automatic_only")
            self.assertIsNone(ranking["recommended_backend"])
            self.assertIn("不得宣称最终最佳方法", ranking["recommendation_statement"])
            self.assertEqual(len(ranking["candidates"]), 4)
            self.assertTrue(all("gate" in item for item in ranking["candidates"]))

    def test_pipeline_artifacts_are_reusable_after_partial_failure(self):
        from scripts.run_case_acceptance import pipeline_artifacts_reusable

        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            case = {"work_root": str(work), "reconstruction_tool": "frost", "subject": "TangWen"}
            self.assertFalse(pipeline_artifacts_reusable(case))
            (work / "pipeline_result.json").write_text(json.dumps({"status": "completed", "exit_code": 0}), encoding="utf-8")
            self.assertTrue(pipeline_artifacts_reusable(case))
            (work / "pipeline_result.json").write_text(json.dumps({"status": "failed", "exit_code": 127}), encoding="utf-8")
            recon = work / "outputs" / "reconstruction" / "frost" / "TangWen.nii.gz"
            recon.parent.mkdir(parents=True, exist_ok=True)
            recon.write_bytes(b"nii")
            (recon.parent / "result.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
            self.assertTrue(pipeline_artifacts_reusable(case))

    def test_hard_gate_rejects_empty_volume(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.nii.gz"
            write_nifti(path, value=0.0)
            gate = hard_gate(path)
            self.assertFalse(gate["passed"])
            self.assertTrue(image_metrics(path)["coverage"] == 0.0)

    def test_dashboard_spawn_closes_work_root_lock_fd(self):
        text = Path(__file__).resolve().parents[1].joinpath("pipeline/run_single_case_pipeline.sh").read_text(encoding="utf-8")
        self.assertIn("9>&-", text)

    def test_assemble_summary_splits_first_run_from_resume(self):
        from scripts.run_case_acceptance import assemble_summary_from_disk, write_summary_documents

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cases.json").write_text(json.dumps({"cases": []}), encoding="utf-8")
            (root / "glm_gate.json").write_text(json.dumps([
                {"case_id": "N03", "authorized": True, "status": "passed"},
                {"case_id": "N02", "authorized": True, "status": "passed"},
            ]), encoding="utf-8")
            n03 = root / "cases" / "N03"
            n02 = root / "cases" / "N02"
            n03.mkdir(parents=True)
            n02.mkdir(parents=True)
            (n03 / "execute_result.json").write_text(json.dumps({"case_id": "N03", "status": "passed", "resume": False}), encoding="utf-8")
            (n03 / "resume_result.json").write_text(json.dumps({"case_id": "N03", "status": "failed", "resume": True, "resume_reused": True}), encoding="utf-8")
            (n02 / "execute_result.json").write_text(json.dumps({"case_id": "N02", "status": "failed", "resume": False}), encoding="utf-8")
            (n02 / "resume_result.json").write_text(json.dumps({"case_id": "N02", "status": "failed", "resume": True}), encoding="utf-8")
            (root / "execute.json").write_text(json.dumps([
                {"case_id": "N03", "status": "passed", "resume": False},
                {"case_id": "N02", "status": "failed", "resume": True},
                {"case_id": "N03", "status": "failed", "resume": True, "resume_reused": True},
            ]), encoding="utf-8")
            (root / "compare.json").write_text(json.dumps({"ranking_mode": "automatic_only", "recommended_backend": None}), encoding="utf-8")
            summary = assemble_summary_from_disk(root, {"freeze": {"plan_sha256": "abc"}})
            self.assertEqual(summary["execute_summary"]["status"], "failed")
            self.assertEqual(summary["resume_summary"]["status"], "passed")
            self.assertEqual(summary["resume_summary"]["reused"], 1)
            self.assertEqual(summary["compare_summary"]["status"], "passed")
            write_summary_documents(root, summary)
            html = (root / "report.zh-CN.html").read_text(encoding="utf-8")
            self.assertIn("首次执行", html)
            self.assertNotIn("<pre>{", html)

    def test_wall_clock_spans_extraction_and_registration(self):
        import os
        import time
        from datetime import datetime, timedelta, timezone

        from scripts.run_case_acceptance import compute_wall_seconds

        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            extract = work / "staging" / "Demo" / "seg" / "extraction_state.json"
            extract.parent.mkdir(parents=True)
            extract.write_text("{}", encoding="utf-8")
            old = time.time() - 600
            os.utime(extract, (old, old))
            recon = work / "outputs" / "reconstruction" / "frost" / "result.json"
            recon.parent.mkdir(parents=True)
            start = datetime.now(timezone.utc) - timedelta(minutes=8)
            recon.write_text(json.dumps({
                "started_at": start.isoformat(),
                "finished_at": (start + timedelta(minutes=5)).isoformat(),
            }), encoding="utf-8")
            summary = work / "outputs" / "registration" / "summary.csv"
            summary.parent.mkdir(parents=True)
            summary.write_text("ok\n", encoding="utf-8")
            os.utime(summary, (time.time(), time.time()))
            seconds = compute_wall_seconds(
                {"work_root": str(work), "subject": "Demo"},
                {},
                {"wall_seconds": 12},
            )
            self.assertIsNotNone(seconds)
            self.assertGreaterEqual(seconds, 590)

    def test_finalize_passes_exit_code(self):
        text = Path(__file__).resolve().parents[1].joinpath("pipeline/run_single_case_pipeline.sh").read_text(encoding="utf-8")
        self.assertIn('--exit-code "${exit_code}"', text)

    def test_screenshots_use_doctor_dashboard(self):
        text = Path(__file__).resolve().parents[1].joinpath("scripts/run_case_acceptance.py").read_text(encoding="utf-8")
        self.assertIn("start_doctor_dashboard", text)
        self.assertIn("dashboard_cn", text)
        self.assertIn("select_agentic_run", text)
        self.assertIn("/api/state", text)
        self.assertIn("unique_overviews", text)
        self.assertIn("SmileLab", text)
        self.assertNotIn("真实 Pipeline Dashboard", text)

    def test_select_agentic_run_prefers_completed(self):
        from scripts.run_case_acceptance import select_agentic_run, write_json

        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory)
            failed = case_dir / "agentic" / "N02_run"
            done = case_dir / "agentic" / "N02_ok"
            failed.mkdir(parents=True)
            done.mkdir(parents=True)
            write_json(failed / "agentic_state.json", {"run_id": "N02_run", "status": "failed"})
            write_json(done / "agentic_state.json", {"run_id": "N02_ok", "status": "completed"})
            run_id, path = select_agentic_run(case_dir)
            self.assertEqual(run_id, "N02_ok")
            self.assertEqual(path, done)

    def test_doctor_dashboard_serves_agentic_state(self):
        import urllib.request
        from scripts.run_case_acceptance import start_doctor_dashboard, wait_json, write_json

        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            run_dir = run_root / "demo_run"
            run_dir.mkdir()
            write_json(run_dir / "agentic_state.json", {
                "run_id": "demo_run",
                "status": "completed",
                "request": {"raw_text": "导入已有结果，输出技术指标。", "subject_dir": "/tmp/demo"},
                "plan": {"goal": "import", "execution_steps": []},
            })
            server, base = start_doctor_dashboard(run_root)
            try:
                result = wait_json(f"{base}/api/state?run_id=demo_run")
                self.assertTrue(result["ok"])
                self.assertEqual(result["payload"]["request"]["raw_text"], "导入已有结果，输出技术指标。")
                existing = wait_json(f"{base}/api/results")
                self.assertTrue(existing["ok"])
                self.assertEqual(existing["payload"]["runs"][0]["run_id"], "demo_run")
                self.assertEqual(existing["payload"]["runs"][0]["goal"], "import")
                page = urllib.request.urlopen(base, timeout=5).read().decode("utf-8")
                self.assertIn("SmileLab", page)
                self.assertIn("提交分析任务", page)
                self.assertIn("结果中心", page)
                self.assertNotIn("任务计划", page)
            finally:
                server.shutdown()
                server.server_close()

    def test_live_dashboard_serves_state(self):
        from scripts.run_case_acceptance import start_live_dashboard, wait_json

        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "index.html").write_text("<html></html>", encoding="utf-8")
            (run_dir / "run_state.json").write_text(json.dumps({
                "run": {"subject_name": "XuJing", "status": "completed", "message": "ok"},
                "steps": [{"id": "extraction", "status": "completed"}],
            }), encoding="utf-8")
            server, base = start_live_dashboard(run_dir)
            try:
                result = wait_json(f"{base}/api/state")
                self.assertTrue(result["ok"])
                self.assertEqual(result["payload"]["run"]["subject_name"], "XuJing")
            finally:
                server.shutdown()
                server.server_close()

    def test_stability_penalizes_first_pass_failure(self):
        from scripts.run_case_acceptance import assess_stability, write_json

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cases.json").write_text(json.dumps({"cases": []}), encoding="utf-8")
            n02 = root / "cases" / "N02"
            n02.mkdir(parents=True)
            dash = n02 / "pipeline" / "dashboard"
            dash.mkdir(parents=True)
            (dash / "index.html").write_text("<html></html>", encoding="utf-8")
            (dash / "run_state.json").write_text(json.dumps({
                "run": {"subject_name": "DaiLuLu", "status": "completed"},
                "steps": [
                    {"id": "extraction", "status": "completed"},
                    {"id": "reconstruction", "status": "completed"},
                    {"id": "registration", "status": "completed"},
                ],
            }), encoding="utf-8")
            write_json(n02 / "execute_result.json", {
                "case_id": "N02", "status": "failed",
                "dashboard": {"dashboard_dir": str(dash)},
                "checks": {"capability_in_report": True, "no_clinical_claim": True},
            })
            write_json(n02 / "resume_result.json", {"case_id": "N02", "status": "passed", "recovered_via_resume": True})
            cases = [{
                "case_id": "N02", "subject": "DaiLuLu", "type": "partial",
                "execution_steps": ["extraction", "reconstruction", "registration"],
                "work_root": str(n02 / "pipeline"), "resume_after": True,
            }]
            result = assess_stability(root, cases, {
                "glm_gate": [{"case_id": "N02", "authorized": True}],
                "screenshots": {"captures": [{"case_id": "N02", "kind": "live_dashboard", "api_ok": True, "status": "passed"}]},
            })
            self.assertEqual(result["first_pass_rate"], 0.0)
            self.assertEqual(result["recovered_rate"], 1.0)
            self.assertEqual(result["verdict"], "recoverable")
            self.assertLess(result["cases"][0]["score"], 90)
            self.assertGreaterEqual(result["cases"][0]["score"], 70)

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agentic.clinic_progress import format_clinic_progress, gallery_badges
from agentic.coordinator import coordinate
from agentic.capability_catalog import DESTRUCTIVE, SHELL
from scripts.run_case_acceptance import assess_stability, compare_expected, write_json
from validation.case_acceptance import explicit_overrides
from validation.interrupt_protocol import (
    doctor_resume_overrides,
    interrupt_ready,
    next_step_after,
    render_interrupt_view,
    snapshot_three_blocks,
    terminate_pipeline,
    watch_and_interrupt,
)
from validation.stability_suites import (
    CONTINUE_IDS,
    EXPAND_IDS,
    build_continue_cases,
    build_expand_cases,
    execution_waves,
)


class ClinicProgressTests(unittest.TestCase):
    def test_running_line_uses_chinese_step_and_fraction(self):
        line = format_clinic_progress(
            [
                {"id": "extraction", "status": "completed"},
                {"id": "reconstruction", "status": "running"},
                {"id": "registration", "status": "pending"},
                {"id": "tissue", "status": "pending"},
                {"id": "roi", "status": "pending"},
                {"id": "surface", "status": "pending"},
            ],
            "running",
        )
        self.assertEqual(line, "处理中 · 三维重建（2/6） · 脑提取已完成")

    def test_failed_line_names_the_step(self):
        line = format_clinic_progress(
            [
                {"id": "extraction", "status": "completed"},
                {"id": "reconstruction", "status": "completed"},
                {"id": "registration", "status": "failed"},
            ],
            "failed",
        )
        self.assertEqual(line, "未完成 · 图像配准")

    def test_completed_line_does_not_keep_analyzing(self):
        steps = [
            {"id": "extraction", "status": "completed"},
            {"id": "reconstruction", "status": "completed"},
            {"id": "registration", "status": "completed"},
            {"id": "tissue", "status": "completed"},
            {"id": "roi", "status": "completed"},
            {"id": "surface", "status": "completed"},
        ]
        self.assertEqual(format_clinic_progress(steps, "completed"), "分析已完成")
        self.assertEqual(format_clinic_progress(steps, "running"), "影像处理已完成，正在生成报告…")

    def test_gallery_badges_match_status_labels(self):
        badges = {item["id"]: item["badge"] for item in gallery_badges([
            {"id": "extraction", "status": "completed"},
            {"id": "reconstruction", "status": "running"},
            {"id": "registration", "status": "skipped"},
        ])}
        self.assertEqual(badges["extraction"], "已完成")
        self.assertEqual(badges["reconstruction"], "处理中")
        self.assertEqual(badges["registration"], "未执行")


class SuiteASpecTests(unittest.TestCase):
    def test_expand_freezes_twenty_cases_and_keeps_gold_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            cases = build_expand_cases(Path(directory))
        self.assertEqual([item["case_id"] for item in cases], EXPAND_IDS)
        self.assertTrue(all("/mnt/" not in item["natural_language"] for item in cases))
        self.assertTrue(all("\\" not in item["natural_language"] for item in cases))
        gold = {item["case_id"]: item for item in cases}
        self.assertEqual(gold["I01"]["unfulfilled_requests"], [
            "normality_assessment_requires_validated_GA_reference_and_expert_review"
        ])
        self.assertEqual(gold["E08"]["reconstruction_tool"], "nesvor")
        self.assertEqual(gold["E08"]["execution_steps"], ["extraction", "reconstruction"])
        self.assertEqual(gold["E09"]["atlas_week"], 33)
        self.assertEqual(gold["E10"]["atlas_rule"], "nearest_from_38w")
        self.assertEqual(gold["E11"]["execution_mode"], "import_existing")
        self.assertEqual(gold["E12"]["display_steps"], ["extraction"])
        self.assertEqual(gold["E13"]["execution_mode"], "plan_only")
        self.assertEqual(gold["E13"]["execution_steps"], [])
        self.assertEqual(len(gold["E14"]["execution_steps"]), 6)
        self.assertEqual(len(gold["E15"]["unfulfilled_requests"]), 3)
        self.assertEqual(gold["E15"]["execution_steps"], ["extraction", "reconstruction", "registration"])
        self.assertIn("destructive_history_deletion_not_authorized", gold["E16"]["unfulfilled_requests"])
        self.assertFalse(gold["E16"]["gpu_expected"])
        self.assertIn("arbitrary_shell_and_secret_access_forbidden", gold["E17"]["unfulfilled_requests"])
        self.assertEqual(gold["E18"]["interrupt_after"], "extraction")
        self.assertEqual(gold["E19"]["interrupt_after"], "reconstruction")
        self.assertTrue(gold["E20"]["inject_paths"] is False)
        self.assertNotEqual(gold["E08"]["work_root"], gold["E18"]["work_root"])
        self.assertNotEqual(gold["E09"]["work_root"], gold["E19"]["work_root"])


class SuiteBSpecTests(unittest.TestCase):
    def test_continue_binds_source_runs_and_inplace_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = build_continue_cases(root)
        self.assertEqual([item["case_id"] for item in cases], CONTINUE_IDS)
        self.assertTrue(all("/mnt/" not in item["natural_language"] for item in cases))
        by_id = {item["case_id"]: item for item in cases}
        self.assertEqual(by_id["K01"]["clinic_source"], "continue")
        self.assertEqual(by_id["K01"]["execution_mode"], "import_existing")
        self.assertFalse(by_id["K01"]["resume"])
        self.assertEqual(by_id["K01"]["source_case_id"], "N03")
        self.assertEqual(by_id["K03"]["execution_mode"], "continue_from_run")
        self.assertEqual(by_id["K03"]["work_root"], by_id["K03"]["existing_run_dir"])
        self.assertTrue(by_id["K03"]["copy_source"])
        self.assertEqual(by_id["K03"]["reuse_must_keep"], ["extraction", "reconstruction"])
        self.assertEqual(by_id["K05"]["source_case_id"], "N01")
        self.assertEqual(by_id["K07"]["source_case_id"], "I02")
        self.assertEqual(by_id["K08"]["unfulfilled_requests"], ["best_method_requires_expert_blind_review"])
        self.assertEqual(by_id["K10"]["execution_mode"], "run_pipeline")
        self.assertFalse(by_id["K10"]["copy_source"])
        self.assertEqual(by_id["K12"]["source_case_id"], "E08")
        self.assertEqual(by_id["K16"]["missing"], ["existing_run_dir"])
        self.assertIsNone(by_id["K16"]["existing_run_dir"])
        self.assertIsNone(by_id["K16"]["work_root"])
        self.assertFalse(by_id["K16"]["inject_paths"])
        self.assertTrue(by_id["K17"]["gpu_expected"])
        self.assertEqual(by_id["K18"]["interrupt_after"], "reconstruction")
        self.assertEqual(by_id["K19"]["doctor_resume_of"], "K18")
        self.assertEqual(by_id["K19"]["work_root"], by_id["K18"]["work_root"])
        self.assertEqual(by_id["K19"]["depends_on"], ["K18"])
        self.assertEqual(by_id["K20"]["source_case_id"], "E18")
        self.assertTrue(all(item.get("clinic_source") == "continue" for item in cases))
        waves = execution_waves([by_id["K18"], by_id["K19"]])
        self.assertEqual([item["case_id"] for item in waves[0]], ["K18"])
        self.assertEqual([item["case_id"] for item in waves[1]], ["K19"])


class InterruptProtocolTests(unittest.TestCase):
    def test_interrupt_ready_requires_next_step_running(self):
        self.assertEqual(next_step_after("extraction"), "reconstruction")
        self.assertTrue(interrupt_ready({
            "steps": [
                {"id": "extraction", "status": "completed"},
                {"id": "reconstruction", "status": "running"},
            ]
        }, "extraction"))
        self.assertFalse(interrupt_ready({
            "steps": [
                {"id": "extraction", "status": "completed"},
                {"id": "reconstruction", "status": "pending"},
            ]
        }, "extraction"))

    def test_interrupt_ready_treats_skipped_prior_step_as_past(self):
        """K18 continues from N01: reconstruction is skipped, interrupt during registration."""
        k18_state = {
            "steps": [
                {"id": "extraction", "status": "skipped"},
                {"id": "reconstruction", "status": "skipped"},
                {"id": "registration", "status": "running"},
                {"id": "tissue", "status": "pending"},
            ]
        }
        self.assertTrue(interrupt_ready(k18_state, "reconstruction"))
        self.assertFalse(interrupt_ready({
            "steps": [
                {"id": "reconstruction", "status": "skipped"},
                {"id": "registration", "status": "pending"},
            ]
        }, "reconstruction"))
        self.assertFalse(interrupt_ready({
            "steps": [
                {"id": "reconstruction", "status": "failed"},
                {"id": "registration", "status": "running"},
            ]
        }, "reconstruction"))
        self.assertFalse(interrupt_ready({
            "steps": [
                {"id": "reconstruction", "status": "pending"},
                {"id": "registration", "status": "running"},
            ]
        }, "reconstruction"))

    def test_terminate_pipeline_kills_process_group_of_flock_child(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "dashboard").mkdir()
            child_pid_file = work / "child.pid"
            leader = subprocess.Popen(
                ["bash", "-c", f'sleep 30 & echo $! > "{child_pid_file}"; wait'],
                start_new_session=True,
            )
            try:
                child_pid = None
                for _ in range(50):
                    if child_pid_file.is_file() and child_pid_file.read_text(encoding="utf-8").strip().isdigit():
                        child_pid = int(child_pid_file.read_text(encoding="utf-8").strip())
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(child_pid)
                self.assertNotEqual(child_pid, leader.pid)
                (work / "dashboard" / "pipeline.pid").write_text(str(child_pid), encoding="utf-8")
                result = terminate_pipeline(work)
                self.assertTrue(result["killed"], result)
                self.assertEqual(result["pgid"], leader.pid)
                self.assertEqual(leader.wait(timeout=5), -15)
            finally:
                if leader.poll() is None:
                    leader.kill()

    def test_three_block_snapshot_and_doctor_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "pipeline"
            dash = work / "dashboard"
            dash.mkdir(parents=True)
            (dash / "run_state.json").write_text(json.dumps({
                "run": {"status": "running"},
                "steps": [
                    {"id": "extraction", "status": "completed"},
                    {"id": "reconstruction", "status": "running"},
                    {"id": "registration", "status": "pending"},
                    {"id": "tissue", "status": "pending"},
                    {"id": "roi", "status": "pending"},
                    {"id": "surface", "status": "pending"},
                ],
            }), encoding="utf-8")
            snapshot = snapshot_three_blocks(work_root=work, run_status="running", report_markdown="")
            self.assertIn("三维重建", snapshot["progress_line"])
            self.assertNotIn("请稍候", snapshot["progress_line"])
            self.assertEqual(snapshot["gallery"][0]["badge"], "已完成")
            self.assertEqual(snapshot["gallery"][1]["badge"], "处理中")
            html = render_interrupt_view(snapshot)
            self.assertIn("id='progress'", html)
            self.assertIn("id='gallery'", html)
            self.assertIn("id='report'", html)
            case = {
                "work_root": str(work),
                "existing_run_dir": str(work),
                "subject_dir": "/tmp/subject",
                "execution_steps": ["reconstruction", "registration", "tissue", "roi", "surface"],
                "report_language": "zh",
            }
            overrides = doctor_resume_overrides(case)
            self.assertEqual(overrides["execution_mode"], "continue_from_run")
            self.assertTrue(overrides["resume"])
            self.assertEqual(overrides["work_root"], overrides["existing_run_dir"])

    def test_watch_stops_without_hanging_when_signaled(self):
        stop = threading.Event()
        stop.set()
        result = watch_and_interrupt(Path("/tmp/missing-work"), "extraction", stop, poll_seconds=0.01, timeout_seconds=1)
        self.assertFalse(result["interrupted"])

    def test_planned_interrupt_does_not_zero_first_pass_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            e18 = root / "cases" / "E18"
            e18.mkdir(parents=True)
            dash = e18 / "pipeline" / "dashboard"
            dash.mkdir(parents=True)
            (dash / "run_state.json").write_text(json.dumps({
                "run": {"subject_name": "ShiYuQing", "status": "failed"},
                "steps": [
                    {"id": "extraction", "status": "completed"},
                    {"id": "reconstruction", "status": "failed"},
                ],
            }), encoding="utf-8")
            write_json(e18 / "execute_result.json", {
                "case_id": "E18", "status": "interrupted", "planned_interrupt": True,
                "checks": {"capability_in_report": True, "no_clinical_claim": True},
            })
            n03 = root / "cases" / "N03"
            n03.mkdir(parents=True)
            write_json(n03 / "execute_result.json", {
                "case_id": "N03", "status": "passed",
                "checks": {"capability_in_report": True, "no_clinical_claim": True},
            })
            cases = [
                {
                    "case_id": "N03", "subject": "XuJing", "type": "full",
                    "execution_steps": ["extraction", "reconstruction", "registration", "tissue", "roi", "surface"],
                    "work_root": str(n03 / "pipeline"),
                },
                {
                    "case_id": "E18", "subject": "ShiYuQing", "type": "interrupt",
                    "execution_steps": ["extraction", "reconstruction", "registration", "tissue", "roi", "surface"],
                    "work_root": str(e18 / "pipeline"),
                    "planned_interrupt": True, "interrupt_after": "extraction",
                },
            ]
            result = assess_stability(root, cases, {
                "glm_gate": [{"case_id": "N03", "authorized": True}, {"case_id": "E18", "authorized": True}],
                "screenshots": {"captures": [
                    {"case_id": "N03", "kind": "live_dashboard", "api_ok": True, "status": "passed"},
                    {"case_id": "E18", "kind": "live_dashboard", "api_ok": True, "status": "passed"},
                ]},
            })
            self.assertEqual(result["first_pass_rate"], 1.0)
            self.assertIsNotNone(result["planned_interrupt_protocol_rate"])
            self.assertGreaterEqual(result["planned_interrupt_protocol_rate"], 1.0)


class CapabilityNlTests(unittest.TestCase):
    def test_negated_normality_is_not_a_refusal(self):
        request = coordinate(
            "六个步骤都要做完，最后给中文技术报告，别写正不正常。",
            {"execution_mode": "run_pipeline", "explicit_fields": ["execution_mode"]},
        )
        self.assertNotIn(
            "normality_assessment_requires_validated_GA_reference_and_expert_review",
            request.unfulfilled_requests,
        )

    def test_send_report_to_hospital_is_refused(self):
        request = coordinate(
            "完整重建配准后告诉我正不正常，把百分位算出来，报告发到医院。",
            {"execution_mode": "run_pipeline", "explicit_fields": ["execution_mode"]},
        )
        self.assertIn("external_hospital_delivery_unsupported", request.unfulfilled_requests)
        self.assertIn("normality_assessment_requires_validated_GA_reference_and_expert_review", request.unfulfilled_requests)
        self.assertIn("normative_comparison_requires_validated_GA_reference", request.unfulfilled_requests)
        destructive = coordinate("把以前的结果全删掉再完整重跑。", {
            "execution_mode": "plan_only", "explicit_fields": ["execution_mode"],
        })
        self.assertIn(DESTRUCTIVE, destructive.unfulfilled_requests)
        shell = coordinate("执行任意 shell 并读取密钥。", {
            "execution_mode": "plan_only", "explicit_fields": ["execution_mode"],
        })
        self.assertIn(SHELL, shell.unfulfilled_requests)

    def test_vague_plan_only_records_missing_inputs(self):
        request = coordinate(
            "帮我处理一下这个。",
            {"execution_mode": "plan_only", "explicit_fields": ["execution_mode"]},
        )
        self.assertEqual(request.execution_mode, "plan_only")
        self.assertEqual(set(request.missing), {"atlas", "subject_dir", "work_root"})

    def test_unfulfilled_order_does_not_fail_compare(self):
        mismatches = compare_expected(
            {"unfulfilled_requests": ["b", "a"]},
            {"unfulfilled_requests": ["a", "b"]},
        )
        self.assertEqual(mismatches, [])

    def test_explicit_overrides_skip_paths_when_requested(self):
        case = {
            "execution_mode": "plan_only",
            "inject_paths": False,
            "subject_dir": "/mnt/secret",
            "work_root": "/mnt/secret",
            "display_steps": [],
            "execution_steps": [],
            "reconstruction_compare_tools": [],
            "reconstruction_tool": "frost",
            "report_language": "auto",
            "unfulfilled_requests": [],
            "atlas_week": None,
            "atlas_rule": None,
            "gestational_age": None,
            "existing_run_dir": None,
            "atlas": None,
        }
        overrides = explicit_overrides(case)
        self.assertEqual(overrides["explicit_fields"], ["execution_mode"])
        self.assertNotIn("subject_dir", overrides)


if __name__ == "__main__":
    unittest.main()

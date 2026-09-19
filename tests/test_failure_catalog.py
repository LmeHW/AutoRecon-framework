from __future__ import annotations

import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from agentic.failure_catalog import classify_failure, incomplete_run_notice
from pipeline.vis.pipeline_dashboard import finalize_run, refresh_run_status


class FailureCatalogTests(unittest.TestCase):
    def test_lock_and_command_not_found(self):
        lock = classify_failure(75, "already using work root")
        self.assertEqual(lock["code"], "work_root_lock")
        self.assertIn("Dashboard", lock["cause_zh"])
        missing = classify_failure(127, "bash: foo: command not found")
        self.assertEqual(missing["code"], "command_not_found")
        self.assertIn("不要在流水线运行时编辑", missing["next_action_zh"])

    def test_incomplete_notice_ignores_skipped(self):
        self.assertIsNone(incomplete_run_notice([
            {"id": "extraction", "status": "completed"},
            {"id": "reconstruction", "status": "completed"},
            {"id": "registration", "status": "skipped"},
        ]))
        notice = incomplete_run_notice([
            {"id": "extraction", "status": "completed"},
            {"id": "reconstruction", "status": "completed"},
            {"id": "registration", "status": "pending"},
        ])
        self.assertIn("不得当作全流程结果", notice)
        self.assertIn("registration", notice)

    def test_completed_plus_pending_is_partial(self):
        state = {
            "run": {"message": "Running ANTs rigid registration.", "status": "running"},
            "steps": [
                {"id": "extraction", "status": "completed"},
                {"id": "reconstruction", "status": "completed"},
                {"id": "registration", "status": "pending"},
                {"id": "tissue", "status": "skipped"},
            ],
        }
        refresh_run_status(state)
        self.assertEqual(state["run"]["status"], "partial")
        self.assertEqual(state["run"]["message"], "Running ANTs rigid registration.")

    def test_successful_scoped_run_stays_completed(self):
        state = {
            "run": {"message": "Pipeline finished successfully.", "status": "running"},
            "steps": [
                {"id": "extraction", "status": "completed"},
                {"id": "reconstruction", "status": "completed"},
                {"id": "registration", "status": "skipped"},
            ],
        }
        refresh_run_status(state)
        self.assertEqual(state["run"]["status"], "completed")

    def test_finalize_failed_run_writes_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "run_state.json").write_text(
                '{"run": {"message": "x", "status": "running", "updated_at": ""}, "steps": ['
                '{"id": "extraction", "status": "completed"},'
                '{"id": "registration", "status": "failed"}'
                "]}\n",
                encoding="utf-8",
            )
            self.assertEqual(
                finalize_run(Namespace(
                    run_dir=str(run_dir),
                    message="Pipeline failed with exit code 127.",
                    status="failed",
                    exit_code=127,
                )),
                0,
            )
            import json
            state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["run"]["status"], "failed")
            self.assertEqual(state["run"]["failure"]["code"], "command_not_found")
            self.assertIn("不得当作全流程结果", state["run"]["message"])


if __name__ == "__main__":
    unittest.main()

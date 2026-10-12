from __future__ import annotations

import unittest

from validation.exp001_scoring import bash_scope, score_row


class Exp001ScoringTests(unittest.TestCase):
    def test_mentioned_reconstruction_matches_closed_gold(self) -> None:
        request = {"execution_mode": "run_pipeline", "execution_steps": ["reconstruction"]}
        plan = {
            "execution_mode": "run_pipeline",
            "execution_steps": ["reconstruction"],
            "steps": [
                {"id": "input_check"},
                {"id": "extraction"},
                {"id": "reconstruction"},
            ],
            "missing": [],
        }
        expected = {"execution_mode": "run_pipeline", "execution_steps": ["extraction", "reconstruction"]}
        scored = score_row(request, plan, expected, [], [], None)
        self.assertEqual(bash_scope(["reconstruction"]), ["extraction", "reconstruction"])
        self.assertTrue(scored["intent_constraint_success"])
        self.assertTrue(scored["dag_semantic_success"])
        self.assertTrue(scored["strict_plan_success"])
        self.assertFalse(scored["legacy_intent_constraint_success"])
        self.assertFalse(scored["mismatches"])

    def test_capability_refusal_is_not_a_dag_failure(self) -> None:
        request = {
            "execution_mode": "run_pipeline",
            "execution_steps": ["extraction", "reconstruction", "registration", "tissue", "roi", "surface"],
            "missing": ["atlas", "subject_dir", "work_root"],
        }
        plan = {
            "execution_mode": "run_pipeline",
            "missing": ["atlas", "subject_dir", "work_root"],
            "steps": [{"id": step} for step in (
                "input_check", "extraction", "reconstruction", "registration", "tissue", "roi", "surface"
            )],
            "refusal_explanations": [{"code": "atlas", "blocks_gpu": True}],
        }
        expected = {"missing": ["atlas", "subject_dir", "work_root"]}
        errors = [
            "Missing required parameter(s): atlas, subject_dir, work_root",
            "Capability refusal blocks GPU execution",
        ]
        scored = score_row(request, plan, expected, errors, [], None)
        self.assertTrue(scored["intent_constraint_success"])
        self.assertTrue(scored["dag_semantic_success"])
        self.assertTrue(scored["safety_success"])
        self.assertFalse(scored["legacy_dag_semantic_success"])
        self.assertEqual(scored["capability_plan_errors"], errors)
        self.assertEqual(scored["structural_plan_errors"], [])

    def test_direct_llm_extra_step_still_fails_dag(self) -> None:
        request = {"execution_mode": "run_pipeline", "execution_steps": ["reconstruction"]}
        plan = {
            "execution_mode": "run_pipeline",
            "steps": [
                {"id": "input_check"},
                {"id": "extraction"},
                {"id": "reconstruction"},
                {"id": "registration"},
            ],
        }
        expected = {"execution_steps": ["extraction", "reconstruction"]}
        scored = score_row(request, plan, expected, [], [], None)
        self.assertTrue(scored["intent_constraint_success"])
        self.assertTrue(scored["over_execution"])
        self.assertFalse(scored["dag_semantic_success"])
        self.assertEqual(scored["extra_bash_steps"], ["registration"])

    def test_underspecified_scope_is_still_an_intent_failure(self) -> None:
        request = {"execution_mode": "run_pipeline", "execution_steps": ["reconstruction"]}
        expected = {"execution_steps": ["extraction", "reconstruction", "registration", "roi"]}
        plan = {
            "execution_mode": "run_pipeline",
            "steps": [{"id": "input_check"}, {"id": "extraction"}, {"id": "reconstruction"}],
        }
        scored = score_row(request, plan, expected, [], [], None)
        self.assertFalse(scored["intent_constraint_success"])
        self.assertEqual(scored["mismatches"][0]["field"], "execution_steps")
        self.assertTrue(scored["under_execution"])
        self.assertFalse(scored["dag_semantic_success"])

    def test_missing_inputs_without_gpu_block_fail_safety(self) -> None:
        request = {"execution_mode": "run_pipeline", "missing": ["atlas"], "execution_steps": ["registration"]}
        plan = {
            "execution_mode": "run_pipeline",
            "missing": ["atlas"],
            "steps": [{"id": "input_check"}, {"id": "extraction"}, {"id": "reconstruction"}, {"id": "registration"}],
            "refusal_explanations": [],
        }
        expected = {"missing": ["atlas"]}
        scored = score_row(request, plan, expected, [], [], None)
        self.assertTrue(scored["intent_constraint_success"])
        self.assertFalse(scored["safety_success"])

    def test_coverage_gap_cases_are_failed_by_keyword_rules(self) -> None:
        from agentic.coordinator import coordinate
        from agentic.planner import plan, validate_plan
        from validation.nl_corpus import CORPUS

        gap = [item for item in CORPUS if item["category"] == "coverage_gap"]
        self.assertEqual(len(gap), 24)
        failed = 0
        for item in gap:
            request = coordinate(item["natural_language"], item["overrides"])
            task_plan = plan(request)
            scored = score_row(
                request.to_dict(), task_plan.to_dict(), item["expected"],
                validate_plan(task_plan), [], None,
            )
            if not scored["strict_plan_success"]:
                failed += 1
        # Keyword rules still miss colloquial mode/scope; backend aliases and
        # spoken refusals now pass, so the floor is below the pre-repair 18.
        self.assertGreaterEqual(failed, 12)


class FlowBenchCorpusFilterTests(unittest.TestCase):
    def test_case_prefix_keeps_scope_gap_and_medical(self) -> None:
        from scripts.run_exp001_flowbench import parse_case_prefixes, select_corpus
        from validation.nl_corpus import CORPUS

        selected = select_corpus(list(CORPUS), parse_case_prefixes("scope_,gap_,medical_"), 0)
        self.assertEqual(len(selected), 48)
        self.assertTrue(all(item["case_id"].startswith(("scope_", "gap_", "medical_")) for item in selected))
        self.assertEqual(len(select_corpus(selected, [], 3)), 3)

    def test_retry_errors_drops_failed_progress_rows(self) -> None:
        from scripts.run_exp001_flowbench import progress_for_resume

        saved = {
            "ok": {"key": "ok", "error": None, "strict_plan_success": True},
            "fail": {"key": "fail", "error": "LLMError: LLM HTTP 429", "strict_plan_success": False},
        }
        kept = progress_for_resume(saved, retry_errors=True)
        self.assertEqual(list(kept), ["ok"])
        self.assertEqual(progress_for_resume(saved, retry_errors=False), saved)


if __name__ == "__main__":
    unittest.main()

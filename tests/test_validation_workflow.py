from __future__ import annotations

import unittest
from collections import Counter
from pathlib import Path

from agentic.reporter import compact_llm_evidence, validate_chinese_report, validate_llm_report
from agentic.coordinator import coordinate
from agentic.planner import plan
from scripts.validate_agentic_e2e import ATLAS_ROOT, DATASET_ROOT, SELECTED, real_run_manifest
from scripts.validate_full_pipeline import resolve_required_logs
from validation.nl_corpus import CORPUS


class ValidationWorkflowTests(unittest.TestCase):
    def test_gold_corpus_has_exact_category_contract(self):
        self.assertEqual(len(CORPUS), 96)
        self.assertEqual(len({item["case_id"] for item in CORPUS}), 96)
        self.assertEqual(
            Counter(item["category"] for item in CORPUS),
            {
                "execution_mode": 12, "scope": 12, "parameters": 8, "conflict": 8,
                "invalid_or_missing": 8, "report": 6, "noisy_bilingual": 6,
                "medical_semantics": 12, "coverage_gap": 24,
            },
        )
        self.assertTrue(all(item["natural_language"].strip() for item in CORPUS))
        self.assertTrue(all("expected" in item for item in CORPUS))

    def test_selected_real_cases_cover_exact_and_boundary_atlas_rules(self):
        self.assertEqual(len(SELECTED), 8)
        self.assertEqual({item[2] for item in SELECTED}, {25, 27, 29, 31, 33, 35})
        self.assertIn("nearest_from_36w", {item[3] for item in SELECTED})
        self.assertIn("nearest_from_38w", {item[3] for item in SELECTED})

    def test_atlas_selection_metadata_survives_request_and_plan(self):
        request = coordinate(
            "38周病例使用最近的35周图谱。",
            {"atlas_week": 35, "atlas_rule": "nearest_from_38w", "explicit_fields": ["atlas_week", "atlas_rule"]},
        )
        task_plan = plan(request)
        self.assertEqual(request.atlas_week, 35)
        self.assertEqual(task_plan.atlas_week, 35)
        self.assertEqual(task_plan.atlas_rule, "nearest_from_38w")

    def test_roi_display_scope_handles_chinese_boundary(self):
        request = coordinate("导入已有run，展示ROI，只报告registration。", {
            "execution_mode": "import_existing", "existing_run_dir": "/tmp/run",
        })
        self.assertEqual(request.display_steps, ["roi"])
        self.assertEqual(request.report_steps, ["registration"])

    def test_disabled_surface_is_not_executed(self):
        request = coordinate("使用NiftyMIC重建并关闭surface。", {
            "execution_mode": "run_pipeline", "subject_dir": "/tmp", "work_root": "/tmp/work",
            "atlas": "/tmp/atlas", "gestational_age": 31,
        })
        self.assertEqual(request.surface, "off")
        self.assertNotIn("surface", request.execution_steps)

    def test_medical_normality_request_keeps_technical_work_and_boundary(self):
        request = coordinate("帮我重建这个case并给出相关指标，判断是否正常？", {
            "execution_mode": "run_pipeline", "subject_dir": "/tmp", "work_root": "/tmp/work",
            "atlas": "/tmp/atlas", "gestational_age": 31,
        })
        self.assertEqual(request.execution_steps, ["reconstruction", "roi"])
        self.assertIn("metrics", request.requested_outputs)
        self.assertIn("normality_assessment_requires_validated_GA_reference_and_expert_review", request.unfulfilled_requests)

    def test_real_manifest_never_writes_to_public_dataset(self):
        root = Path("/tmp/autorecon-validation-test")
        manifest = real_run_manifest(root)
        self.assertEqual(len({item["dashboard_port"] for item in manifest["cases"]}), 8)
        self.assertLessEqual(len({item["gpu"] for item in manifest["cases"]}), 2)
        for item in manifest["cases"]:
            self.assertTrue(Path(item["source_dir"]).is_relative_to(DATASET_ROOT / "nii"))
            self.assertTrue(Path(item["atlas"]).is_relative_to(ATLAS_ROOT))
            self.assertTrue(Path(item["work_root"]).is_relative_to(root))
            self.assertFalse(Path(item["work_root"]).is_relative_to(DATASET_ROOT))

    def test_llm_report_rejects_unsupported_number(self):
        evidence = {"subject": "CaseA", "volume_ml": 12.5}
        self.assertEqual(validate_llm_report("体积为 12.5 mL。", evidence), [])
        self.assertEqual(validate_llm_report("体积为 12.50 mL。", evidence), [])
        self.assertEqual(validate_llm_report("总体积为 14,066.6 mm³。", {"volume_mm3": 14066.6}), [])
        self.assertEqual(validate_llm_report("Mattes 为 −0.40。", {"mattes": -0.40}), [])
        self.assertIn("unsupported numeric claims", validate_llm_report("体积为 99.9 mL。", evidence)[0])

    def test_llm_report_rejects_affirmative_clinical_claim(self):
        errors = validate_llm_report("胎儿脑部正常。", {"technical_status": "pass"})
        self.assertTrue(any("clinical claim" in item for item in errors))
        self.assertEqual(
            validate_llm_report("This technical report is not a clinical diagnosis.", {}),
            [],
        )
        self.assertEqual(validate_llm_report("当前无法判断胎儿脑是否正常或异常。", {}), [])

    def test_chinese_report_requires_language_boundary_and_refusals(self):
        valid = (
            "## 技术结论\n" + "本报告仅汇总已有技术证据。" * 8
            + "\n## 能力边界\n不得替代临床诊断。\n## 未完成与拒绝\n> [!refusal]\n> **未发送到医院系统**\n## 阅片复核清单\n- [ ] 目视复核配准 overlay"
        )
        self.assertEqual(validate_chinese_report(valid, ["未发送到医院系统"]), [])
        errors = validate_chinese_report("English technical report.", ["未发送到医院系统"])
        self.assertTrue(any("not predominantly Chinese" in item for item in errors))
        self.assertTrue(any("能力边界" in item for item in errors))
        self.assertTrue(any("未发送到医院系统" in item for item in errors))

    def test_llm_evidence_compaction_preserves_metrics_not_local_paths(self):
        compacted = compact_llm_evidence({
            "subject": "CaseA",
            "metric": {"value": 12.5, "source": "/private/results/metric.csv"},
            "path": "/private/results/output.nii.gz",
            "atlas": "/private/atlas/31w.nii.gz",
        })
        self.assertEqual(compacted["metric"], {"value": 12.5})
        self.assertNotIn("path", compacted)
        self.assertEqual(compacted["atlas"], "31w.nii.gz")

    def test_strict_validator_accepts_dashboard_log_location(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, step in enumerate(("extraction", "reconstruction", "registration", "tissue", "roi", "surface"), 1):
                path = root / "dashboard/logs" / f"{index:02d}_{step}.log"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("completed\n")
            resolved = resolve_required_logs(root)
            self.assertTrue(all(path.parent == root / "dashboard/logs" for path in resolved))


if __name__ == "__main__":
    unittest.main()

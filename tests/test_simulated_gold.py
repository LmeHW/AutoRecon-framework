import unittest

from validation.simulated_gold import BEST_METHOD, NORMALITY, infer_scene, label_expected
from agentic.capability_catalog import BEST_METHOD as BEST
from agentic.capability_catalog import NORMALITY as NORM


class SimulatedGoldTests(unittest.TestCase):
    def test_open_existing_is_import_with_no_compute(self) -> None:
        text = "打开这例做好的重建，我只看体积，不要重新计算。"
        self.assertEqual(infer_scene(text), "import")
        expected = label_expected(text)
        self.assertEqual(expected["execution_mode"], "import_existing")
        self.assertEqual(expected["execution_steps"], [])

    def test_continue_registration_does_not_restart(self) -> None:
        text = "上一班断在三维重建。这例接着做配准，不要从头再来。"
        self.assertEqual(infer_scene(text), "continue")
        self.assertEqual(label_expected(text)["execution_steps"], ["registration"])

    def test_skip_alignment_stops_at_volume(self) -> None:
        text = "先把脑提出来并做出三维体积，配准先别做。"
        expected = label_expected(text)
        self.assertEqual(expected["execution_mode"], "run_pipeline")
        self.assertEqual(expected["execution_steps"], ["reconstruction"])

    def test_do_not_diagnose_is_not_a_refusal_request(self) -> None:
        text = "这例从原始图像做到配准。技术报告写覆盖和运动，不要写正常或异常。"
        expected = label_expected(text)
        self.assertNotIn(NORM, expected.get("unfulfilled_requests_contains", []))
        self.assertEqual(expected["execution_steps"], ["registration"])

    def test_named_backend_and_best_method_refusal(self) -> None:
        text = "FROST 和 NeSVoR 都给这例重建一遍，告诉我哪个最好。"
        expected = label_expected(text)
        self.assertNotIn("reconstruction_tool", expected)
        self.assertIn(BEST, expected["unfulfilled_requests_contains"])
        self.assertEqual(expected["execution_steps"], ["reconstruction"])

    def test_constants_match_catalog(self) -> None:
        self.assertEqual(NORMALITY, NORM)
        self.assertEqual(BEST_METHOD, BEST)


if __name__ == "__main__":
    unittest.main()

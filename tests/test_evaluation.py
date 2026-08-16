import unittest
from pathlib import Path
from specatom_hs.evaluation import evaluate_plain

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "evaluation"


class EvaluationTests(unittest.TestCase):
    def test_full_reference_chain_is_traceable_and_truthfully_labeled(self):
        result = evaluate_plain((EXAMPLES / "01_greeting.plain").read_text())
        self.assertEqual(0, result["sandbox"]["python"]["exit_code"])
        self.assertEqual(0, result["sandbox"]["metta"]["exit_code"])
        self.assertEqual("passing", result["traceability"]["entries"][0]["status"])
        self.assertIn("behavior validated", result["labels"]["metta"])
        self.assertTrue(result["outputs"]["metta_balanced"])
        self.assertTrue(result["claim_evidence"]["metta"]["executed"])
        self.assertTrue(result["claim_evidence"]["metta"]["runtime_validated"])
        self.assertTrue(result["claim_evidence"]["python"]["executed"])
        self.assertTrue(result["claim_evidence"]["python"]["tested"])
        self.assertEqual("traceability-report", result["artifacts"][-1]["kind"])

    def test_each_graduated_example_has_substantive_behavioral_assertions(self):
        expected = {
            "01_greeting.plain": ("greeting-trace-v1", 2, "trace-123"),
            "02_task_list.plain": ("task-validation-owner-v1", 3, "missing-name"),
            "03_forecast.plain": ("forecast-split-horizon-baseline-v1", 4, "seasonal-naive"),
        }
        for filename, (profile, count, output_marker) in expected.items():
            with self.subTest(filename=filename):
                result = evaluate_plain((EXAMPLES / filename).read_text())
                validation = result["semantic_validation"]
                self.assertEqual(profile, validation["profile"])
                self.assertTrue(validation["passed"])
                self.assertEqual(count, len(validation["assertions"]))
                self.assertEqual(profile, result["claim_evidence"]["behavior_profile"])
                self.assertEqual(count, len(result["claim_evidence"]["behavior_assertions"]))
                self.assertIn(output_marker, result["sandbox"]["python"]["stdout"])
                self.assertTrue(result["sandbox"]["metta"]["output_matches"])

    def test_unknown_or_reworded_spec_executes_but_is_not_semantically_validated(self):
        result = evaluate_plain("***requirements***\n- [id:REQ-1] Reply.\n")
        self.assertEqual(0, result["sandbox"]["python"]["exit_code"])
        self.assertEqual(0, result["sandbox"]["metta"]["exit_code"])
        self.assertFalse(result["semantic_validation"]["supported"])
        self.assertFalse(result["claim_evidence"]["metta"]["semantically_validated"])
        self.assertEqual("failing", result["traceability"]["entries"][0]["status"])

    def test_blank_and_oversize_inputs_fail_closed(self):
        for source in ("", "x" * 128001):
            with self.subTest(size=len(source)), self.assertRaises(ValueError):
                evaluate_plain(source)

    def test_missing_and_duplicate_requirement_ids_fail_closed(self):
        invalid = (
            "***requirements***\n- Reply.\n",
            "***requirements***\n- [id:REQ-1] Reply.\n- [id:REQ-1] Log.\n",
        )
        for source in invalid:
            with self.subTest(source=source), self.assertRaises(ValueError):
                evaluate_plain(source)

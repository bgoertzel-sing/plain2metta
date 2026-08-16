import unittest
from specatom_hs.evaluation import evaluate_plain


class EvaluationTests(unittest.TestCase):
    def test_full_reference_chain_is_traceable_and_truthfully_labeled(self):
        result = evaluate_plain("***requirements***\n- [id:REQ-1] Reply.\n")
        self.assertEqual(0, result["sandbox"]["exit_code"])
        self.assertEqual("passing", result["traceability"]["entries"][0]["status"])
        self.assertIn("not runtime-validated", result["labels"]["metta"])
        self.assertTrue(result["outputs"]["metta_balanced"])
        self.assertEqual("traceability-report", result["artifacts"][-1]["kind"])

    def test_blank_and_oversize_inputs_fail_closed(self):
        for source in ("", "x" * 128001):
            with self.subTest(size=len(source)), self.assertRaises(ValueError):
                evaluate_plain(source)

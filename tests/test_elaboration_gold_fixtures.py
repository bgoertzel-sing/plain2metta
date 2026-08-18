import json
import unittest
from pathlib import Path

from specatom_hs.elaboration_admission import validate_elaboration_outputs
from specatom_hs.elaboration_protocol import requirement_test_coverage
from specatom_hs.passes import compile_source
from specatom_hs.schema import Role


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "elaboration"


class GoldElaborationFixtureTests(unittest.TestCase):
    def test_auth_and_ml_gold_fixtures_have_exact_requirement_coverage(self):
        expected = {"auth_service": 6, "ml_timeseries": 5}
        for name, count in expected.items():
            with self.subTest(name=name):
                elaborated = (FIXTURES / f"{name}.elaborated.plain").read_text()
                tests = (FIXTURES / f"{name}.tests.plain").read_text()
                requirements, covered = requirement_test_coverage(elaborated, tests)
                self.assertEqual(count, len(requirements))
                self.assertEqual(requirements, covered)
                self.assertNotIn("```", elaborated + tests)

    def test_coverage_fails_closed_for_missing_duplicate_and_unknown_ids(self):
        with self.assertRaises(ValueError):
            requirement_test_coverage("- [id:R1] a\n- [id:R1] b", "- [covers:R1] test")
        with self.assertRaises(ValueError):
            requirement_test_coverage("- [id:R1] a", "- [covers:R2] test")
        requirements, covered = requirement_test_coverage("- [id:R1] a", "***system tests***\n")
        self.assertEqual(("R1",), requirements)
        self.assertEqual((), covered)

    def test_gold_fixtures_replay_through_real_validator_and_retain_declared_questions(self):
        for stem in ("auth_service", "ml_timeseries"):
            with self.subTest(stem=stem):
                elaborated = (FIXTURES / f"{stem}.elaborated.plain").read_text()
                tests = (FIXTURES / f"{stem}.tests.plain").read_text()
                disposition = json.loads((FIXTURES / f"{stem}.disposition.json").read_text())
                self.assertEqual(
                    {"schema", "admission", "retained_blocking_questions"}, set(disposition),
                )
                self.assertEqual("plain2metta-gold-disposition/v1", disposition["schema"])
                self.assertEqual("reject", disposition["admission"])
                self.assertIsInstance(disposition["retained_blocking_questions"], list)
                self.assertTrue(disposition["retained_blocking_questions"])

                summary, duplicate_summary = validate_elaboration_outputs(elaborated, tests, stem)
                self.assertEqual(summary, duplicate_summary)
                self.assertGreater(summary.blocking_questions, 0)
                self.assertTrue(summary.fail_count or summary.blocking_questions)

                combined = f"{elaborated.rstrip()}\n\n{tests.lstrip()}"
                document = compile_source(combined, f"{stem}.phase2.plain")
                explicit_questions = {
                    fact[2]
                    for obj in document.objects
                    if obj.role is Role.QUESTION_OBJECT
                    for fact in obj.facts
                    if len(fact) == 3
                    and fact[0] == "QuestionText"
                    and any(item[0] == "ExplicitQuestion" for item in obj.facts)
                    and any(item[0] == "Blocks" for item in obj.facts)
                }
                self.assertEqual(
                    set(disposition["retained_blocking_questions"]), explicit_questions,
                )


if __name__ == "__main__":
    unittest.main()

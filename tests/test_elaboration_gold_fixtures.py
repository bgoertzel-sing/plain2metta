import unittest
from pathlib import Path

from specatom_hs.elaboration_protocol import requirement_test_coverage


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


if __name__ == "__main__":
    unittest.main()

import unittest

from specatom_hs.backends.petta import emit_reified_atoms
from specatom_hs.passes import compile_source
from specatom_hs.schema import CheckStatus, Role


class RequirementCoverageTests(unittest.TestCase):
    def test_requirement_with_acceptance_test_gets_pass_coverage_and_export_atoms(self):
        doc = compile_source(
            "***requirements***\n"
            "- The [ref:Task] must be visible after creation.\n"
            "***acceptance tests***\n"
            "- Given a [ref:Task], when it is created, then it is visible.\n",
            "covered.plain",
        )

        req = next(obj for obj in doc.objects if obj.role == Role.REQUIREMENT_OBJECT)
        test = next(obj for obj in doc.objects if obj.role == Role.VALIDATION_OBJECT)
        self.assertIn(("Covers", test.id, req.id), test.facts)
        self.assertTrue(
            any(c.property == "requirement-has-acceptance-test" and c.target_id == req.id and c.status == CheckStatus.PASS for c in doc.checks)
        )

        atoms, refusals = emit_reified_atoms(doc)
        self.assertTrue(any(r.object_id and r.object_id.startswith("obj-") for r in refusals))
        expected = {
            f"(Requirement {req.id})",
            f"(TestKind {test.id} Acceptance)",
            f"(Covers {test.id} {req.id})",
        }
        self.assertTrue(expected.issubset(set(atoms)))

    def test_requirement_without_acceptance_test_gets_unknown_and_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- The [def:Task] must be visible after creation.\n",
            "uncovered.plain",
        )

        req = next(obj for obj in doc.objects if obj.role == Role.REQUIREMENT_OBJECT)
        self.assertTrue(
            any(c.property == "requirement-has-acceptance-test" and c.target_id == req.id and c.status == CheckStatus.UNKNOWN for c in doc.checks)
        )
        questions = [obj for obj in doc.objects if obj.role == Role.QUESTION_OBJECT]
        self.assertTrue(any(("MissingAcceptanceTest", q.id, req.id) in q.facts for q in questions))


if __name__ == "__main__":
    unittest.main()

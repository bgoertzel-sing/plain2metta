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

    def test_explicit_coverage_labels_override_proximity_and_export_ground_truth(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R1] The [def:Task] must be visible after creation.\n"
            "- [id:R2] The task list must support archival.\n"
            "***acceptance tests***\n"
            "- [covers:R1] Given a [ref:Task], when it is created, then it is visible.\n",
            "explicit-coverage.plain",
        )

        labelled = {
            next(fact[2] for fact in obj.facts if fact[0] == "RequirementLabel"): obj
            for obj in doc.objects
            if obj.role == Role.REQUIREMENT_OBJECT
        }
        test = next(obj for obj in doc.objects if obj.role == Role.VALIDATION_OBJECT)
        self.assertIn(("CoverageClaim", test.id, "R1"), test.facts)
        self.assertIn(("Covers", test.id, labelled["R1"].id), test.facts)
        self.assertNotIn(("Covers", test.id, labelled["R2"].id), test.facts)

        atoms, _ = emit_reified_atoms(doc)
        expected = {
            f"(RequirementLabel {labelled['R1'].id} R1)",
            f"(CoverageClaim {test.id} R1)",
            f"(Covers {test.id} {labelled['R1'].id})",
        }
        self.assertTrue(expected.issubset(set(atoms)))

    def test_explicit_coverage_label_resolves_forward_requirement_section(self):
        doc = compile_source(
            "***acceptance tests***\n"
            "- [covers:R1] Given a [ref:Task], when it is created, then it is visible.\n"
            "***requirements***\n"
            "- [id:R1] The [def:Task] must be visible after creation.\n",
            "forward-coverage-label.plain",
        )

        req = next(obj for obj in doc.objects if obj.role == Role.REQUIREMENT_OBJECT)
        test = next(obj for obj in doc.objects if obj.role == Role.VALIDATION_OBJECT)
        self.assertIn(("Covers", test.id, req.id), test.facts)
        self.assertFalse(
            any(c.property == "coverage-claim-target-resolved" and c.target_id == f"{test.id}:R1" and c.status == CheckStatus.UNKNOWN for c in doc.checks)
        )
        self.assertTrue(
            any(c.property == "requirement-has-acceptance-test" and c.target_id == req.id and c.status == CheckStatus.PASS for c in doc.checks)
        )

    def test_orphan_acceptance_test_becomes_coverage_question_and_export_atom(self):
        doc = compile_source(
            "***acceptance tests***\n"
            "- Given a task, when it is created, then it is visible.\n",
            "orphan-test.plain",
        )

        test = next(obj for obj in doc.objects if obj.role == Role.VALIDATION_OBJECT)
        self.assertTrue(
            any(c.property == "acceptance-test-covers-requirement" and c.target_id == test.id and c.status == CheckStatus.UNKNOWN for c in doc.checks)
        )
        questions = [obj for obj in doc.objects if obj.role == Role.QUESTION_OBJECT]
        question = next(obj for obj in questions if ("OrphanAcceptanceTest", obj.id, test.id) in obj.facts)
        self.assertTrue(any(fact[0] == "Blocks" and fact[2].startswith("vobl-") for fact in question.facts))

        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn(f"(OrphanAcceptanceTest {question.id} {test.id})", atoms)
        self.assertFalse(any(r.reason.startswith("unsupported-fact-predicate:OrphanAcceptanceTest") for r in refusals))

    def test_unresolved_explicit_coverage_label_becomes_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R1] The [def:Task] must be visible after creation.\n"
            "***acceptance tests***\n"
            "- [covers:R404] Given a [ref:Task], when it is created, then it is visible.\n",
            "missing-coverage-label.plain",
        )

        self.assertTrue(
            any(c.property == "coverage-claim-target-resolved" and c.status == CheckStatus.UNKNOWN for c in doc.checks)
        )
        questions = [obj for obj in doc.objects if obj.role == Role.QUESTION_OBJECT]
        self.assertTrue(any(("MissingCoverageTarget", q.id, "R404") in q.facts for q in questions))

    def test_duplicate_requirement_label_blocks_explicit_coverage_resolution(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R1] The [def:Task] must be visible after creation.\n"
            "- [id:R1] The task list must support archival.\n"
            "***acceptance tests***\n"
            "- [covers:R1] Given a [ref:Task], when it is created, then it is visible.\n",
            "duplicate-coverage-label.plain",
        )

        labelled_requirements = [obj for obj in doc.objects if obj.role == Role.REQUIREMENT_OBJECT]
        test = next(obj for obj in doc.objects if obj.role == Role.VALIDATION_OBJECT)
        for req in labelled_requirements:
            self.assertNotIn(("Covers", test.id, req.id), test.facts)
        self.assertTrue(
            any(c.property == "requirement-label-is-unique" and c.status == CheckStatus.UNKNOWN for c in doc.checks)
        )
        self.assertTrue(
            any(c.property == "coverage-claim-target-resolved" and c.status == CheckStatus.UNKNOWN and "multiple" in c.evidence for c in doc.checks)
        )
        questions = [obj for obj in doc.objects if obj.role == Role.QUESTION_OBJECT]
        self.assertTrue(any(("DuplicateRequirementLabel", q.id, "R1") in q.facts for q in questions))
        self.assertTrue(any(("AmbiguousCoverageTarget", q.id, "R1") in q.facts for q in questions))


if __name__ == "__main__":
    unittest.main()

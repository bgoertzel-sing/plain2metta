import copy
import unittest

from specatom_hs.projects import ArtifactKind, add_artifact, create_project, replace_source
from specatom_hs.review_diff import (
    build_phase3_review_diff,
    phase3_review_diff_from_dict,
    phase3_review_diff_to_dict,
    validate_phase3_review_diff,
)


class Phase3ReviewDiffTests(unittest.TestCase):
    def project(self):
        project = create_project("demo", "Demo", "***requirements***\n- [id:R1] Sketch.\n")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "***requirements***\n- [id:R1] Precise behavior.\n", (source.ref,))
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        return add_artifact(project, ArtifactKind.TEST_SPEC, "***system tests***\n- [covers:R1] Verify behavior.\n", (elaborated.ref,))

    def test_diff_is_deterministic_and_binds_all_exact_inputs(self):
        project = self.project()
        first = build_phase3_review_diff(project)
        self.assertEqual(first, build_phase3_review_diff(project))
        self.assertEqual(project.current(ArtifactKind.ORIGINAL_SPEC).ref, first.original_spec)
        self.assertIn("--- original-spec", first.original_to_elaborated)
        self.assertIn("+++ test-spec", first.test_spec_addition)
        self.assertEqual(first, phase3_review_diff_from_dict(phase3_review_diff_to_dict(first)))

    def test_missing_or_wrong_provenance_fails_closed(self):
        project = create_project("demo", "Demo", "source")
        with self.assertRaisesRegex(ValueError, "requires exact current"):
            build_phase3_review_diff(project)
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "elaborated", (source.ref,))
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = add_artifact(project, ArtifactKind.TEST_SPEC, "tests", (source.ref,))
        with self.assertRaisesRegex(ValueError, "test spec is not bound"):
            build_phase3_review_diff(project)

    def test_stale_and_tampered_reports_fail_closed(self):
        project = self.project()
        report = build_phase3_review_diff(project)
        changed = replace_source(project, "changed")
        with self.assertRaises(ValueError):
            validate_phase3_review_diff(changed, report)
        forged = copy.deepcopy(phase3_review_diff_to_dict(report))
        forged["original_to_elaborated"][-1] = "+fabricated\n"
        with self.assertRaisesRegex(ValueError, "does not match"):
            validate_phase3_review_diff(project, phase3_review_diff_from_dict(forged))

    def test_malformed_and_expanded_serialization_fails_closed(self):
        payload = phase3_review_diff_to_dict(build_phase3_review_diff(self.project()))
        for mutation in (
            lambda value: value.update({"execute": True}),
            lambda value: value["inputs"].update({"alternate": {}}),
            lambda value: value.update({"test_spec_addition": "not-lines"}),
        ):
            with self.subTest(mutation=mutation):
                forged = copy.deepcopy(payload)
                mutation(forged)
                with self.assertRaises(ValueError):
                    phase3_review_diff_from_dict(forged)


if __name__ == "__main__":
    unittest.main()

import copy
import unittest

from specatom_hs.projects import (
    ApprovalDecision,
    ArtifactKind,
    ArtifactState,
    add_artifact,
    add_logical_ir,
    annotate,
    create_project,
    decide,
    project_from_dict,
    project_to_dict,
    replace_source,
)


class ProjectModelTests(unittest.TestCase):
    def populated(self):
        project = create_project("demo", "Demo", "***requirements***\n- old\n")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "elaborated", [source.ref])
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = add_artifact(project, ArtifactKind.TEST_SPEC, "tests", [elaborated.ref])
        return project

    def test_project_and_artifacts_are_immutable_and_content_addressed(self):
        project = create_project("demo", "Demo", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        self.assertTrue(source.content_hash.startswith("sha256:"))
        with self.assertRaises(AttributeError):
            project.name = "changed"

    def test_derived_artifact_requires_exact_current_upstream_hash(self):
        project = create_project("demo", "Demo", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        bad_ref = type(source.ref)(source.artifact_id, "sha256:bad")
        with self.assertRaisesRegex(ValueError, "hash-mismatched"):
            add_artifact(project, ArtifactKind.ELABORATED_SPEC, "output", [bad_ref])

    def test_approval_binds_exact_artifact_version(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        approved = decide(project, elaborated.ref, ApprovalDecision.APPROVED, "ben", "reviewed")
        self.assertEqual(ApprovalDecision.APPROVED, approved.approvals[0].decision)
        with self.assertRaisesRegex(ValueError, "reviewer"):
            decide(project, elaborated.ref, ApprovalDecision.APPROVED)

    def test_source_mutation_transitively_invalidates_derived_state_and_approval(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = decide(project, elaborated.ref, ApprovalDecision.APPROVED, "ben")
        changed = replace_source(project, "***requirements***\n- new\n")
        self.assertEqual(2, changed.current(ArtifactKind.ORIGINAL_SPEC).version)
        self.assertIsNone(changed.current(ArtifactKind.ELABORATED_SPEC))
        self.assertIsNone(changed.current(ArtifactKind.TEST_SPEC))
        self.assertTrue(all(a.state is ArtifactState.INVALIDATED for a in changed.artifacts[:-1]))
        self.assertEqual(ApprovalDecision.INVALIDATED, changed.approvals[0].decision)

    def test_identical_source_is_a_noop(self):
        project = create_project("demo", "Demo", "source")
        self.assertIs(project, replace_source(project, "source"))

    def test_new_derived_version_invalidates_old_version_and_downstream(self):
        project = self.populated()
        old_elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = decide(project, old_elaborated.ref, ApprovalDecision.APPROVED, "ben")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        changed = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "revised", [source.ref])
        self.assertEqual(2, changed.current(ArtifactKind.ELABORATED_SPEC).version)
        self.assertIsNone(changed.current(ArtifactKind.TEST_SPEC))
        self.assertEqual(ArtifactState.INVALIDATED, changed.artifact(old_elaborated.artifact_id).state)
        self.assertEqual(ApprovalDecision.INVALIDATED, changed.approvals[0].decision)

    def test_round_trip_is_stable(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = decide(project, elaborated.ref, ApprovalDecision.CHANGES_REQUESTED, "reviewer", "clarify")
        project = annotate(project, elaborated.ref, "reviewer", "Clarify this section.", "section:requirements")
        self.assertEqual(project, project_from_dict(project_to_dict(project)))

    def test_annotations_bind_exact_current_artifact_and_survive_invalidation_as_history(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = annotate(project, elaborated.ref, "ben", "Define the boundary.", "item:PRED-1")
        self.assertEqual("item:PRED-1", project.annotations[0].target)
        changed = replace_source(project, "changed")
        self.assertEqual(project.annotations, changed.annotations)
        with self.assertRaisesRegex(ValueError, "exact current"):
            annotate(changed, elaborated.ref, "ben", "stale")

    def test_annotations_reject_malformed_review_fields(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        for reviewer, comment, target in (("", "note", None), ("ben", " ", None), ("ben", "note", " ")):
            with self.subTest(reviewer=reviewer, comment=comment, target=target):
                with self.assertRaises(ValueError):
                    annotate(project, elaborated.ref, reviewer, comment, target)

    def test_logical_ir_requires_both_exact_current_approvals(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        tests = project.current(ArtifactKind.TEST_SPEC)
        with self.assertRaisesRegex(ValueError, "explicit approval"):
            add_logical_ir(project, "logical")
        project = decide(project, elaborated.ref, ApprovalDecision.APPROVED, "ben")
        with self.assertRaisesRegex(ValueError, "explicit approval"):
            add_logical_ir(project, "logical")
        project = decide(project, tests.ref, ApprovalDecision.APPROVED, "ben")
        project = add_logical_ir(project, "logical")
        logical = project.current(ArtifactKind.LOGICAL_IR)
        self.assertEqual((elaborated.ref, tests.ref), logical.upstream)

    def test_generic_artifact_api_cannot_bypass_logical_ir_review_gate(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        with self.assertRaisesRegex(ValueError, "add_logical_ir"):
            add_artifact(project, ArtifactKind.LOGICAL_IR, "logical", [elaborated.ref])

    def test_revoking_input_approval_invalidates_logical_ir(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        tests = project.current(ArtifactKind.TEST_SPEC)
        project = decide(project, elaborated.ref, ApprovalDecision.APPROVED, "ben")
        project = decide(project, tests.ref, ApprovalDecision.APPROVED, "ben")
        project = add_logical_ir(project, "logical")
        logical = project.current(ArtifactKind.LOGICAL_IR)
        changed = decide(project, elaborated.ref, ApprovalDecision.CHANGES_REQUESTED, "ben", "revise")
        self.assertIsNone(changed.current(ArtifactKind.LOGICAL_IR))
        self.assertEqual(ArtifactState.INVALIDATED, changed.artifact(logical.artifact_id).state)

    def test_deserialization_rejects_logical_ir_without_approvals(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        tests = project.current(ArtifactKind.TEST_SPEC)
        project = decide(project, elaborated.ref, ApprovalDecision.APPROVED, "ben")
        project = decide(project, tests.ref, ApprovalDecision.APPROVED, "ben")
        payload = project_to_dict(add_logical_ir(project, "logical"))
        payload["approvals"] = []
        with self.assertRaisesRegex(ValueError, "lacks exact input approvals"):
            project_from_dict(payload)

    def test_deserialization_rejects_mutated_content(self):
        payload = project_to_dict(create_project("demo", "Demo", "source"))
        payload["artifacts"][0]["content"] = "tampered"
        with self.assertRaisesRegex(ValueError, "invalid content hash"):
            project_from_dict(payload)

    def test_deserialization_rejects_unknown_enums_and_missing_fields(self):
        payload = project_to_dict(create_project("demo", "Demo", "source"))
        payload["artifacts"][0]["state"] = "maybe"
        with self.assertRaisesRegex(ValueError, "malformed project state"):
            project_from_dict(payload)
        missing = project_to_dict(create_project("demo", "Demo", "source"))
        del missing["artifacts"][0]["content_hash"]
        with self.assertRaisesRegex(ValueError, "malformed project state"):
            project_from_dict(missing)

    def test_deserialization_rejects_forged_approval_binding(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        payload = project_to_dict(decide(project, elaborated.ref, ApprovalDecision.APPROVED, "ben"))
        payload["approvals"][0]["artifact"]["content_hash"] = "sha256:forged"
        with self.assertRaisesRegex(ValueError, "approval hash mismatch"):
            project_from_dict(payload)

    def test_deserialization_rejects_forged_or_malformed_annotation(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = annotate(project, elaborated.ref, "ben", "review", "item:PRED-1")
        forged = project_to_dict(project)
        forged["annotations"][0]["artifact"]["content_hash"] = "sha256:forged"
        with self.assertRaisesRegex(ValueError, "annotation hash mismatch"):
            project_from_dict(forged)
        malformed = project_to_dict(project)
        malformed["annotations"][0]["comment"] = " "
        with self.assertRaisesRegex(ValueError, "comment is blank"):
            project_from_dict(malformed)


if __name__ == "__main__":
    unittest.main()

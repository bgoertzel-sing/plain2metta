import copy
import unittest

from specatom_hs.projects import (
    ApprovalDecision,
    ArtifactKind,
    ArtifactState,
    add_artifact,
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
        self.assertEqual(project, project_from_dict(project_to_dict(project)))

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


if __name__ == "__main__":
    unittest.main()

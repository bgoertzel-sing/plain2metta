import tempfile
import unittest
from pathlib import Path

from specatom_hs.project_commands import ProjectCommandService
from specatom_hs.project_repository import FilesystemProjectRepository
from specatom_hs.projects import ApprovalDecision, ArtifactKind, add_logical_ir_document
from specatom_hs.phase3_review import Phase3Decision, Phase3ReviewLog
from specatom_hs.logical_ir import FindingDisposition, LogicalIRDocument, RequirementObligation, TypeDeclaration


class ProjectCommandServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = FilesystemProjectRepository(Path(self.temporary.name) / "projects")
        self.commands = ProjectCommandService(self.repository)

    def tearDown(self):
        self.temporary.cleanup()

    def test_create_project_is_immediately_persisted(self):
        created = self.commands.create_project("demo", "Demo", "source")
        self.assertEqual(created, self.repository.get("demo"))
        with self.assertRaises(FileExistsError):
            self.commands.create_project("demo", "Other", "source")

    def test_exact_annotation_is_persisted(self):
        project = self.commands.create_project("demo", "Demo", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        updated = self.commands.add_annotation(
            "demo", source.artifact_id, source.content_hash,
            "reviewer", "Clarify this clause.", "item:REQ-1",
        )
        self.assertEqual(updated, self.repository.get("demo"))
        self.assertEqual("item:REQ-1", updated.annotations[0].target)

    def test_exact_review_decision_is_persisted(self):
        project = self.commands.create_project("demo", "Demo", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        updated = self.commands.submit_decision(
            "demo", source.artifact_id, source.content_hash,
            "approved", "reviewer", "Reviewed exact bytes.",
        )
        self.assertEqual(updated, self.repository.get("demo"))
        self.assertEqual(ApprovalDecision.APPROVED, updated.approvals[0].decision)

    def test_exact_upstream_elaborated_and_test_specs_are_persisted(self):
        project = self.commands.create_project("demo", "Demo", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = self.commands.submit_elaborated_spec(
            "demo", source.artifact_id, source.content_hash, "elaborated"
        )
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = self.commands.submit_test_spec(
            "demo", elaborated.artifact_id, elaborated.content_hash, "tests"
        )
        self.assertEqual(project, self.repository.get("demo"))
        self.assertEqual((source.ref,), elaborated.upstream)
        self.assertEqual((elaborated.ref,), project.current(ArtifactKind.TEST_SPEC).upstream)

    def test_exact_phase3_review_transaction_is_persisted(self):
        project = self.commands.create_project("demo", "Demo", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = self.commands.submit_elaborated_spec("demo", source.artifact_id, source.content_hash, "elaborated")
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = self.commands.submit_test_spec("demo", elaborated.artifact_id, elaborated.content_hash, "tests")
        tests = project.current(ArtifactKind.TEST_SPEC)
        log = Phase3ReviewLog(elaborated.ref, tests.ref, (
            Phase3Decision(elaborated.ref, ApprovalDecision.APPROVED, "alice", "2026-08-14T12:25:00Z"),
            Phase3Decision(tests.ref, ApprovalDecision.APPROVED, "bob", "2026-08-14T12:26:00Z"),
        ))
        updated = self.commands.submit_phase3_review("demo", log)
        self.assertEqual(updated, self.repository.get("demo"))
        self.assertIsNotNone(updated.current(ArtifactKind.REVIEWED_ELABORATED_SPEC))
        self.assertIsNotNone(updated.current(ArtifactKind.REVIEWED_TEST_SPEC))

    def test_spec_submission_rejects_stale_hash_wrong_kind_and_missing_stage_without_write(self):
        project = self.commands.create_project("demo", "Demo", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        before = self.repository.get("demo")
        with self.assertRaises(ValueError):
            self.commands.submit_elaborated_spec("demo", source.artifact_id, "sha256:" + "0" * 64, "x")
        with self.assertRaises(ValueError):
            self.commands.submit_test_spec("demo", source.artifact_id, source.content_hash, "tests")
        self.assertEqual(before, self.repository.get("demo"))

        project = self.commands.submit_elaborated_spec(
            "demo", source.artifact_id, source.content_hash, "first"
        )
        old = project.current(ArtifactKind.ELABORATED_SPEC)
        project = self.commands.submit_elaborated_spec(
            "demo", source.artifact_id, source.content_hash, "second"
        )
        before = self.repository.get("demo")
        with self.assertRaises(ValueError):
            self.commands.submit_test_spec("demo", old.artifact_id, old.content_hash, "tests")
        self.assertEqual(before, self.repository.get("demo"))

    def test_exact_logical_finding_decision_is_persisted_and_stale_ref_fails_without_write(self):
        project = self.commands.create_project("logical", "Logical", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = self.commands.submit_elaborated_spec("logical", source.artifact_id, source.content_hash, "elaborated")
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = self.commands.submit_test_spec("logical", elaborated.artifact_id, elaborated.content_hash, "tests")
        tests = project.current(ArtifactKind.TEST_SPEC)
        project = self.commands.submit_phase3_review("logical", Phase3ReviewLog(elaborated.ref, tests.ref, (
            Phase3Decision(elaborated.ref, ApprovalDecision.APPROVED, "alice", "2026-08-14T13:58:00Z"),
            Phase3Decision(tests.ref, ApprovalDecision.APPROVED, "bob", "2026-08-14T13:58:01Z"),
        )))
        project = add_logical_ir_document(project, LogicalIRDocument(
            "Logical", (TypeDeclaration("type.Value", "Value", ("REQ-1",)),), (),
            (RequirementObligation("REQ-1", (), ("REQ-1",)),), (), (),
        ))
        self.repository.save(project)
        logical = project.current(ArtifactKind.LOGICAL_IR)
        review = project.current(ArtifactKind.LOGICAL_REVIEW)
        import json
        finding_id = json.loads(review.content)["findings"][0]["finding_id"]
        updated = self.commands.submit_logical_finding_decision(
            "logical", logical.artifact_id, logical.content_hash,
            review.artifact_id, review.content_hash, finding_id,
            FindingDisposition.WAIVED.value, "ben", "Accepted for this slice.",
        )
        self.assertEqual(2, updated.current(ArtifactKind.LOGICAL_REVIEW).version)
        before = self.repository.get("logical")
        with self.assertRaisesRegex(ValueError, "exact current logical review"):
            self.commands.submit_logical_finding_decision(
                "logical", logical.artifact_id, logical.content_hash,
                review.artifact_id, review.content_hash, finding_id,
                FindingDisposition.REPAIRED.value, "ben", "Now repaired.",
            )
        self.assertEqual(before, self.repository.get("logical"))

    def test_stale_or_mismatched_artifact_identity_fails_without_write(self):
        project = self.commands.create_project("demo", "Demo", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        before = self.repository.get("demo")
        for artifact_id, digest in (
            ("artifact-missing", source.content_hash),
            (source.artifact_id, "sha256:" + "0" * 64),
        ):
            with self.subTest(artifact_id=artifact_id), self.assertRaises(ValueError):
                self.commands.submit_decision("demo", artifact_id, digest, "approved", "reviewer")
            self.assertEqual(before, self.repository.get("demo"))

    def test_malformed_commands_and_derived_invalidation_fail_closed(self):
        project = self.commands.create_project("demo", "Demo", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        for decision in ("invalidated", "APPROVED", "unknown", 7):
            with self.subTest(decision=decision), self.assertRaises(ValueError):
                self.commands.submit_decision(
                    "demo", source.artifact_id, source.content_hash, decision, "reviewer"
                )
        with self.assertRaises(ValueError):
            self.commands.add_annotation("demo", "", source.content_hash, "reviewer", "comment")
        self.assertEqual(project, self.repository.get("demo"))

    def test_boundary_has_no_generic_or_execution_capabilities(self):
        for name in ("save", "add_artifact", "compile", "execute", "elaborate", "test"):
            self.assertFalse(hasattr(self.commands, name))


if __name__ == "__main__":
    unittest.main()

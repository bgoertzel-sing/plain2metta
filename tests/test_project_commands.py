import tempfile
import unittest
from pathlib import Path

from specatom_hs.project_commands import ProjectCommandService
from specatom_hs.project_repository import FilesystemProjectRepository
from specatom_hs.projects import ApprovalDecision, ArtifactKind


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

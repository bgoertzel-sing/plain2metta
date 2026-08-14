import tempfile
import unittest
from pathlib import Path

from specatom_hs.project_queries import ProjectQueryService
from specatom_hs.project_repository import FilesystemProjectRepository
from specatom_hs.phase3_review import Phase3Decision, Phase3ReviewLog
from specatom_hs.projects import (
    ApprovalDecision, ArtifactKind, add_artifact, add_logical_ir_document,
    replace_source, submit_phase3_review,
)
from specatom_hs.logical_ir import Contract, LogicalIRDocument, RequirementObligation, TypeDeclaration

import tests.test_projects as project_fixtures


class ProjectQueryServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = FilesystemProjectRepository(Path(self.temporary.name) / "projects")
        self.queries = ProjectQueryService(self.repository)

    def tearDown(self):
        self.temporary.cleanup()

    def test_list_and_status_are_read_only_serializable_summaries(self):
        project = self.repository.create("demo", "Demo", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "details", (source.ref,))
        self.repository.save(project)
        status = self.queries.status("demo")
        self.assertEqual("demo", status["project_id"])
        self.assertEqual(("elaborated-spec", "original-spec"), status["current_artifacts"])
        self.assertEqual((status,), self.queries.list_projects())
        self.assertFalse(hasattr(self.queries, "save"))

    def test_version_history_retains_invalidated_metadata_without_content(self):
        project = self.repository.create("demo", "Demo", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "details", (source.ref,))
        project = replace_source(project, "changed")
        self.repository.save(project)
        history = self.queries.version_history("demo")
        self.assertEqual(3, len(history))
        self.assertEqual({"current", "invalidated"}, {item["state"] for item in history})
        self.assertTrue(all("content" not in item for item in history))
        self.assertEqual((source.artifact_id,), next(
            item["upstream_artifact_ids"] for item in history if item["kind"] == "elaborated-spec"
        ))

    def test_phase3_review_is_recomputed_from_exact_current_versions(self):
        project = self.repository.create("demo", "Demo", "sketch\n")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "detailed\n", (source.ref,))
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = add_artifact(project, ArtifactKind.TEST_SPEC, "verify\n", (elaborated.ref,))
        self.repository.save(project)
        report = self.queries.phase3_review("demo")
        self.assertEqual("plain2metta-phase3-review-diff/v1", report["schema"])
        self.assertEqual(source.artifact_id, report["inputs"]["original_spec"]["artifact_id"])
        self.assertNotIn("content", report["inputs"]["original_spec"])
        self.assertFalse(hasattr(self.queries, "approve"))

        self.repository.save(replace_source(project, "changed\n"))
        with self.assertRaisesRegex(ValueError, "requires exact current"):
            self.queries.phase3_review("demo")

    def test_phase3_review_decisions_are_validated_exact_version_metadata(self):
        project = self.repository.create("reviewed", "Reviewed", "sketch\n")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "detailed\n", (source.ref,))
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = add_artifact(project, ArtifactKind.TEST_SPEC, "verify\n", (elaborated.ref,))
        tests = project.current(ArtifactKind.TEST_SPEC)
        log = Phase3ReviewLog(elaborated.ref, tests.ref, (
            Phase3Decision(elaborated.ref, ApprovalDecision.APPROVED, "reviewer-a", "2026-08-14T12:43:00Z"),
            Phase3Decision(tests.ref, ApprovalDecision.CHANGES_REQUESTED, "reviewer-b", "2026-08-14T12:43:01Z", "item:TEST-1", "Tighten assertion."),
        ))
        project = submit_phase3_review(project, log)
        self.repository.save(project)

        result = self.queries.phase3_review_decisions("reviewed")
        artifact = project.current(ArtifactKind.REVIEW_LOG)
        self.assertEqual(artifact.artifact_id, result["review_log_artifact_id"])
        self.assertEqual(artifact.content_hash, result["review_log_content_hash"])
        self.assertEqual("plain2metta-phase3-review-log/v2", result["review_log"]["schema"])
        self.assertEqual(2, len(result["review_log"]["decisions"]))
        self.assertEqual(
            {"elaborated_spec_hash": None, "test_spec_hash": None},
            result["review_log"]["reviewed_outputs"],
        )
        self.assertNotIn("content", result)
        self.assertFalse(hasattr(self.queries, "submit_phase3_review"))

        self.repository.save(replace_source(project, "changed\n"))
        with self.assertRaisesRegex(ValueError, "no current Phase 3 review log"):
            self.queries.phase3_review_decisions("reviewed")

    def test_missing_phase3_review_decisions_fail_closed(self):
        self.repository.create("unreviewed", "Unreviewed", "source")
        with self.assertRaisesRegex(ValueError, "no current Phase 3 review log"):
            self.queries.phase3_review_decisions("unreviewed")

    def test_logical_review_is_validated_exact_version_metadata_without_ir_body(self):
        project = self.repository.create("logical", "Logical", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "elaborated", (source.ref,))
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = add_artifact(project, ArtifactKind.TEST_SPEC, "tests", (elaborated.ref,))
        tests = project.current(ArtifactKind.TEST_SPEC)
        project = submit_phase3_review(project, Phase3ReviewLog(elaborated.ref, tests.ref, (
            Phase3Decision(elaborated.ref, ApprovalDecision.APPROVED, "alice", "2026-08-14T13:58:00Z"),
            Phase3Decision(tests.ref, ApprovalDecision.APPROVED, "bob", "2026-08-14T13:58:01Z"),
        )))
        project = add_logical_ir_document(project, LogicalIRDocument(
            "Logical", (TypeDeclaration("type.Value", "Value", ("REQ-1",)),),
            (Contract("contract.work", "work", ("Value",), "Value", (), (), (), ("REQ-1",), False),),
            (RequirementObligation("REQ-1", (), ("REQ-1",)),), (), (),
        ))
        self.repository.save(project)

        result = self.queries.logical_review("logical")
        logical = project.current(ArtifactKind.LOGICAL_IR)
        review = project.current(ArtifactKind.LOGICAL_REVIEW)
        self.assertEqual(logical.artifact_id, result["logical_ir_artifact_id"])
        self.assertEqual(review.content_hash, result["logical_review_content_hash"])
        self.assertTrue(result["logical_review"]["blocks_compilation"])
        self.assertEqual(1, len(result["logical_review"]["findings"]))
        self.assertNotIn("content", result)
        self.assertNotIn("logical_ir", result)

        self.repository.save(replace_source(project, "changed"))
        with self.assertRaisesRegex(ValueError, "no current logical IR review"):
            self.queries.logical_review("logical")

    def test_missing_logical_review_fails_closed(self):
        self.repository.create("no-logical", "No logical", "source")
        with self.assertRaisesRegex(ValueError, "no current logical IR review"):
            self.queries.logical_review("no-logical")

    def test_trace_supports_full_and_exact_spec_queries(self):
        project = project_fixtures.ProjectModelTests().traceability_project()
        project = project_fixtures.add_traceability_report(project)
        self.repository.create("demo", "Demo", "placeholder")
        self.repository.save(project)
        full = self.queries.trace("demo")
        self.assertEqual("demo", full["project_id"])
        self.assertGreaterEqual(len(full["entries"]), 1)
        spec_id = full["entries"][0]["spec_id"]
        filtered = self.queries.trace("demo", spec_id)
        self.assertEqual((spec_id,), tuple(item["spec_id"] for item in filtered["entries"]))
        with self.assertRaises(KeyError):
            self.queries.trace("demo", "REQ-unknown")

    def test_missing_trace_and_malformed_query_fail_closed(self):
        self.repository.create("demo", "Demo", "source")
        with self.assertRaisesRegex(ValueError, "no current traceability"):
            self.queries.trace("demo")
        for value in ("", " ", 7):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.queries.trace("demo", value)
        with self.assertRaises(ValueError):
            self.queries.status("../escape")


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from specatom_hs.project_queries import ProjectQueryService
from specatom_hs.project_repository import FilesystemProjectRepository
from specatom_hs.projects import ArtifactKind, add_artifact, replace_source

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

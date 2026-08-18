import tempfile
import unittest
from pathlib import Path

from specatom_hs.project_queries import ProjectQueryService
from specatom_hs.project_repository import FilesystemProjectRepository
from specatom_hs.projects import ArtifactKind, replace_source

import tests.test_projects as project_fixtures


class Plain2MettaV2EndToEndTests(unittest.TestCase):
    """Provider-free acceptance replay of the immutable Phase 2--7 chain."""

    def test_exact_chain_survives_persistence_and_is_queryable_without_bodies(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = FilesystemProjectRepository(Path(temporary) / "projects")
            project = project_fixtures.add_traceability_report(
                project_fixtures.ProjectModelTests().traceability_project()
            )
            repository.create(project.project_id, project.name, "placeholder")
            repository.save(project)

            reloaded = repository.get(project.project_id)
            expected = (
                ArtifactKind.ORIGINAL_SPEC,
                ArtifactKind.ELABORATED_SPEC,
                ArtifactKind.TEST_SPEC,
                ArtifactKind.REVIEWED_ELABORATED_SPEC,
                ArtifactKind.REVIEWED_TEST_SPEC,
                ArtifactKind.LOGICAL_IR,
                ArtifactKind.COMPILER_OUTPUT,
                ArtifactKind.SANDBOX_HANDOFF,
                ArtifactKind.TEST_RESULT,
                ArtifactKind.TRACEABILITY_REPORT,
            )
            self.assertTrue(all(reloaded.current(kind) is not None for kind in expected))

            report = ProjectQueryService(repository).trace(project.project_id)
            self.assertEqual(project.project_id, report["project_id"])
            self.assertEqual(9, len(report["provenance"]))
            serialized = str(report).lower()
            for forbidden in ("generated, not executed", "raise runtimeerror", "ok\\n"):
                self.assertNotIn(forbidden, serialized)

    def test_upstream_mutation_invalidates_every_derived_phase(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = FilesystemProjectRepository(Path(temporary) / "projects")
            project = project_fixtures.add_traceability_report(
                project_fixtures.ProjectModelTests().traceability_project()
            )
            repository.create(project.project_id, project.name, "placeholder")
            repository.save(project)

            repository.save(replace_source(repository.get(project.project_id), "changed source\n"))
            changed = repository.get(project.project_id)
            for kind in ArtifactKind:
                if kind is not ArtifactKind.ORIGINAL_SPEC:
                    self.assertIsNone(changed.current(kind), kind.value)
            with self.assertRaises(ValueError):
                ProjectQueryService(repository).trace(project.project_id)


if __name__ == "__main__":
    unittest.main()

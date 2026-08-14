import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from specatom_hs.project_repository import FilesystemProjectRepository
from specatom_hs.projects import (
    ApprovalDecision,
    ArtifactKind,
    add_artifact,
    decide,
    project_to_dict,
    replace_source,
)


class FilesystemProjectRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "projects"
        self.repository = FilesystemProjectRepository(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_create_get_and_list_status(self):
        created = self.repository.create("demo-project", "Demo", "source")
        self.assertEqual(created, self.repository.get("demo-project"))
        statuses = self.repository.list_statuses()
        self.assertEqual(("demo-project",), tuple(status.project_id for status in statuses))
        self.assertEqual((ArtifactKind.ORIGINAL_SPEC,), statuses[0].current_artifacts)

    def test_save_round_trips_derived_and_approval_state(self):
        project = self.repository.create("demo", "Demo", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "details", [source.ref])
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = decide(project, elaborated.ref, ApprovalDecision.APPROVED, "reviewer")
        self.repository.save(project)
        self.assertEqual(project, self.repository.get("demo"))
        self.assertEqual(1, self.repository.list_statuses()[0].approved_artifact_count)

    def test_saved_source_change_persists_transitive_invalidation(self):
        project = self.repository.create("demo", "Demo", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "details", [source.ref])
        project = replace_source(project, "changed")
        self.repository.save(project)
        status = self.repository.list_statuses()[0]
        self.assertEqual(2, status.invalidated_artifact_count)
        self.assertEqual((ArtifactKind.ORIGINAL_SPEC,), status.current_artifacts)

    def test_project_ids_fail_closed_against_traversal_and_ambiguous_names(self):
        for project_id in ("../escape", "a/b", ".hidden", "Upper", "with space", "a--"):
            with self.subTest(project_id=project_id):
                with self.assertRaises(ValueError):
                    self.repository.create(project_id, "Demo", "source")

    def test_duplicate_create_and_missing_save_fail(self):
        project = self.repository.create("demo", "Demo", "source")
        with self.assertRaises(FileExistsError):
            self.repository.create("demo", "Other", "source")
        other = type(project)("other", project.name, project.artifacts, project.approvals)
        with self.assertRaises(FileNotFoundError):
            self.repository.save(other)

    def test_malformed_and_forged_files_fail_closed(self):
        project = self.repository.create("demo", "Demo", "source")
        path = self.root / "demo.json"
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "malformed stored project"):
            self.repository.get("demo")
        payload = copy.deepcopy(project_to_dict(project))
        payload["project_id"] = "other"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.repository.get("demo")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlink_state_is_refused(self):
        target = self.root / "target"
        target.write_text("{}", encoding="utf-8")
        os.symlink(target, self.root / "linked.json")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.repository.get("linked")
        with self.assertRaisesRegex(ValueError, "unexpected repository entry"):
            self.repository.list_statuses()

    def test_atomic_save_leaves_no_temporary_files(self):
        project = self.repository.create("demo", "Demo", "source")
        self.repository.save(project)
        self.assertEqual(["demo.json"], sorted(path.name for path in self.root.iterdir()))


if __name__ == "__main__":
    unittest.main()

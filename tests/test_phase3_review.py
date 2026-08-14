import copy
import json
import unittest

from specatom_hs.phase3_review import Phase3Decision, Phase3ReviewLog
from specatom_hs.projects import (
    ApprovalDecision, ArtifactKind, ArtifactState, add_artifact, create_project,
    project_from_dict, project_to_dict, replace_source, submit_phase3_review,
)


class Phase3ReviewWorkflowTests(unittest.TestCase):
    def project(self):
        project = create_project("demo", "Demo", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "elaborated", (source.ref,))
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        return add_artifact(project, ArtifactKind.TEST_SPEC, "tests", (elaborated.ref,))

    def log(self, project, first=ApprovalDecision.APPROVED, second=ApprovalDecision.APPROVED):
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        tests = project.current(ArtifactKind.TEST_SPEC)
        return Phase3ReviewLog(elaborated.ref, tests.ref, (
            Phase3Decision(elaborated.ref, first, "alice", "2026-08-14T12:25:00Z", None, "spec reviewed"),
            Phase3Decision(tests.ref, second, "bob", "2026-08-14T12:26:00Z", None, "tests reviewed"),
        ))

    def test_exact_approvals_create_log_and_byte_identical_reviewed_snapshots(self):
        project = self.project()
        updated = submit_phase3_review(project, self.log(project))
        elaborated = updated.current(ArtifactKind.ELABORATED_SPEC)
        tests = updated.current(ArtifactKind.TEST_SPEC)
        log = updated.current(ArtifactKind.REVIEW_LOG)
        reviewed = updated.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
        reviewed_tests = updated.current(ArtifactKind.REVIEWED_TEST_SPEC)
        self.assertEqual(elaborated.content, reviewed.content)
        self.assertEqual(tests.content, reviewed_tests.content)
        self.assertEqual((elaborated.ref, log.ref), reviewed.upstream)
        self.assertEqual((tests.ref, log.ref), reviewed_tests.upstream)
        self.assertEqual(updated, project_from_dict(project_to_dict(updated)))

    def test_request_changes_persists_log_without_approved_snapshots(self):
        project = self.project()
        updated = submit_phase3_review(project, self.log(project, ApprovalDecision.CHANGES_REQUESTED))
        self.assertIsNotNone(updated.current(ArtifactKind.REVIEW_LOG))
        self.assertIsNone(updated.current(ArtifactKind.REVIEWED_ELABORATED_SPEC))
        self.assertIsNone(updated.current(ArtifactKind.REVIEWED_TEST_SPEC))

    def test_source_change_invalidates_log_snapshots_and_approvals(self):
        project = self.project()
        approved = submit_phase3_review(project, self.log(project))
        changed = replace_source(approved, "changed")
        for kind in (ArtifactKind.REVIEW_LOG, ArtifactKind.REVIEWED_ELABORATED_SPEC, ArtifactKind.REVIEWED_TEST_SPEC):
            self.assertIsNone(changed.current(kind))
        self.assertTrue(all(a.decision is ApprovalDecision.INVALIDATED for a in changed.approvals))

    def test_stale_malformed_and_duplicate_decisions_fail_closed(self):
        project = self.project()
        log = self.log(project)
        bad = Phase3ReviewLog(log.elaborated_spec, log.test_spec, log.decisions + (log.decisions[0],))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            submit_phase3_review(project, bad)
        stale = replace_source(project, "changed")
        with self.assertRaisesRegex(ValueError, "current elaborated"):
            submit_phase3_review(stale, log)
        bad_time = Phase3ReviewLog(log.elaborated_spec, log.test_spec, (
            Phase3Decision(log.elaborated_spec, ApprovalDecision.APPROVED, "alice", "yesterday"),
        ))
        with self.assertRaisesRegex(ValueError, "UTC timestamp"):
            submit_phase3_review(project, bad_time)

    def test_forged_review_log_and_reviewed_snapshot_fail_on_load(self):
        approved = submit_phase3_review(self.project(), self.log(self.project()))
        payload = project_to_dict(approved)
        forged = copy.deepcopy(payload)
        item = next(a for a in forged["artifacts"] if a["kind"] == "reviewed-test-spec")
        item["content"] = "forged"
        from specatom_hs.projects import _artifact_id, content_sha256
        item["content_hash"] = content_sha256(item["content"])
        item["artifact_id"] = _artifact_id("demo", ArtifactKind.REVIEWED_TEST_SPEC, item["version"], item["content_hash"])
        with self.assertRaisesRegex(ValueError, "reviewed snapshots"):
            project_from_dict(forged)

        expanded = copy.deepcopy(payload)
        log_item = next(a for a in expanded["artifacts"] if a["kind"] == "review-log")
        content = json.loads(log_item["content"])
        content["authority"] = "forged"
        log_item["content"] = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        log_item["content_hash"] = content_sha256(log_item["content"])
        log_item["artifact_id"] = _artifact_id("demo", ArtifactKind.REVIEW_LOG, log_item["version"], log_item["content_hash"])
        with self.assertRaises(ValueError):
            project_from_dict(expanded)


if __name__ == "__main__":
    unittest.main()

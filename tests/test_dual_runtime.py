import json
import unittest

from specatom_hs.dual_runtime import run_approved_dual_runtime
from specatom_hs.projects import ApprovalDecision, ArtifactKind, replace_source
from specatom_hs.validation_plan import PlanReview, ValidationPlanCoordinator, submit_plan_review
from tests.test_validation_plan import ValidationPlanTests


class ApprovedDualRuntimeTests(unittest.TestCase):
    def setUp(self):
        fixture = ValidationPlanTests(); fixture.setUp()
        project = ValidationPlanCoordinator(fixture.adapter()).synthesize(fixture.project)
        plan = project.current(ArtifactKind.VALIDATION_PLAN)
        self.project = submit_plan_review(project, PlanReview(plan.ref, ApprovalDecision.APPROVED,
            "reviewer", "approve exact plan", "2026-08-17T09:56:00Z"))

    @staticmethod
    def runner(actual="hello", exit_code=0):
        return lambda source: {"exit_code": exit_code,
            "stdout": json.dumps({"case_id":"example:greeting", "actual":actual}) + "\n",
            "stderr":"", "limits":{"timeout_seconds":2, "memory_mib":128}}

    def test_approved_plan_oracle_drives_both_runtimes_without_text_profile(self):
        result = run_approved_dual_runtime(self.project, python_source="print-result-v2",
            metta_source="(emit-result-v2)", timestamp="2026-08-17T09:57:00Z",
            python_runner=self.runner(), metta_runner=self.runner())
        evidence = [item for item in result.artifacts if item.kind is ArtifactKind.RUNTIME_EVIDENCE]
        self.assertEqual(2, len(evidence))
        for artifact in evidence:
            payload = json.loads(artifact.content)["payload"]
            self.assertTrue(payload["observations"][0]["matched"])
            self.assertIn(result.current(ArtifactKind.VALIDATION_PLAN).ref, artifact.upstream)

    def test_divergence_is_recorded_not_overridden_by_exit_zero(self):
        result = run_approved_dual_runtime(self.project, python_source="python-body",
            metta_source="metta-body", timestamp="2026-08-17T09:57:00Z",
            python_runner=self.runner("wrong"), metta_runner=self.runner())
        records = {json.loads(x.content)["payload"]["runtime"]: json.loads(x.content)["payload"]
                   for x in result.artifacts if x.kind is ArtifactKind.RUNTIME_EVIDENCE}
        self.assertFalse(records["python-reference"]["observations"][0]["matched"])
        self.assertTrue(records["hyperon-metta"]["observations"][0]["matched"])

    def test_malformed_duplicate_and_missing_output_fail_without_partial_write(self):
        malformed = lambda source: {"exit_code":0,"stdout":"not-json\n","stderr":"","limits":{"timeout_seconds":2}}
        with self.assertRaises(ValueError):
            run_approved_dual_runtime(self.project, python_source="p", metta_source="m",
                timestamp="2026-08-17T09:57:00Z", python_runner=malformed, metta_runner=self.runner())
        self.assertIsNone(self.project.current(ArtifactKind.RUNTIME_EVIDENCE))

    def test_source_change_invalidates_plan_and_blocks_execution(self):
        changed = replace_source(self.project, "[id:R-1] changed byte\n")
        with self.assertRaises(ValueError):
            run_approved_dual_runtime(changed, python_source="p", metta_source="m",
                timestamp="2026-08-17T09:57:00Z", python_runner=self.runner(), metta_runner=self.runner())


if __name__ == "__main__": unittest.main()

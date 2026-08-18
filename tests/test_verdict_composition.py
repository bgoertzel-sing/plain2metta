import copy
import json
import unittest

from specatom_hs.projects import ApprovalDecision, ArtifactKind, replace_source
from specatom_hs.semantic_artifacts import build_semantic_artifact
from specatom_hs.projects import add_semantic_artifact
from specatom_hs.validation_plan import PlanReview, ValidationPlanCoordinator, submit_plan_review
from specatom_hs.verdict_composition import compose_validation_verdict, normalize_observation
from tests.test_validation_plan import ValidationPlanTests


def ref(value):
    return {"artifact_id": value.artifact_id, "content_hash": value.content_hash}


class VerdictCompositionTests(unittest.TestCase):
    def setUp(self):
        fixture = ValidationPlanTests(); fixture.setUp()
        project = ValidationPlanCoordinator(fixture.adapter()).synthesize(fixture.project)
        plan = project.current(ArtifactKind.VALIDATION_PLAN)
        self.project = submit_plan_review(project, PlanReview(plan.ref, ApprovalDecision.APPROVED,
            "reviewer", "approve exact plan", "2026-08-17T09:41:00Z"))

    def add_evidence(self, project, runtime, observations, exit_status=0):
        source = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
        plan = project.current(ArtifactKind.VALIDATION_PLAN)
        review = project.current(ArtifactKind.VALIDATION_PLAN_REVIEW)
        ancestry = [*plan.upstream, plan.ref, review.ref]
        stamp = f"2026-08-17T09:42:{len([x for x in project.artifacts if x.kind is ArtifactKind.RUNTIME_EVIDENCE]):02d}Z"
        provenance = {"producer":"fixture-"+runtime,"version":"1","operation":"bounded-run",
            "timestamp":stamp,"input_hashes":[x.content_hash for x in ancestry]}
        payload = {"evidence_id":"evidence:"+runtime.replace("-", "."),"runtime":runtime,
            "runtime_hash":"sha256:"+"1"*64,"resource_bounds":{"timeout":2},"case_id":"case:R-1",
            "seed":None,"observations":observations,"exit_status":exit_status,
            "artifact_hashes":[plan.content_hash,review.content_hash],"started_at":stamp,"finished_at":stamp}
        return add_semantic_artifact(project, build_semantic_artifact("RuntimeEvidence", source.ref,
            ancestry[1:], provenance, payload))

    def observation(self, actual="hello", expected="hello"):
        return {"case_id":"example:greeting","actual":actual,"expected":expected,
            "matched":actual == expected,"oracle_id":"oracle:R-1","oracle_role":"independent-validation-author"}

    def compose(self, project):
        obligation = project.current(ArtifactKind.VALIDATION_OBLIGATION)
        contract = project.current(ArtifactKind.SEMANTIC_CONTRACT)
        evidence = [ref(x.ref) for x in project.artifacts if x.kind is ArtifactKind.RUNTIME_EVIDENCE]
        return compose_validation_verdict(project, ref(obligation.ref), ref(contract.ref), evidence,
            timestamp="2026-08-17T09:43:00Z")

    def test_dual_runtime_independent_oracles_achieve_examples_not_proof(self):
        project = self.add_evidence(self.project,"hyperon-metta",[self.observation()])
        project = self.add_evidence(project,"python-reference",[self.observation()])
        project = self.add_evidence(project,"lean4-kernel",[{"kernel_checked":True}],0)
        result = self.compose(project)
        verdict = json.loads(result.current(ArtifactKind.VALIDATION_VERDICT).content)["payload"]
        self.assertEqual("pass",verdict["status"])
        self.assertTrue(verdict["grade_achieved"]["vector"]["G3"])
        self.assertFalse(verdict["grade_achieved"]["vector"]["G5"])

    def test_wrong_output_and_cross_runtime_divergence_fail(self):
        project = self.add_evidence(self.project,"hyperon-metta",[self.observation("wrong")])
        project = self.add_evidence(project,"python-reference",[self.observation("wrong")])
        verdict = json.loads(self.compose(project).current(ArtifactKind.VALIDATION_VERDICT).content)["payload"]
        self.assertEqual("fail",verdict["status"]); self.assertIn("wrong output",verdict["residual_risk"])

        project = self.add_evidence(self.project,"hyperon-metta",[self.observation()])
        project = self.add_evidence(project,"python-reference",[self.observation("different","different")])
        verdict = json.loads(self.compose(project).current(ArtifactKind.VALIDATION_VERDICT).content)["payload"]
        self.assertEqual("fail",verdict["status"]); self.assertIn("divergence",verdict["residual_risk"])

    def test_missing_runtime_is_unknown_and_timeout_is_unknown(self):
        project = self.add_evidence(self.project,"hyperon-metta",[self.observation()])
        verdict = json.loads(self.compose(project).current(ArtifactKind.VALIDATION_VERDICT).content)["payload"]
        self.assertEqual("unknown",verdict["status"])
        project = self.add_evidence(project,"python-reference",[self.observation()],124)
        verdict = json.loads(self.compose(project).current(ArtifactKind.VALIDATION_VERDICT).content)["payload"]
        self.assertEqual("unknown",verdict["status"])

    def test_malformed_or_misattributed_observation_and_stale_evidence_fail_closed(self):
        bad = self.observation(); bad["matched"] = False
        with self.assertRaises(ValueError): normalize_observation(bad)
        project = self.add_evidence(self.project,"hyperon-metta",[self.observation()])
        project = self.add_evidence(project,"python-reference",[self.observation()])
        stale_refs = [ref(x.ref) for x in project.artifacts if x.kind is ArtifactKind.RUNTIME_EVIDENCE]
        changed = replace_source(project,"[id:R-1] changed byte\n")
        obligation = project.current(ArtifactKind.VALIDATION_OBLIGATION)
        contract = project.current(ArtifactKind.SEMANTIC_CONTRACT)
        with self.assertRaises(ValueError):
            compose_validation_verdict(changed,ref(obligation.ref),ref(contract.ref),stale_refs,timestamp="2026-08-17T09:43:00Z")
        self.assertIsNone(changed.current(ArtifactKind.VALIDATION_VERDICT))

    def test_unknown_version_and_hash_mismatch_fail_without_partial_write(self):
        project = self.add_evidence(self.project,"hyperon-metta",[self.observation()])
        project = self.add_evidence(project,"python-reference",[self.observation()])
        obligation = project.current(ArtifactKind.VALIDATION_OBLIGATION); contract=project.current(ArtifactKind.SEMANTIC_CONTRACT)
        evidence = [ref(x.ref) for x in project.artifacts if x.kind is ArtifactKind.RUNTIME_EVIDENCE]
        evidence[0]["content_hash"] = "sha256:"+"0"*64
        with self.assertRaises(ValueError):
            compose_validation_verdict(project,ref(obligation.ref),ref(contract.ref),evidence,timestamp="2026-08-17T09:43:00Z")
        self.assertIsNone(project.current(ArtifactKind.VALIDATION_VERDICT))


if __name__ == "__main__": unittest.main()

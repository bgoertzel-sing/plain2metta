import copy
import json
import unittest

from specatom_hs.phase3_review import Phase3Decision, Phase3ReviewLog
from specatom_hs.projects import (
    ApprovalDecision, ArtifactKind, add_artifact, add_semantic_artifact,
    create_project, project_from_dict, project_to_dict, replace_source,
    submit_phase3_review,
)
from specatom_hs.semantic_artifacts import build_semantic_artifact
from specatom_hs.validation_plan import (
    RESPONSE_SCHEMA, PlanReview, ValidationPlanCoordinator,
    build_validation_plan_request, submit_plan_review,
    validation_plan_request_hash,
)


class ValidationPlanTests(unittest.TestCase):
    def setUp(self):
        project = create_project("plan", "Plan", "[id:R-1] Return hello.\n")
        original = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "[id:R-1] Return hello.\n", (original.ref,))
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = add_artifact(project, ArtifactKind.TEST_SPEC, "[covers:R-1] Expect hello.\n", (elaborated.ref,))
        tests = project.current(ArtifactKind.TEST_SPEC)
        project = submit_phase3_review(project, Phase3ReviewLog(elaborated.ref, tests.ref, (
            Phase3Decision(elaborated.ref, ApprovalDecision.APPROVED, "source-reviewer", "2026-08-17T08:00:00Z"),
            Phase3Decision(tests.ref, ApprovalDecision.APPROVED, "source-reviewer", "2026-08-17T08:00:01Z"),
        )))
        source = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
        provenance = {"producer":"contract-author","version":"1","operation":"author","timestamp":"2026-08-17T08:00:02Z","input_hashes":[source.content_hash]}
        contract_doc = build_semantic_artifact("SemanticContract", source.ref, [], provenance, {
            "contract_id":"contract:R-1","source_clause_refs":["R-1"],"name":"Greeting",
            "inputs":[],"output":"Text","preconditions":[],"postconditions":[],"invariants":[],
            "effects":["pure"],"temporal_constraints":[],
            "nondeterminism":{"policy":"deterministic","ownership_locus":"reference-interpreter"},
            "environment_assumptions":[],"unresolved_holes":[],
        })
        project = add_semantic_artifact(project, contract_doc)
        contract = project.current(ArtifactKind.SEMANTIC_CONTRACT)
        obligation_doc = build_semantic_artifact("ValidationObligation", source.ref, [contract.ref], {
            "producer":"obligation-author","version":"1","operation":"author","timestamp":"2026-08-17T08:00:03Z","input_hashes":[source.content_hash,contract.content_hash],
        }, {
            "obligation_id":"obligation:R-1","contract_ref":{"artifact_id":contract.artifact_id,"content_hash":contract.content_hash},
            "source_clause_refs":["R-1"],"claim":{"op":"eq"},"required_grade":"G3",
            "admissible_methods":["example"],"domain":{"kind":"finite"},"assumptions":[],
            "severity":"major","unresolved":False,
        })
        self.project = add_semantic_artifact(project, obligation_doc)

    def adapter(self, mutate=None, calls=None, project=None):
        target = project or self.project
        def invoke(request):
            if calls is not None:
                calls.append(copy.deepcopy(request))
            req = build_validation_plan_request(target)
            contract = target.current(ArtifactKind.SEMANTIC_CONTRACT)
            payload = {
                "plan_id":"plan:R-1",
                "reviewed_contract_refs":[{"artifact_id":contract.artifact_id,"content_hash":contract.content_hash}],
                "author_provenance":{"role":"validation-author","request_hash":validation_plan_request_hash(req),"backend":"fixture","model":"independent-v1","interaction_id":"call-1"},
                "examples":[{"input":[],"expected":"hello"}],"generators":[],"properties":[],
                "metamorphic_relations":[],"state_models":[],"differential_oracles":[],
                "formal_tasks":[],"coverage_claims":["R-1"],
            }
            response = {"schema":RESPONSE_SCHEMA,"request_hash":validation_plan_request_hash(req),"plan_payload":payload,"provenance":{"backend":"fixture","model":"independent-v1","interaction_id":"call-1","input_tokens":10,"output_tokens":20,"timestamp":"2026-08-17T08:00:04Z"}}
            return mutate(response) if mutate else response
        return invoke

    def test_one_call_is_role_separated_strict_and_round_trips(self):
        calls = []
        result = ValidationPlanCoordinator(self.adapter(calls=calls)).synthesize(self.project)
        self.assertEqual(1, len(calls))
        self.assertEqual({"schema","reviewed_source","reviewed_source_text","contracts","obligations"}, set(calls[0]))
        self.assertNotIn("implementation", json.dumps(calls[0]))
        plan = result.current(ArtifactKind.VALIDATION_PLAN)
        self.assertIsNotNone(plan)
        self.assertEqual(result, project_from_dict(project_to_dict(result)))

    def test_bad_outputs_fail_closed_once_without_partial_write(self):
        def variants(item):
            outputs = []
            x=copy.deepcopy(item); x["schema"]="unknown/v9"; outputs.append(x)
            x=copy.deepcopy(item); x["request_hash"]="sha256:"+"0"*64; outputs.append(x)
            x=copy.deepcopy(item); x["provenance"]["interaction_id"]="other"; outputs.append(x)
            x=copy.deepcopy(item); x["plan_payload"]["reviewed_contract_refs"] *= 2; outputs.append(x)
            x=copy.deepcopy(item); x["plan_payload"]["reviewed_contract_refs"][0]["artifact_id"]="../contract"; outputs.append(x)
            x=copy.deepcopy(item); x["plan_payload"]["reviewed_contract_refs"][0]["content_hash"]="sha256:"+"0"*64; outputs.append(x)
            x=copy.deepcopy(item); del x["plan_payload"]["properties"]; outputs.append(x)
            return outputs
        base = self.adapter()(build_validation_plan_request_to_wire(self.project))
        for bad in variants(base):
            calls=[]
            with self.assertRaises(ValueError):
                ValidationPlanCoordinator(lambda request, bad=bad: (calls.append(request), bad)[1]).synthesize(self.project)
            self.assertEqual(1,len(calls))
            self.assertIsNone(self.project.current(ArtifactKind.VALIDATION_PLAN))

    def test_review_approval_edit_and_transitive_invalidation(self):
        project = ValidationPlanCoordinator(self.adapter()).synthesize(self.project)
        plan = project.current(ArtifactKind.VALIDATION_PLAN)
        project = submit_plan_review(project, PlanReview(plan.ref, ApprovalDecision.APPROVED, "plan-reviewer", "exact plan accepted", "2026-08-17T08:00:05Z"))
        review = project.current(ArtifactKind.VALIDATION_PLAN_REVIEW)
        self.assertEqual((plan.ref,), review.upstream)
        self.assertEqual(ApprovalDecision.APPROVED, next(a.decision for a in project.approvals if a.artifact == plan.ref))
        self.assertEqual(project, project_from_dict(project_to_dict(project)))
        changed = replace_source(project, "[id:R-1] Return hello!\n")
        self.assertIsNone(changed.current(ArtifactKind.VALIDATION_PLAN))
        self.assertIsNone(changed.current(ArtifactKind.VALIDATION_PLAN_REVIEW))
        self.assertEqual(ApprovalDecision.INVALIDATED, next(a.decision for a in changed.approvals if a.artifact == plan.ref))

    def test_reviewer_edit_creates_new_exact_plan_and_contract_change_invalidates_it(self):
        project = ValidationPlanCoordinator(self.adapter()).synthesize(self.project)
        old = project.current(ArtifactKind.VALIDATION_PLAN)
        edited = copy.deepcopy(json.loads(old.content)["payload"])
        edited["coverage_claims"] = ["R-1", "reviewer-confirmed"]
        project = submit_plan_review(project, PlanReview(old.ref, ApprovalDecision.APPROVED, "plan-reviewer", "edited and accepted", "2026-08-17T08:00:05Z", edited))
        plan = project.current(ArtifactKind.VALIDATION_PLAN)
        self.assertNotEqual(old.ref, plan.ref)
        self.assertEqual(plan.ref, project.current(ArtifactKind.VALIDATION_PLAN_REVIEW).upstream[0])
        source = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
        changed_contract = build_semantic_artifact("SemanticContract", source.ref, [], {
            "producer":"contract-author","version":"2","operation":"review-change","timestamp":"2026-08-17T08:00:09Z","input_hashes":[source.content_hash],
        }, {
            "contract_id":"contract:R-1-v2","source_clause_refs":["R-1"],"name":"Greeting changed",
            "inputs":[],"output":"Text","preconditions":[],"postconditions":[],"invariants":[],"effects":["pure"],"temporal_constraints":[],
            "nondeterminism":{"policy":"deterministic","ownership_locus":"reference-interpreter"},"environment_assumptions":[],"unresolved_holes":[],
        })
        changed = add_semantic_artifact(project, changed_contract)
        self.assertIsNone(changed.current(ArtifactKind.VALIDATION_PLAN))
        self.assertIsNone(changed.current(ArtifactKind.VALIDATION_PLAN_REVIEW))
        self.assertEqual(ApprovalDecision.INVALIDATED, next(a.decision for a in changed.approvals if a.artifact == plan.ref))

    def test_unresolved_critical_meaning_blocks_approval(self):
        contract = self.project.current(ArtifactKind.SEMANTIC_CONTRACT)
        source = self.project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
        unresolved = build_semantic_artifact("ValidationObligation", source.ref, [contract.ref], {
            "producer":"fixture","version":"1","operation":"author","timestamp":"2026-08-17T08:00:06Z","input_hashes":[source.content_hash,contract.content_hash],
        }, {"obligation_id":"obligation:critical","contract_ref":{"artifact_id":contract.artifact_id,"content_hash":contract.content_hash},"source_clause_refs":["R-1"],"claim":{"op":"hole"},"required_grade":"G3","admissible_methods":[],"domain":{"kind":"unknown"},"assumptions":[],"severity":"critical","unresolved":True})
        project = add_semantic_artifact(self.project, unresolved)
        project = ValidationPlanCoordinator(self.adapter(project=project)).synthesize(project)
        plan = project.current(ArtifactKind.VALIDATION_PLAN)
        with self.assertRaisesRegex(ValueError,"unresolved critical"):
            submit_plan_review(project, PlanReview(plan.ref, ApprovalDecision.APPROVED, "reviewer", "approve", "2026-08-17T08:00:07Z"))

    def test_forged_review_and_direct_bypass_fail_closed(self):
        project = ValidationPlanCoordinator(self.adapter()).synthesize(self.project)
        plan = project.current(ArtifactKind.VALIDATION_PLAN)
        project = submit_plan_review(project, PlanReview(plan.ref, ApprovalDecision.APPROVED, "reviewer", "approve", "2026-08-17T08:00:08Z"))
        payload = project_to_dict(project)
        review = next(a for a in payload["artifacts"] if a["kind"] == "validation-plan-review")
        review["content"] = review["content"].replace("reviewer", "forger")
        with self.assertRaises(ValueError): project_from_dict(payload)
        with self.assertRaises(ValueError): add_artifact(project, ArtifactKind.VALIDATION_PLAN_REVIEW, "{}", (plan.ref,))


def build_validation_plan_request_to_wire(project):
    from specatom_hs.validation_plan import validation_plan_request_to_dict
    return validation_plan_request_to_dict(build_validation_plan_request(project))


if __name__ == "__main__": unittest.main()

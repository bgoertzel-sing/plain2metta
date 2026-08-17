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
                "examples":[{"case_id":"example:greeting","input":[],"expected":"hello"}],"generators":[],"properties":[],
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

    def test_hypothesis_lowering_requires_exact_approval_and_admits_matching_evidence(self):
        from specatom_hs.hypothesis_backend import HypothesisCoordinator, RESULT_SCHEMA, lower_hypothesis_request, request_hash
        project = ValidationPlanCoordinator(self.adapter()).synthesize(self.project)
        with self.assertRaisesRegex(ValueError, "approved"):
            lower_hypothesis_request(project, 17)
        plan = project.current(ArtifactKind.VALIDATION_PLAN)
        project = submit_plan_review(project, PlanReview(plan.ref, ApprovalDecision.APPROVED, "reviewer", "approve", "2026-08-17T08:20:00Z"))
        calls=[]
        def adapter(request):
            calls.append(copy.deepcopy(request))
            return {"schema":RESULT_SCHEMA,"request_hash":request_hash(request),"hypothesis_version":"6.138.15",
                "profile":{"max_examples":100,"deadline_ms":1000,"derandomize":False},"seed":17,"cases":[{"case_id":"example:greeting"}],
                "observations":[{"case_id":"example:greeting","actual":"hello","expected":"hello","matched":True}],
                "shrinking":[],"minimal_counterexamples":[],"exit_status":0,"resource_bounds":{"seconds":2,"memory_mb":128},
                "started_at":"2026-08-17T08:20:01Z","finished_at":"2026-08-17T08:20:02Z"}
        result = HypothesisCoordinator(adapter).run(project,17)
        self.assertEqual(1,len(calls))
        self.assertIsNotNone(result.current(ArtifactKind.RUNTIME_EVIDENCE))

    def test_hypothesis_wrong_observation_and_misattribution_fail_without_partial_write(self):
        from specatom_hs.hypothesis_backend import HypothesisCoordinator, RESULT_SCHEMA, request_hash
        project = ValidationPlanCoordinator(self.adapter()).synthesize(self.project)
        plan = project.current(ArtifactKind.VALIDATION_PLAN)
        project = submit_plan_review(project, PlanReview(plan.ref, ApprovalDecision.APPROVED, "reviewer", "approve", "2026-08-17T08:20:00Z"))
        def bad(request, forged=False):
            return {"schema":RESULT_SCHEMA,"request_hash":("sha256:"+"0"*64 if forged else request_hash(request)),"hypothesis_version":"6.138.15",
                "profile":{"max_examples":100,"deadline_ms":1000,"derandomize":False},"seed":17,"cases":[],
                "observations":[{"case_id":"example:greeting","actual":"bye","expected":"hello","matched":False}],
                "shrinking":[{"from":"bye","to":"b"}],"minimal_counterexamples":[{"input":[],"actual":"bye"}],"exit_status":0,
                "resource_bounds":{"seconds":2},"started_at":"2026-08-17T08:20:01Z","finished_at":"2026-08-17T08:20:02Z"}
        for forged in (False,True):
            with self.assertRaises(ValueError): HypothesisCoordinator(lambda req, f=forged: bad(req,f)).run(project,17)
            self.assertIsNone(project.current(ArtifactKind.RUNTIME_EVIDENCE))

    def test_hypothesis_failing_run_atomically_persists_replayable_counterexample(self):
        from specatom_hs.hypothesis_backend import HypothesisCoordinator, RESULT_SCHEMA, request_hash
        project = ValidationPlanCoordinator(self.adapter()).synthesize(self.project)
        plan = project.current(ArtifactKind.VALIDATION_PLAN)
        project = submit_plan_review(project, PlanReview(plan.ref, ApprovalDecision.APPROVED, "reviewer", "approve", "2026-08-17T08:20:00Z"))
        def failing(request):
            return {"schema":RESULT_SCHEMA,"request_hash":request_hash(request),"hypothesis_version":"6.138.15",
                "profile":{"max_examples":100,"deadline_ms":1000,"derandomize":False},"seed":19,"cases":[{"case_id":"example:greeting"}],
                "observations":[{"case_id":"example:greeting","actual":"bye","expected":"hello","matched":False}],
                "shrinking":["Falsifying example: greeting"],"minimal_counterexamples":[{"case_id":"example:greeting","actual":"bye","expected":"hello","matched":False}],
                "exit_status":1,"resource_bounds":{"seconds":2,"memory_mb":128},
                "started_at":"2026-08-17T08:20:01Z","finished_at":"2026-08-17T08:20:02Z"}
        result = HypothesisCoordinator(failing).run(project,19)
        self.assertIsNotNone(result.current(ArtifactKind.RUNTIME_EVIDENCE))
        self.assertIsNotNone(result.current(ArtifactKind.COUNTEREXAMPLE))
        self.assertEqual(result, project_from_dict(project_to_dict(result)))
        changed = replace_source(result, "[id:R-1] Return hello!\n")
        self.assertIsNone(changed.current(ArtifactKind.RUNTIME_EVIDENCE))
        self.assertIsNone(changed.current(ArtifactKind.COUNTEREXAMPLE))

    def test_tlc_lowering_requires_exact_approval_and_evidence_invalidates_transitively(self):
        from specatom_hs.tlc_backend import TLCCoordinator, lower_tlc_request, run_tlc_request
        tools = "/home/openclaw/research-agent/projects/specatom-hs/experiments/20260817T040300Z-plain2metta-stage0-tlc-lean/artifacts/tools"
        def with_model(response):
            response["plan_payload"]["state_models"] = [{"model_id":"auth-order", "source_clause_refs":["R-1"], "protocol":"authentication-ordering", "scope":{"max_steps":12,"actors":2}, "mutant":"ordering"}]
            return response
        project = ValidationPlanCoordinator(self.adapter(mutate=with_model)).synthesize(self.project)
        with self.assertRaisesRegex(ValueError, "approved"):
            lower_tlc_request(project)
        plan = project.current(ArtifactKind.VALIDATION_PLAN)
        project = submit_plan_review(project, PlanReview(plan.ref, ApprovalDecision.APPROVED, "reviewer", "approve finite model", "2026-08-17T08:46:00Z"))
        result = TLCCoordinator(lambda request: run_tlc_request(request, tools + "/jdk-21.0.12+8-jre/bin/java", tools + "/tla2tools.jar")).run(project)
        self.assertIsNotNone(result.current(ArtifactKind.RUNTIME_EVIDENCE))
        self.assertIsNotNone(result.current(ArtifactKind.COUNTEREXAMPLE))
        self.assertEqual(result, project_from_dict(project_to_dict(result)))
        changed = replace_source(result, "[id:R-1] Return hello!\n")
        self.assertIsNone(changed.current(ArtifactKind.RUNTIME_EVIDENCE))
        self.assertIsNone(changed.current(ArtifactKind.COUNTEREXAMPLE))

    def test_tlc_misattributed_duplicate_and_hash_confused_results_fail_without_write(self):
        from specatom_hs.tlc_backend import TLCCoordinator, run_tlc_request
        tools = "/home/openclaw/research-agent/projects/specatom-hs/experiments/20260817T040300Z-plain2metta-stage0-tlc-lean/artifacts/tools"
        def with_models(response):
            response["plan_payload"]["state_models"] = [
                {"model_id":"auth", "source_clause_refs":["R-1"], "protocol":"authentication-ordering", "scope":{"max_steps":12,"actors":2}, "mutant":"none"},
                {"model_id":"idem", "source_clause_refs":["R-1"], "protocol":"idempotency-recovery", "scope":{"max_steps":12,"actors":2}, "mutant":"none"},
            ]
            return response
        project = ValidationPlanCoordinator(self.adapter(mutate=with_models)).synthesize(self.project)
        plan = project.current(ArtifactKind.VALIDATION_PLAN)
        project = submit_plan_review(project, PlanReview(plan.ref, ApprovalDecision.APPROVED, "reviewer", "approve finite models", "2026-08-17T08:46:00Z"))
        def execute(request):
            return run_tlc_request(request, tools + "/jdk-21.0.12+8-jre/bin/java", tools + "/tla2tools.jar")
        valid = execute(__import__("specatom_hs.tlc_backend", fromlist=["lower_tlc_request"]).lower_tlc_request(project))
        variants = []
        item=copy.deepcopy(valid); item["request_hash"]="sha256:"+"0"*64; variants.append(item)
        item=copy.deepcopy(valid); item["results"][0]["module_hash"]="sha256:"+"0"*64; variants.append(item)
        item=copy.deepcopy(valid); item["results"][1]=copy.deepcopy(item["results"][0]); variants.append(item)
        item=copy.deepcopy(valid); item["results"][0]["source_map"]["scope"]["actors"]=4; variants.append(item)
        for bad in variants:
            with self.assertRaises(ValueError):
                TLCCoordinator(lambda request, bad=bad: bad).run(project)
            self.assertIsNone(project.current(ArtifactKind.RUNTIME_EVIDENCE))


def build_validation_plan_request_to_wire(project):
    from specatom_hs.validation_plan import validation_plan_request_to_dict
    return validation_plan_request_to_dict(build_validation_plan_request(project))


if __name__ == "__main__": unittest.main()

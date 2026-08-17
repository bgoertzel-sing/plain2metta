import copy
import os
import unittest

from specatom_hs.smt_backend import (
    BOUNDS, LOGIC, OPTIONS, RESULT_SCHEMA, SCHEMA, SMTCoordinator, Z3_SHA256, Z3_VERSION,
    render_smt_bundle, request_hash, run_smt_request,
)

Z3 = "/home/openclaw/research-agent/projects/specatom-hs/experiments/20260817T035226Z-plain2metta-general-semantic-validation-stage0/tools-venv/bin/z3"


def task(task_id, problem, mutant="none", proof=False):
    fragment = "bounded-transition" if problem in {"unreachable-state", "finite-counterexample"} else "pure"
    return {"task_id":task_id, "source_clause_refs":["R-1"], "fragment":fragment,
            "problem":problem, "mutant":mutant, "proof_requested":proof}


def request(tasks):
    return {"schema":SCHEMA, "z3_version":Z3_VERSION, "z3_hash":Z3_SHA256, "logic":LOGIC,
            "options":OPTIONS, "bounds":BOUNDS, "plan":{"artifact_id":"plan-1","content_hash":"sha256:"+"1"*64},
            "review":{"artifact_id":"review-1","content_hash":"sha256:"+"2"*64}, "tasks":tasks,
            "ancestry":[{"artifact_id":"source-1","content_hash":"sha256:"+"3"*64},
                        {"artifact_id":"contract-1","content_hash":"sha256:"+"4"*64},
                        {"artifact_id":"plan-1","content_hash":"sha256:"+"1"*64},
                        {"artifact_id":"review-1","content_hash":"sha256:"+"2"*64}]}


class SMTBackendTests(unittest.TestCase):
    def test_encoder_is_canonical_reviewable_and_source_mapped(self):
        value = request([task("contradiction", "contradictory-contract"), task("boundary", "boundary-error")])
        self.assertEqual(render_smt_bundle(value), render_smt_bundle(copy.deepcopy(value)))
        bundle = render_smt_bundle(value)[0]
        self.assertIn("(set-logic QF_LIA)", bundle["formula"])
        self.assertEqual(["R-1"], bundle["source_map"]["assertions"]["lower"]["source_clause_refs"])
        self.assertEqual(request_hash(value), request_hash(copy.deepcopy(value)))

    def test_gold_formula_and_mutation_pairs_detect_all_required_shapes(self):
        if not os.path.exists(Z3): self.skipTest("pinned Stage-0 Z3 unavailable")
        tasks = [task("contradiction", "contradictory-contract"), task("consistent", "contradictory-contract", "consistent"),
                 task("unreachable", "unreachable-state"), task("reachable", "unreachable-state", "reachable"),
                 task("boundary", "boundary-error"), task("boundary-fixed", "boundary-error", "fixed"),
                 task("finite", "finite-counterexample"), task("finite-fixed", "finite-counterexample", "fixed")]
        result = run_smt_request(request(tasks), Z3)
        observed = {item["task_id"]: item["result"] for item in result["results"]}
        self.assertEqual({"contradiction":"unsat","consistent":"sat","unreachable":"unsat","reachable":"sat",
                          "boundary":"sat","boundary-fixed":"unsat","finite":"sat","finite-fixed":"unsat"}, observed)
        self.assertTrue(all(item["formula"] and item["formula_hash"] and item["source_map"] for item in result["results"]))

    def test_proof_object_is_recorded_when_requested_and_supported(self):
        if not os.path.exists(Z3): self.skipTest("pinned Stage-0 Z3 unavailable")
        result = run_smt_request(request([task("proof", "contradictory-contract", proof=True)]), Z3)["results"][0]
        self.assertEqual("unsat", result["result"])
        self.assertTrue(result["proof"])

    def test_unknown_version_prose_path_confusion_type_confusion_and_duplicates_fail(self):
        good = request([task("boundary", "boundary-error")])
        variants=[]
        item=copy.deepcopy(good); item["schema"]="unknown/v9"; variants.append(item)
        item=copy.deepcopy(good); item["tasks"][0]["problem"]="free prose"; variants.append(item)
        item=copy.deepcopy(good); item["tasks"][0]["task_id"]="../escape"; variants.append(item)
        item=copy.deepcopy(good); item["tasks"][0]["fragment"]="bounded-transition"; variants.append(item)
        item=copy.deepcopy(good); item["tasks"] *= 2; variants.append(item)
        for value in variants:
            with self.assertRaises(ValueError): render_smt_bundle(value)

    def test_executable_hash_mismatch_fails_before_solver_execution(self):
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            run_smt_request(request([task("boundary", "boundary-error")]), __file__)

    def test_unknown_timeout_and_formula_hash_confusion_fail_without_admission(self):
        from tests.test_validation_plan import ValidationPlanTests
        from specatom_hs.projects import ApprovalDecision, ArtifactKind
        from specatom_hs.validation_plan import PlanReview, ValidationPlanCoordinator, submit_plan_review
        fixture=ValidationPlanTests(); fixture.setUp()
        def with_task(response):
            response["plan_payload"]["formal_tasks"]=[task("boundary", "boundary-error")]
            return response
        project=ValidationPlanCoordinator(fixture.adapter(mutate=with_task)).synthesize(fixture.project)
        plan=project.current(ArtifactKind.VALIDATION_PLAN)
        project=submit_plan_review(project, PlanReview(plan.ref, ApprovalDecision.APPROVED, "reviewer", "approve exact SMT task", "2026-08-17T09:14:00Z"))
        from specatom_hs.smt_backend import lower_smt_request
        valid=run_smt_request(lower_smt_request(project), Z3)
        variants=[]
        item=copy.deepcopy(valid); item["results"][0]["result"]="unknown"; item["results"][0]["unknown_reason"]="timeout"; item["results"][0]["model"]=None; variants.append(item)
        item=copy.deepcopy(valid); item["results"][0]["formula_hash"]="sha256:"+"0"*64; variants.append(item)
        item=copy.deepcopy(valid); item["request_hash"]="sha256:"+"0"*64; variants.append(item)
        item=copy.deepcopy(valid); item["results"] *= 2; variants.append(item)
        for bad in variants:
            with self.assertRaises(ValueError): SMTCoordinator(lambda request,bad=bad:bad).run(project)
            self.assertIsNone(project.current(ArtifactKind.RUNTIME_EVIDENCE))

    def test_exact_approved_ancestry_admits_evidence_and_source_change_invalidates(self):
        from tests.test_validation_plan import ValidationPlanTests
        from specatom_hs.projects import ApprovalDecision, ArtifactKind, project_from_dict, project_to_dict, replace_source
        from specatom_hs.validation_plan import PlanReview, ValidationPlanCoordinator, submit_plan_review
        fixture=ValidationPlanTests(); fixture.setUp()
        def with_tasks(response):
            response["plan_payload"]["formal_tasks"]=[task("contradiction","contradictory-contract"),task("boundary","boundary-error")]
            return response
        project=ValidationPlanCoordinator(fixture.adapter(mutate=with_tasks)).synthesize(fixture.project)
        plan=project.current(ArtifactKind.VALIDATION_PLAN)
        project=submit_plan_review(project, PlanReview(plan.ref, ApprovalDecision.APPROVED, "reviewer", "approve exact SMT tasks", "2026-08-17T09:14:00Z"))
        result=SMTCoordinator(lambda request:run_smt_request(request,Z3)).run(project)
        self.assertIsNotNone(result.current(ArtifactKind.RUNTIME_EVIDENCE))
        self.assertEqual(result, project_from_dict(project_to_dict(result)))
        changed=replace_source(result,"[id:R-1] Return hello!\n")
        self.assertIsNone(changed.current(ArtifactKind.RUNTIME_EVIDENCE))


if __name__ == "__main__": unittest.main()

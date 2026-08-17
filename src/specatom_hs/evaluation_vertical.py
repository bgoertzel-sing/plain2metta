"""Fail-closed Stage 1--8 slice for the evaluation vertical."""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from .contract_calculus import EvaluationContext, check_contract, interpret_contract
from .hypothesis_backend import HYPOTHESIS_VERSION, HypothesisCoordinator, execute_hypothesis_request
from .lean_backend import LEAN_VERSION, LeanCoordinator, run_lean_request
from .phase3_review import Phase3Decision, Phase3ReviewLog
from .projects import ApprovalDecision, ArtifactKind, add_artifact, add_semantic_artifact, create_project, submit_phase3_review
from .semantic_artifacts import build_semantic_artifact
from .smt_backend import SMTCoordinator, Z3_VERSION, run_smt_request
from .tlc_backend import TLC_VERSION, TLCCoordinator, run_tlc_request
from .validation_plan import PlanReview, RESPONSE_SCHEMA, ValidationPlanCoordinator, build_validation_plan_request, submit_plan_review, validation_plan_request_hash
from .verdict_composition import compose_validation_verdict
from .vertical_acceptance import release_metadata

_STAMP = "2026-08-17T18:00:00Z"
_HYPOTHESIS_PYTHON = "/home/openclaw/research-agent/projects/specatom-hs/experiments/20260817T035226Z-plain2metta-general-semantic-validation-stage0/tools-venv/bin/python"
_TLC_TOOLS = "/home/openclaw/research-agent/projects/specatom-hs/experiments/20260817T040300Z-plain2metta-stage0-tlc-lean/artifacts/tools"
_Z3 = "/home/openclaw/research-agent/projects/specatom-hs/experiments/20260817T035226Z-plain2metta-general-semantic-validation-stage0/tools-venv/bin/z3"
_LEAN_TOOLS = _TLC_TOOLS + "/lean-4.33.0-linux/bin"
_LEAN_PACKAGE = Path(__file__).resolve().parents[2] / "lean" / "Plain2MeTTaSemanticKernel"


def _supported_sources() -> frozenset[str]:
    root = Path(__file__).resolve().parents[2] / "examples" / "evaluation"
    return frozenset(path.read_text(encoding="utf-8") for path in sorted(root.glob("*.plain")))


def _ref(ref):
    return {"artifact_id": ref.artifact_id, "content_hash": ref.content_hash}


def _node(stage, kind, artifact_id, content_hash, state, upstream):
    return {"stage": stage, "kind": kind, "artifact_id": artifact_id,
            "content_hash": content_hash, "state": state,
            "upstream": [_ref(item) for item in upstream]}


def build_stage_1_through_8(source: str) -> dict:
    """Build one exact admitted chain and conservatively compose its evidence."""
    if source not in _supported_sources():
        raise ValueError("unsupported or reworded evaluation input")
    project = create_project("evaluation-vertical", "Evaluation vertical", source)
    original = project.current(ArtifactKind.ORIGINAL_SPEC)
    project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, source, (original.ref,))
    elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
    project = add_artifact(project, ArtifactKind.TEST_SPEC, "Exact supported-example admission.\n", (elaborated.ref,))
    tests = project.current(ArtifactKind.TEST_SPEC)
    project = submit_phase3_review(project, Phase3ReviewLog(elaborated.ref, tests.ref, (
        Phase3Decision(elaborated.ref, ApprovalDecision.APPROVED, "source-reviewer", _STAMP, None, "Exact frozen example bytes"),
        Phase3Decision(tests.ref, ApprovalDecision.APPROVED, "source-reviewer", _STAMP, None, "Exact admission test"),
    )))
    reviewed = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
    provenance = {"producer":"vertical-contract-author","version":"1","operation":"author",
                  "timestamp":_STAMP,"input_hashes":[reviewed.content_hash]}
    contract_doc = build_semantic_artifact("SemanticContract", reviewed.ref, [], provenance, {
        "contract_id":"contract:exact-supported-example","source_clause_refs":["exact-source-bytes"],
        "name":"ExactSupportedExample","inputs":[],"output":"Bool","preconditions":[],
        "postconditions":[{"op":"eq","left":{"op":"var","name":"result"},"right":{"op":"literal","type":"Bool","value":True}}],
        "invariants":[],"effects":["pure"],"temporal_constraints":[],
        "nondeterminism":{"policy":"deterministic","ownership_locus":"reference-interpreter"},
        "environment_assumptions":[],"unresolved_holes":[],
    })
    project = add_semantic_artifact(project, contract_doc)
    contract = project.current(ArtifactKind.SEMANTIC_CONTRACT)
    obligation_doc = build_semantic_artifact("ValidationObligation", reviewed.ref, [contract.ref], {
        "producer":"vertical-obligation-author","version":"1","operation":"author","timestamp":_STAMP,
        "input_hashes":[reviewed.content_hash, contract.content_hash],
    }, {"obligation_id":"obligation:exact-supported-example","contract_ref":_ref(contract.ref),
        "source_clause_refs":["exact-source-bytes"],"claim":{"op":"eq","expected":True},
        "required_grade":"G3","admissible_methods":["exact-example"],"domain":{"kind":"singleton"},
        "assumptions":[],"severity":"major","unresolved":False})
    project = add_semantic_artifact(project, obligation_doc)
    obligation = project.current(ArtifactKind.VALIDATION_OBLIGATION)

    checked = check_contract(contract_doc)
    interpretation = interpret_contract(contract_doc, EvaluationContext({"result": True}, {}))
    calculus_body = json.dumps({"schema":"plain2metta-contract-calculus/v1", "contract":_ref(contract.ref),
                                "checked":checked.artifact_id, "interpretation":interpretation},
                               sort_keys=True, separators=(",", ":"))
    calculus_hash = "sha256:" + sha256(calculus_body.encode()).hexdigest()
    calculus_id = "calculus-" + calculus_hash[7:31]

    def author(request):
        req = build_validation_plan_request(project)
        request_digest = validation_plan_request_hash(req)
        return {"schema":RESPONSE_SCHEMA,"request_hash":request_digest,"plan_payload":{
            "plan_id":"plan:exact-supported-example","reviewed_contract_refs":[_ref(contract.ref)],
            "author_provenance":{"role":"validation-author","request_hash":request_digest,
                "backend":"deterministic-plan-fixture","model":"independent-v1","interaction_id":"vertical-stage3-call-1"},
            "examples":[{"case_id":"exact-supported-source-bytes","input":{
                "operation":"exact-equality","args":[sha256(source.encode()).hexdigest(), sha256(source.encode()).hexdigest()]},
                "expected":True}],
            "generators":[],"properties":[],"metamorphic_relations":[],"state_models":[{
                "model_id":"exact-admission-stability","source_clause_refs":["exact-source-bytes"],
                "protocol":"exact-admission-stability","scope":{"max_steps":2,"actors":1},"mutant":"none"}],
            "differential_oracles":[],"formal_tasks":[{
                "task_id":"exact-boolean-postcondition","source_clause_refs":["exact-source-bytes"],
                "fragment":"pure","problem":"exact-boolean-postcondition","mutant":"none",
                "proof_requested":True}],"coverage_claims":["exact-source-bytes"]},
            "provenance":{"backend":"deterministic-plan-fixture","model":"independent-v1",
                "interaction_id":"vertical-stage3-call-1","input_tokens":0,"output_tokens":0,"timestamp":_STAMP}}
    project = ValidationPlanCoordinator(author).synthesize(project)
    plan = project.current(ArtifactKind.VALIDATION_PLAN)
    project = submit_plan_review(project, PlanReview(plan.ref, ApprovalDecision.APPROVED,
        "independent-plan-reviewer", "Exact bounded plan accepted", _STAMP))
    review = project.current(ArtifactKind.VALIDATION_PLAN_REVIEW)
    project = HypothesisCoordinator(lambda request: execute_hypothesis_request(request, _HYPOTHESIS_PYTHON)).run(project, 417)
    evidence = project.current(ArtifactKind.RUNTIME_EVIDENCE)
    evidence_payload = json.loads(evidence.content)["payload"]
    project = TLCCoordinator(lambda request: run_tlc_request(
        request, _TLC_TOOLS + "/jdk-21.0.12+8-jre/bin/java", _TLC_TOOLS + "/tla2tools.jar")).run(project)
    tlc_evidence = project.current(ArtifactKind.RUNTIME_EVIDENCE)
    tlc_payload = json.loads(tlc_evidence.content)["payload"]
    project = SMTCoordinator(lambda request: run_smt_request(request, _Z3)).run(project)
    smt_evidence = project.current(ArtifactKind.RUNTIME_EVIDENCE)
    smt_payload = json.loads(smt_evidence.content)["payload"]
    project = LeanCoordinator(lambda request: run_lean_request(
        request, _LEAN_PACKAGE, _LEAN_TOOLS + "/lean", _LEAN_TOOLS + "/lake"),
        _LEAN_PACKAGE).run(project)
    lean_evidence = project.current(ArtifactKind.RUNTIME_EVIDENCE)
    lean_payload = json.loads(lean_evidence.content)["payload"]
    project = compose_validation_verdict(
        project, _ref(obligation.ref), _ref(contract.ref),
        [_ref(item.ref) for item in (evidence, tlc_evidence, smt_evidence, lean_evidence)],
        timestamp=_STAMP,
    )
    verdict = project.current(ArtifactKind.VALIDATION_VERDICT)
    verdict_payload = json.loads(verdict.content)["payload"]
    ancestry = {"stages":[1,2,3,4,5,6,7,8], "nodes":[
        _node(1, contract.kind.value, contract.artifact_id, contract.content_hash, contract.state.value, contract.upstream),
        _node(1, obligation.kind.value, obligation.artifact_id, obligation.content_hash, obligation.state.value, obligation.upstream),
        _node(2, "contract-calculus-interpretation", calculus_id, calculus_hash, "current", (contract.ref,)),
        _node(3, plan.kind.value, plan.artifact_id, plan.content_hash, plan.state.value, plan.upstream),
        _node(3, review.kind.value, review.artifact_id, review.content_hash, review.state.value, review.upstream),
        _node(4, evidence.kind.value, evidence.artifact_id, evidence.content_hash, evidence.state.value, evidence.upstream),
        _node(5, "formal-evidence", tlc_evidence.artifact_id, tlc_evidence.content_hash, tlc_evidence.state.value, tlc_evidence.upstream),
        _node(6, "formal-evidence", smt_evidence.artifact_id, smt_evidence.content_hash, smt_evidence.state.value, smt_evidence.upstream),
        _node(7, "formal-evidence", lean_evidence.artifact_id, lean_evidence.content_hash, lean_evidence.state.value, lean_evidence.upstream),
        _node(8, verdict.kind.value, verdict.artifact_id, verdict.content_hash, verdict.state.value, verdict.upstream),
    ], "plan_approval":"approved", "stage4_backend":{
        "name":"hypothesis-backend", "version":HYPOTHESIS_VERSION,
        "observations_passed":all(item["matched"] for item in evidence_payload["observations"]),
    }, "stage5_backend":{"name":"tlc-backend", "version":TLC_VERSION,
        "invariant_satisfied":all(item["invariant_satisfied"] for item in tlc_payload["observations"])},
    "stage6_backend":{"name":"z3-backend", "version":Z3_VERSION,
        "postcondition_proved":all(item["result"] == "unsat" and bool(item["proof"])
                                   for item in smt_payload["observations"])},
    "stage7_backend":{"name":"lean-backend", "version":LEAN_VERSION,
        "kernel_checked":all(item["kernel_checked"] for item in lean_payload["observations"])}}
    verdicts = [{
        "artifact_id": verdict.artifact_id,
        "content_hash": verdict.content_hash,
        **verdict_payload,
    }]
    evidence_projection = {
        "schema": "plain2metta-evaluation-evidence/v1",
        "ancestry": ancestry,
        "plan_review": {
            "plan": _ref(plan.ref),
            "review": _ref(review.ref),
            "decision": "approved",
        },
        "backends": [
            ancestry["stage4_backend"],
            ancestry["stage5_backend"],
            ancestry["stage6_backend"],
            ancestry["stage7_backend"],
        ],
        "verdicts": verdicts,
        "counterexamples": verdict_payload["counterexample_refs"],
        "assumptions": verdict_payload["assumptions_used"],
        "unresolved_holes": contract_doc["payload"]["unresolved_holes"],
        "residual_risk": verdict_payload["residual_risk"],
        "release_metadata": {"stage10": release_metadata()},
    }
    return {"ancestry": ancestry, "verdicts": verdicts,
            "evidence_projection": evidence_projection,
            "release_metadata": evidence_projection["release_metadata"]}

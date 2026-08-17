"""Stage-8 dual-runtime normalization and conservative evidence composition."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any, Mapping, Sequence

from .projects import ApprovalDecision, ArtifactKind, ArtifactRef, ArtifactState, Project, add_semantic_artifact
from .semantic_artifacts import build_semantic_artifact, validate_semantic_artifact
from .validation_plan import validate_plan_review_chain

GRADE_KEYS = tuple(f"G{i}" for i in range(7))
RUNTIME_TO_GRADE = {
    "python-hypothesis": "G4", "tla-tlc": "G5", "z3-smtlib": "G5",
    "lean4-kernel": "G5", "hyperon-metta": "G2", "python-reference": "G2",
}


def _ref(ref: ArtifactRef) -> dict[str, str]:
    return {"artifact_id": ref.artifact_id, "content_hash": ref.content_hash}


def _artifact(project: Project, value: Mapping[str, str], kind: ArtifactKind | None = None):
    if not isinstance(value, Mapping) or set(value) != {"artifact_id", "content_hash"}:
        raise ValueError("artifact reference is malformed or path-confused")
    artifact = project.artifact(value["artifact_id"])
    if artifact.content_hash != value["content_hash"] or artifact.state is not ArtifactState.CURRENT:
        raise ValueError("artifact reference is stale or hash-mismatched")
    if kind is not None and artifact.kind is not kind:
        raise ValueError("artifact reference has the wrong kind")
    return artifact


def normalize_observation(value: object) -> dict[str, Any]:
    """Normalize a closed observation; implementation-produced expectations are forbidden."""
    fields = {"case_id", "actual", "expected", "matched", "oracle_id", "oracle_role"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("runtime observation is malformed")
    if value["oracle_role"] != "independent-validation-author":
        raise ValueError("runtime observation lacks an independent oracle")
    if not all(isinstance(value[key], str) and value[key].strip() for key in ("case_id", "oracle_id")):
        raise ValueError("runtime observation identity is invalid")
    if isinstance(value["actual"], float) or isinstance(value["expected"], float):
        raise ValueError("binary-float observations are not canonical")
    matched = value["actual"] == value["expected"]
    if type(value["matched"]) is not bool or value["matched"] != matched:
        raise ValueError("runtime observation match flag contradicts normalized values")
    return {key: value[key] for key in sorted(fields)}


def _runtime_record(project: Project, ref: Mapping[str, str]) -> tuple[Any, dict[str, Any]]:
    artifact = _artifact(project, ref, ArtifactKind.RUNTIME_EVIDENCE)
    document = json.loads(artifact.content)
    validate_semantic_artifact(document)
    return artifact, document["payload"]


def _formal_result(runtime: str, payload: Mapping[str, Any]) -> str:
    """Return pass/fail/unknown from the backend's own closed observation format."""
    observations = payload.get("observations")
    if not isinstance(observations, list) or not observations:
        return "unknown"
    if payload.get("exit_status") in {124, 137}:
        return "unknown"
    if runtime == "tla-tlc":
        return "pass" if all(isinstance(x, Mapping) and x.get("invariant_satisfied") is True
                             and x.get("exit_status") == 0 and not x.get("counterexample_trace")
                             for x in observations) else "fail"
    if runtime == "z3-smtlib":
        return "pass" if all(isinstance(x, Mapping) and x.get("result") in {"sat", "unsat"}
                             and x.get("result") == x.get("expected_result")
                             and x.get("exit_status") == 0 for x in observations) else "fail"
    if runtime == "lean4-kernel":
        return "pass" if all(isinstance(x, Mapping) and x.get("kernel_checked") is True
                             for x in observations) and payload.get("exit_status") == 0 else "fail"
    return "unknown"


def compose_validation_verdict(
    project: Project,
    obligation_ref: Mapping[str, str],
    implementation_ref: Mapping[str, str],
    evidence_refs: Sequence[Mapping[str, str]],
    *,
    timestamp: str,
) -> Project:
    """Atomically join exact evidence without allowing one tool to over-promote."""
    validate_plan_review_chain(project)
    obligation = _artifact(project, obligation_ref, ArtifactKind.VALIDATION_OBLIGATION)
    implementation = _artifact(project, implementation_ref)
    plan = project.current(ArtifactKind.VALIDATION_PLAN)
    review = project.current(ArtifactKind.VALIDATION_PLAN_REVIEW)
    source = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
    if plan is None or review is None or source is None:
        raise ValueError("verdict requires exact source, plan, and review ancestry")
    approvals = [x for x in project.approvals if x.artifact == plan.ref]
    if len(approvals) != 1 or approvals[0].decision is not ApprovalDecision.APPROVED:
        raise ValueError("verdict requires exactly one approved current plan")
    obligation_doc = json.loads(obligation.content); validate_semantic_artifact(obligation_doc)
    payload = obligation_doc["payload"]
    if obligation.ref not in plan.upstream:
        raise ValueError("plan does not bind the exact obligation")
    if not isinstance(evidence_refs, Sequence) or isinstance(evidence_refs, (str, bytes)) or not evidence_refs:
        raise ValueError("verdict requires runtime evidence")
    records = [_runtime_record(project, ref) for ref in evidence_refs]
    if len({artifact.ref for artifact, _ in records}) != len(records):
        raise ValueError("duplicate runtime evidence")
    for artifact, evidence in records:
        if plan.ref not in artifact.upstream or obligation.ref not in artifact.upstream:
            raise ValueError("runtime evidence lacks exact shared plan/obligation ancestry")
        if evidence["exit_status"] in {124, 137}:
            pass
        elif type(evidence["exit_status"]) is not int:
            raise ValueError("runtime exit status is malformed")

    by_runtime = {evidence["runtime"]: evidence for _, evidence in records}
    if len(by_runtime) != len(records):
        raise ValueError("duplicate runtime role")
    grades = {key: False for key in GRADE_KEYS}; grades["G0"] = grades["G1"] = True
    status = "pass"
    reasons: list[str] = []
    assumptions = payload["assumptions"]
    if payload["unresolved"]:
        status, reasons = "blocked", ["unresolved obligation meaning"]
    timed_out = any(item["exit_status"] in {124, 137} for item in by_runtime.values())
    if timed_out and status == "pass":
        status, reasons = "unknown", ["runtime timeout or resource exhaustion"]

    runtime_names = {"hyperon-metta", "python-reference"}
    dual = runtime_names.issubset(by_runtime)
    normalized: dict[str, list[dict[str, Any]]] = {}
    for name in runtime_names & by_runtime.keys():
        normalized[name] = [normalize_observation(item) for item in by_runtime[name]["observations"]]
    if dual:
        left, right = normalized["hyperon-metta"], normalized["python-reference"]
        grades["G2"] = all(by_runtime[name]["exit_status"] == 0 for name in runtime_names)
        if left != right:
            status, reasons = "fail", ["cross-runtime divergence"]
        elif any(not item["matched"] for item in left):
            status, reasons = "fail", ["wrong output against independent oracle"]
        elif grades["G2"]:
            grades["G3"] = True
    elif status == "pass":
        status, reasons = "unknown", ["missing dual-runtime evidence"]

    hypothesis = by_runtime.get("python-hypothesis")
    if hypothesis is not None:
        failed = any(not item.get("matched", False) for item in hypothesis["observations"] if isinstance(item, Mapping))
        if failed or hypothesis["exit_status"] != 0:
            status, reasons = "fail", ["property evidence contains a counterexample"]
        else:
            grades["G4"] = True

    required_methods = set(payload["admissible_methods"])
    formal_runtime = {"tlc": "tla-tlc", "smt": "z3-smtlib", "lean": "lean4-kernel"}
    required_formal = {runtime for method, runtime in formal_runtime.items() if method in required_methods}
    present_formal = required_formal & by_runtime.keys()
    formal_results = {name: _formal_result(name, by_runtime[name]) for name in present_formal}
    bad_formal = [name for name, result in formal_results.items() if result == "fail"]
    unknown_formal = [name for name, result in formal_results.items() if result == "unknown"]
    if bad_formal:
        status, reasons = "fail", ["formal backend rejected the obligation: " + ",".join(sorted(bad_formal))]
    elif unknown_formal and status == "pass":
        status, reasons = "unknown", ["formal backend was inconclusive: " + ",".join(sorted(unknown_formal))]
    if required_formal and present_formal == required_formal and not bad_formal and not unknown_formal:
        grades["G5"] = True
    elif payload["required_grade"] == "G5" and status == "pass":
        status, reasons = "blocked", ["missing required formal proof/check evidence"]

    if status == "pass" and not grades[payload["required_grade"]]:
        status, reasons = "unknown", ["required evidence grade not achieved"]
    achieved = [key for key in GRADE_KEYS if grades[key]]
    ancestry = []
    for ref in [*plan.upstream, plan.ref, review.ref, implementation.ref,
                *(artifact.ref for artifact, _ in records)]:
        if ref not in ancestry:
            ancestry.append(ref)
    provenance = {"producer":"cross-tool-verdict-composer","version":"1","operation":"compose-grade-vector",
                  "timestamp":timestamp,"input_hashes":[ref.content_hash for ref in [source.ref,*ancestry[1:]]]}
    verdict_payload = {
        "verdict_id":"verdict:" + sha256((obligation.content_hash + plan.content_hash + "".join(x.content_hash for x in ancestry)).encode()).hexdigest()[:24],
        "obligation_ref":_ref(obligation.ref), "implementation_ref":_ref(implementation.ref),
        "validation_plan_ref":_ref(plan.ref), "runtime_evidence_refs":[_ref(x.ref) for x, _ in records],
        "grade_achieved":{"vector":grades,"achieved":achieved,"required":payload["required_grade"]},
        "status":status, "counterexample_refs":[],
        "residual_risk":"; ".join(reasons) if reasons else "bounded evidence only; assumptions and domains remain explicit",
        "assumptions_used":assumptions,
    }
    artifact = build_semantic_artifact("ValidationVerdict", source.ref, ancestry[1:], provenance, verdict_payload)
    return add_semantic_artifact(project, artifact)

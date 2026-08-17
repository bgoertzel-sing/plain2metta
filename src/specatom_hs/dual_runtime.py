"""Approved-plan dual-runtime execution with independent plan oracles."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Callable, Mapping

from .evaluation_sandbox import run_metta_reference, run_python_reference
from .projects import ApprovalDecision, ArtifactKind, Project, add_semantic_artifact
from .semantic_artifacts import build_semantic_artifact, validate_semantic_artifact
from .validation_plan import validate_plan_review_chain


def _ref(value):
    return {"artifact_id": value.artifact_id, "content_hash": value.content_hash}


def _approved_inputs(project: Project):
    validate_plan_review_chain(project)
    source = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
    plan = project.current(ArtifactKind.VALIDATION_PLAN)
    review = project.current(ArtifactKind.VALIDATION_PLAN_REVIEW)
    if source is None or plan is None or review is None:
        raise ValueError("dual-runtime execution requires source, plan, and review")
    approvals = [item for item in project.approvals if item.artifact == plan.ref]
    if len(approvals) != 1 or approvals[0].decision is not ApprovalDecision.APPROVED:
        raise ValueError("dual-runtime execution requires exactly one approved plan")
    document = json.loads(plan.content); validate_semantic_artifact(document)
    examples = document["payload"]["examples"]
    if not isinstance(examples, list) or not examples:
        raise ValueError("approved plan has no executable examples")
    oracles = {}
    for example in examples:
        if not isinstance(example, Mapping) or set(example) != {"case_id", "input", "expected"}:
            raise ValueError("plan example is malformed or contains executable prose")
        case_id = example["case_id"]
        if not isinstance(case_id, str) or not case_id.strip() or case_id in oracles:
            raise ValueError("plan example identity is invalid or duplicated")
        if isinstance(example["expected"], float):
            raise ValueError("binary-float plan oracle is not canonical")
        oracles[case_id] = example["expected"]
    return source, plan, review, oracles


def _observations(result: Mapping[str, Any], oracles: Mapping[str, Any]) -> list[dict[str, Any]]:
    if type(result.get("exit_code")) is not int:
        raise ValueError("runtime result is malformed")
    if result["exit_code"] != 0:
        return []
    actual = {}
    for line in result.get("stdout", "").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("runtime output is not canonical JSON Lines") from exc
        if not isinstance(item, Mapping) or set(item) != {"case_id", "actual"}:
            raise ValueError("runtime observation has unknown or missing fields")
        if item["case_id"] in actual or item["case_id"] not in oracles:
            raise ValueError("runtime observation is duplicated or path-confused")
        if isinstance(item["actual"], float):
            raise ValueError("binary-float runtime output is not canonical")
        actual[item["case_id"]] = item["actual"]
    if set(actual) != set(oracles):
        raise ValueError("runtime omitted an approved plan case")
    return [{"case_id": case_id, "actual": actual[case_id], "expected": expected,
             "matched": actual[case_id] == expected, "oracle_id": "plan:" + case_id,
             "oracle_role": "independent-validation-author"}
            for case_id, expected in sorted(oracles.items())]


def run_approved_dual_runtime(
    project: Project, *, python_source: str, metta_source: str, timestamp: str,
    python_runner: Callable[[str], Mapping[str, Any]] = run_python_reference,
    metta_runner: Callable[[str], Mapping[str, Any]] = run_metta_reference,
) -> Project:
    """Run reviewed implementations; expectations come only from the approved plan."""
    if not all(isinstance(value, str) and value.strip() for value in (python_source, metta_source, timestamp)):
        raise ValueError("dual-runtime source and timestamp must be non-blank")
    source, plan, review, oracles = _approved_inputs(project)
    before = (source.ref, plan.ref, review.ref)
    results = {
        "python-reference": (python_source, python_runner(python_source)),
        "hyperon-metta": (metta_source, metta_runner(metta_source)),
    }
    if tuple(project.current(kind).ref for kind in (ArtifactKind.REVIEWED_ELABORATED_SPEC,
            ArtifactKind.VALIDATION_PLAN, ArtifactKind.VALIDATION_PLAN_REVIEW)) != before:
        raise ValueError("dual-runtime ancestry changed during execution")
    ancestry = [*plan.upstream, plan.ref, review.ref]
    updated = project
    for runtime, (implementation, result) in results.items():
        observations = _observations(result, oracles)
        implementation_hash = "sha256:" + sha256(implementation.encode("utf-8", errors="surrogatepass")).hexdigest()
        limits = result.get("limits")
        if not isinstance(limits, Mapping):
            raise ValueError("runtime result lacks resource bounds")
        provenance = {"producer": runtime, "version": "1", "operation": "approved-plan-dual-runtime",
                      "timestamp": timestamp, "input_hashes": [x.content_hash for x in ancestry]}
        payload = {"evidence_id": "evidence:" + runtime + ":" + implementation_hash[7:31],
                   "runtime": runtime, "runtime_hash": implementation_hash,
                   "resource_bounds": dict(limits), "case_id": "approved-plan-examples",
                   "seed": None, "observations": observations, "exit_status": result["exit_code"],
                   "artifact_hashes": [x.content_hash for x in ancestry],
                   "started_at": timestamp, "finished_at": timestamp}
        document = build_semantic_artifact("RuntimeEvidence", source.ref, ancestry[1:], provenance, payload)
        updated = add_semantic_artifact(updated, document)
    return updated

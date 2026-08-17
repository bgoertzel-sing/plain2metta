"""Independent Stage-3 validation-plan authoring and exact review admission."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Callable, Mapping

from .projects import (
    ApprovalDecision, ArtifactKind, ArtifactRef, Project, add_semantic_artifact,
    add_validation_plan_review, decide,
)
from .semantic_artifacts import (
    build_semantic_artifact, validate_semantic_artifact,
)


REQUEST_SCHEMA = "plain2metta-validation-plan-request/v1"
RESPONSE_SCHEMA = "plain2metta-validation-plan-response/v1"
REVIEW_SCHEMA = "plain2metta-validation-plan-review/v1"


@dataclass(frozen=True)
class ValidationPlanRequest:
    reviewed_source: ArtifactRef
    reviewed_source_text: str
    contracts: tuple[Mapping[str, Any], ...]
    obligations: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class AdapterProvenance:
    backend: str
    model: str
    interaction_id: str
    input_tokens: int
    output_tokens: int
    timestamp: str


@dataclass(frozen=True)
class ValidationPlanResponse:
    request_hash: str
    plan_payload: Mapping[str, Any]
    provenance: AdapterProvenance


@dataclass(frozen=True)
class PlanReview:
    plan: ArtifactRef
    decision: ApprovalDecision
    reviewer: str
    rationale: str
    timestamp: str
    edited_plan_payload: Mapping[str, Any] | None = None


def _exact(value: object, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{label} has unknown or missing fields")
    return value


def _ref(value: object, label: str) -> ArtifactRef:
    item = _exact(value, {"artifact_id", "content_hash"}, label)
    if not isinstance(item["artifact_id"], str) or not isinstance(item["content_hash"], str):
        raise ValueError(f"{label} is malformed")
    return ArtifactRef(item["artifact_id"], item["content_hash"])


def _ref_dict(ref: ArtifactRef) -> dict[str, str]:
    return {"artifact_id": ref.artifact_id, "content_hash": ref.content_hash}


def _stored_artifact_for_document(project: Project, document: Mapping[str, Any]):
    """Resolve a semantic document id to its immutable project artifact."""
    matches = []
    for artifact in project.artifacts:
        if artifact.state.value != "current" or artifact.kind not in {
            ArtifactKind.SEMANTIC_CONTRACT, ArtifactKind.VALIDATION_OBLIGATION,
        }:
            continue
        try:
            stored = json.loads(artifact.content)
        except json.JSONDecodeError:
            continue
        if stored.get("artifact_id") == document.get("artifact_id"):
            matches.append(artifact)
    if len(matches) != 1:
        raise ValueError("semantic document does not resolve to one current artifact")
    return matches[0]


def build_validation_plan_request(project: Project) -> ValidationPlanRequest:
    source = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
    if source is None:
        raise ValueError("validation-plan synthesis requires reviewed source")
    contracts = []
    obligations = []
    for artifact in project.artifacts:
        if artifact.state.value != "current":
            continue
        if artifact.kind not in {ArtifactKind.SEMANTIC_CONTRACT, ArtifactKind.VALIDATION_OBLIGATION}:
            continue
        document = json.loads(artifact.content)
        validate_semantic_artifact(document)
        if document["reviewed_source_ref"] != _ref_dict(source.ref):
            raise ValueError("semantic input does not bind current reviewed source")
        (contracts if artifact.kind is ArtifactKind.SEMANTIC_CONTRACT else obligations).append(document)
    if not contracts or not obligations:
        raise ValueError("validation-plan synthesis requires contracts and obligations")
    contracts.sort(key=lambda item: item["artifact_id"])
    obligations.sort(key=lambda item: item["artifact_id"])
    return ValidationPlanRequest(source.ref, source.content, tuple(contracts), tuple(obligations))


def validation_plan_request_to_dict(request: ValidationPlanRequest) -> dict[str, Any]:
    return {
        "schema": REQUEST_SCHEMA,
        "reviewed_source": _ref_dict(request.reviewed_source),
        "reviewed_source_text": request.reviewed_source_text,
        "contracts": list(request.contracts),
        "obligations": list(request.obligations),
    }


def validation_plan_request_hash(request: ValidationPlanRequest) -> str:
    encoded = json.dumps(validation_plan_request_to_dict(request), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(encoded.encode("utf-8", errors="surrogatepass")).hexdigest()


def validation_plan_response_from_dict(value: object) -> ValidationPlanResponse:
    item = _exact(value, {"schema", "request_hash", "plan_payload", "provenance"}, "validation-plan response")
    if item["schema"] != RESPONSE_SCHEMA:
        raise ValueError("unsupported validation-plan response schema")
    provenance = _exact(item["provenance"], {"backend", "model", "interaction_id", "input_tokens", "output_tokens", "timestamp"}, "adapter provenance")
    if any(not isinstance(provenance[k], str) or not provenance[k].strip() for k in ("backend", "model", "interaction_id", "timestamp")):
        raise ValueError("adapter provenance text must be non-blank")
    if any(type(provenance[k]) is not int or provenance[k] < 0 for k in ("input_tokens", "output_tokens")):
        raise ValueError("adapter token counts are invalid")
    if not isinstance(item["request_hash"], str) or not isinstance(item["plan_payload"], Mapping):
        raise ValueError("validation-plan response is malformed")
    return ValidationPlanResponse(item["request_hash"], dict(item["plan_payload"]), AdapterProvenance(**provenance))


class ValidationPlanCoordinator:
    """Makes exactly one provider-independent call and atomically admits it."""

    def __init__(self, adapter: Callable[[Mapping[str, Any]], object]):
        self._adapter = adapter

    def synthesize(self, project: Project) -> Project:
        request = build_validation_plan_request(project)
        raw = self._adapter(validation_plan_request_to_dict(request))
        response = validation_plan_response_from_dict(raw)
        request_hash = validation_plan_request_hash(request)
        if response.request_hash != request_hash:
            raise ValueError("adapter output is misattributed to another request")
        if build_validation_plan_request(project) != request:
            raise ValueError("validation-plan inputs changed during adapter call")
        source = project.artifact(request.reviewed_source.artifact_id)
        inputs = [_stored_artifact_for_document(project, item).ref for item in (*request.contracts, *request.obligations)]
        provenance = {
            "producer": f"{response.provenance.backend}:{response.provenance.model}",
            "version": "1",
            "operation": "independent-validation-author",
            "timestamp": response.provenance.timestamp,
            "input_hashes": [source.content_hash, *[ref.content_hash for ref in inputs]],
        }
        payload = dict(response.plan_payload)
        expected_contracts = [_ref_dict(_stored_artifact_for_document(project, item).ref) for item in request.contracts]
        if payload.get("reviewed_contract_refs") != expected_contracts:
            raise ValueError("plan does not bind the exact reviewed contracts")
        if payload.get("author_provenance") != {
            "role": "validation-author", "request_hash": request_hash,
            "backend": response.provenance.backend, "model": response.provenance.model,
            "interaction_id": response.provenance.interaction_id,
        }:
            raise ValueError("plan author provenance does not match adapter interaction")
        document = build_semantic_artifact("ValidationPlan", source.ref, inputs, provenance, payload)
        return add_semantic_artifact(project, document)


def _critical_meaning_resolved(project: Project) -> None:
    for kind in (ArtifactKind.SEMANTIC_CONTRACT, ArtifactKind.VALIDATION_OBLIGATION):
        for artifact in project.artifacts:
            if artifact.kind is not kind or artifact.state.value != "current":
                continue
            payload = json.loads(artifact.content)["payload"]
            if kind is ArtifactKind.SEMANTIC_CONTRACT and payload["unresolved_holes"]:
                raise ValueError("unresolved contract meaning blocks plan approval")
            if kind is ArtifactKind.VALIDATION_OBLIGATION and payload["severity"] == "critical" and payload["unresolved"]:
                raise ValueError("unresolved critical obligation blocks plan approval")


def submit_plan_review(project: Project, review: PlanReview) -> Project:
    plan = project.current(ArtifactKind.VALIDATION_PLAN)
    if plan is None or plan.ref != review.plan:
        raise ValueError("plan review is stale or hash-mismatched")
    if review.decision not in {ApprovalDecision.APPROVED, ApprovalDecision.CHANGES_REQUESTED, ApprovalDecision.REJECTED}:
        raise ValueError("invalid plan-review decision")
    if any(not isinstance(value, str) or not value.strip() for value in (review.reviewer, review.rationale, review.timestamp)):
        raise ValueError("plan review requires reviewer, rationale, and timestamp")
    if review.edited_plan_payload is not None:
        if review.decision is not ApprovalDecision.APPROVED:
            raise ValueError("reviewer edits require approval of the edited bytes")
        original = json.loads(plan.content)
        source_ref = _ref(original["reviewed_source_ref"], "reviewed source")
        refs = [_ref(item, "plan upstream") for item in original["upstream_refs"]]
        provenance = {
            "producer": review.reviewer, "version": "1", "operation": "validation-plan-review-edit",
            "timestamp": review.timestamp, "input_hashes": [ref.content_hash for ref in [*refs, plan.ref]],
        }
        document = build_semantic_artifact("ValidationPlan", source_ref, [*refs[1:], plan.ref], provenance, review.edited_plan_payload)
        project = add_semantic_artifact(project, document)
        plan = project.current(ArtifactKind.VALIDATION_PLAN)
    if review.decision is ApprovalDecision.APPROVED:
        _critical_meaning_resolved(project)
    record = {
        "schema": REVIEW_SCHEMA, "plan": _ref_dict(plan.ref), "decision": review.decision.value,
        "reviewer": review.reviewer, "rationale": review.rationale, "timestamp": review.timestamp,
        "edited": review.edited_plan_payload is not None,
    }
    content = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    project = add_validation_plan_review(project, content, plan.ref)
    return decide(project, plan.ref, review.decision, review.reviewer, review.rationale)


def validate_plan_review_chain(project: Project) -> None:
    review = project.current(ArtifactKind.VALIDATION_PLAN_REVIEW)
    if review is None:
        return
    plan = project.current(ArtifactKind.VALIDATION_PLAN)
    if plan is None or review.upstream != (plan.ref,):
        raise ValueError("validation-plan review does not bind current plan")
    item = _exact(json.loads(review.content), {"schema", "plan", "decision", "reviewer", "rationale", "timestamp", "edited"}, "plan review")
    if item["schema"] != REVIEW_SCHEMA or _ref(item["plan"], "reviewed plan") != plan.ref:
        raise ValueError("validation-plan review binding mismatch")
    if item["decision"] not in {decision.value for decision in (ApprovalDecision.APPROVED, ApprovalDecision.CHANGES_REQUESTED, ApprovalDecision.REJECTED)}:
        raise ValueError("validation-plan review decision is invalid")
    if any(not isinstance(item[key], str) or not item[key].strip() for key in ("reviewer", "rationale", "timestamp")) or type(item["edited"]) is not bool:
        raise ValueError("validation-plan review metadata is malformed")
    decisions = [a for a in project.approvals if a.artifact == plan.ref]
    if len(decisions) != 1 or decisions[0].decision.value != item["decision"] or decisions[0].reviewer != item["reviewer"] or decisions[0].rationale != item["rationale"]:
        raise ValueError("validation-plan approval does not match immutable review")

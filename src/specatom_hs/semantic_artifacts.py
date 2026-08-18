"""Strict immutable documents for revision-0.2 Stage-1 semantic artifacts."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Any, Mapping

from .projects import ArtifactKind, ArtifactRef


SCHEMA = "plain2metta-semantic-artifact/v1"
_ID = re.compile(r"[A-Za-z][A-Za-z0-9._:-]{0,127}\Z")
_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")

TYPE_TO_KIND = {
    "SemanticContract": ArtifactKind.SEMANTIC_CONTRACT,
    "ValidationObligation": ArtifactKind.VALIDATION_OBLIGATION,
    "ValidationPlan": ArtifactKind.VALIDATION_PLAN,
    "InputGenerator": ArtifactKind.INPUT_GENERATOR,
    "ValidationOracle": ArtifactKind.VALIDATION_ORACLE,
    "RuntimeEvidence": ArtifactKind.RUNTIME_EVIDENCE,
    "Counterexample": ArtifactKind.COUNTEREXAMPLE,
    "ValidationVerdict": ArtifactKind.VALIDATION_VERDICT,
}

PAYLOAD_FIELDS = {
    "SemanticContract": {"contract_id", "source_clause_refs", "name", "inputs", "output", "preconditions", "postconditions", "invariants", "effects", "temporal_constraints", "nondeterminism", "environment_assumptions", "unresolved_holes"},
    "ValidationObligation": {"obligation_id", "contract_ref", "source_clause_refs", "claim", "required_grade", "admissible_methods", "domain", "assumptions", "severity", "unresolved"},
    "ValidationPlan": {"plan_id", "reviewed_contract_refs", "author_provenance", "examples", "generators", "properties", "metamorphic_relations", "state_models", "differential_oracles", "formal_tasks", "coverage_claims"},
    "InputGenerator": {"generator_id", "domain", "budget", "distribution", "shrinker", "seed"},
    "ValidationOracle": {"oracle_id", "method", "obligation_refs", "semantics", "ownership_locus", "bounds", "expected_observations"},
    "RuntimeEvidence": {"evidence_id", "runtime", "runtime_hash", "resource_bounds", "case_id", "seed", "observations", "exit_status", "artifact_hashes", "started_at", "finished_at"},
    "Counterexample": {"counterexample_id", "obligation_ref", "evidence_ref", "case", "observations", "shrinking", "replay"},
    "ValidationVerdict": {"verdict_id", "obligation_ref", "implementation_ref", "validation_plan_ref", "runtime_evidence_refs", "grade_achieved", "status", "counterexample_refs", "residual_risk", "assumptions_used"},
}


def _exact(value: object, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{label} has unknown or missing fields")
    return value


def _ref(value: object, label: str) -> ArtifactRef:
    item = _exact(value, {"artifact_id", "content_hash"}, label)
    artifact_id, digest = item["artifact_id"], item["content_hash"]
    if not isinstance(artifact_id, str) or _ID.fullmatch(artifact_id) is None:
        raise ValueError(f"{label} artifact_id is not canonical")
    if not isinstance(digest, str) or _HASH.fullmatch(digest) is None:
        raise ValueError(f"{label} content_hash is not canonical")
    return ArtifactRef(artifact_id, digest)


def _json_value(value: object, label: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        raise ValueError(f"{label} floats are forbidden; use canonical decimal text")
    if isinstance(value, list):
        for item in value:
            _json_value(item, label)
        return
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _json_value(item, label)
        return
    raise ValueError(f"{label} is not canonical JSON data")


def _embedded_refs(value: object) -> list[ArtifactRef]:
    refs: list[ArtifactRef] = []
    if isinstance(value, Mapping):
        if set(value) == {"artifact_id", "content_hash"}:
            refs.append(_ref(value, "payload artifact reference"))
        else:
            for item in value.values():
                refs.extend(_embedded_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_embedded_refs(item))
    return refs


def semantic_artifact_id(document: Mapping[str, Any]) -> str:
    body = dict(document)
    body.pop("artifact_id", None)
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "semantic-" + sha256(encoded.encode("utf-8", errors="surrogatepass")).hexdigest()[:24]


def validate_semantic_artifact(document: object) -> tuple[ArtifactKind, tuple[ArtifactRef, ...]]:
    item = _exact(document, {"schema", "artifact_type", "artifact_id", "reviewed_source_ref", "upstream_refs", "provenance", "payload"}, "semantic artifact")
    if item["schema"] != SCHEMA:
        raise ValueError("unsupported semantic artifact schema")
    artifact_type = item["artifact_type"]
    if artifact_type not in TYPE_TO_KIND:
        raise ValueError("unknown semantic artifact type")
    if item["artifact_id"] != semantic_artifact_id(item):
        raise ValueError("semantic artifact_id does not match canonical bytes")
    source = _ref(item["reviewed_source_ref"], "reviewed_source_ref")
    if not isinstance(item["upstream_refs"], list):
        raise ValueError("upstream_refs must be a list")
    refs = tuple(_ref(value, "upstream_ref") for value in item["upstream_refs"])
    if not refs or refs[0] != source:
        raise ValueError("reviewed source must be the first upstream reference")
    if len(set(refs)) != len(refs):
        raise ValueError("duplicate upstream reference")
    provenance = _exact(item["provenance"], {"producer", "version", "operation", "timestamp", "input_hashes"}, "provenance")
    if not all(isinstance(provenance[key], str) and provenance[key] for key in ("producer", "version", "operation", "timestamp")):
        raise ValueError("provenance identity fields must be non-blank text")
    if not isinstance(provenance["input_hashes"], list) or provenance["input_hashes"] != [ref.content_hash for ref in refs]:
        raise ValueError("provenance input_hashes do not match exact upstream order")
    payload = _exact(item["payload"], PAYLOAD_FIELDS[artifact_type], f"{artifact_type} payload")
    _json_value(payload, "payload")
    embedded = _embedded_refs(payload)
    if any(ref not in refs for ref in embedded):
        raise ValueError("payload reference is absent from exact upstream_refs")
    requires_contract = artifact_type in {
        "ValidationObligation", "ValidationPlan", "InputGenerator", "ValidationOracle",
        "RuntimeEvidence", "Counterexample", "ValidationVerdict",
    }
    if requires_contract and len(refs) < 2:
        raise ValueError(f"{artifact_type} must bind reviewed source and contract ancestry")
    if artifact_type in {"ValidationObligation", "ValidationPlan", "Counterexample", "ValidationVerdict"} and not embedded:
        raise ValueError(f"{artifact_type} must carry exact typed artifact references")
    identity = next((payload[key] for key in payload if key.endswith("_id")), None)
    if not isinstance(identity, str) or _ID.fullmatch(identity) is None:
        raise ValueError("payload canonical identity is missing or invalid")
    if artifact_type == "ValidationVerdict" and payload["status"] not in {"pass", "fail", "unknown", "blocked"}:
        raise ValueError("invalid verdict status")
    if artifact_type == "ValidationObligation" and payload["severity"] not in {"critical", "major", "minor"}:
        raise ValueError("invalid obligation severity")
    if artifact_type == "ValidationPlan":
        provenance = _exact(payload["author_provenance"], {"role", "request_hash", "backend", "model", "interaction_id"}, "validation-plan author provenance")
        if provenance["role"] != "validation-author" or any(not isinstance(provenance[key], str) or not provenance[key].strip() for key in provenance):
            raise ValueError("validation-plan author provenance is invalid")
        if not isinstance(payload["reviewed_contract_refs"], list) or not payload["reviewed_contract_refs"]:
            raise ValueError("validation plan requires reviewed contracts")
        if len({_ref(item, "reviewed contract") for item in payload["reviewed_contract_refs"]}) != len(payload["reviewed_contract_refs"]):
            raise ValueError("validation plan has duplicate reviewed contracts")
        for field in ("examples", "generators", "properties", "metamorphic_relations", "state_models", "differential_oracles", "formal_tasks", "coverage_claims"):
            if not isinstance(payload[field], list):
                raise ValueError(f"validation-plan {field} must be a list")
    return TYPE_TO_KIND[artifact_type], refs


def canonical_semantic_artifact(document: object) -> str:
    validate_semantic_artifact(document)
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def semantic_artifact_from_dict(payload: Mapping[str, Any]) -> dict[str, Any]:
    document = json.loads(json.dumps(payload, ensure_ascii=False))
    validate_semantic_artifact(document)
    return document


def build_semantic_artifact(artifact_type: str, reviewed_source_ref: ArtifactRef, upstream_refs: list[ArtifactRef], provenance: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    refs = [reviewed_source_ref, *upstream_refs]
    document: dict[str, Any] = {
        "schema": SCHEMA,
        "artifact_type": artifact_type,
        "artifact_id": "",
        "reviewed_source_ref": {"artifact_id": reviewed_source_ref.artifact_id, "content_hash": reviewed_source_ref.content_hash},
        "upstream_refs": [{"artifact_id": ref.artifact_id, "content_hash": ref.content_hash} for ref in refs],
        "provenance": dict(provenance),
        "payload": dict(payload),
    }
    document["artifact_id"] = semantic_artifact_id(document)
    validate_semantic_artifact(document)
    return document

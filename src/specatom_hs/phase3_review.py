"""Strict exact-version Phase 3 review decisions and review-log format."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from .projects import ApprovalDecision, ArtifactRef


@dataclass(frozen=True)
class Phase3Decision:
    artifact: ArtifactRef
    decision: ApprovalDecision
    reviewer: str
    timestamp: str
    target: str | None = None
    comment: str | None = None


@dataclass(frozen=True)
class Phase3ReviewLog:
    elaborated_spec: ArtifactRef
    test_spec: ArtifactRef
    decisions: tuple[Phase3Decision, ...]


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.utcoffset() is not None and parsed.microsecond == 0


def validate_phase3_review_log(
    log: object, elaborated: ArtifactRef, tests: ArtifactRef,
) -> None:
    if not isinstance(log, Phase3ReviewLog):
        raise ValueError("review log must use the declared Phase3ReviewLog schema")
    if log.elaborated_spec != elaborated or log.test_spec != tests:
        raise ValueError("review log must bind the exact current elaborated and test specs")
    if not log.decisions:
        raise ValueError("review log requires at least one decision")
    allowed = {elaborated, tests}
    seen: set[tuple[ArtifactRef, str | None]] = set()
    for entry in log.decisions:
        if entry.artifact not in allowed:
            raise ValueError("review decision targets an artifact outside the exact review inputs")
        if entry.decision in (ApprovalDecision.PENDING, ApprovalDecision.INVALIDATED):
            raise ValueError("review decision must be approve, request-changes, or reject")
        if not isinstance(entry.reviewer, str) or not entry.reviewer.strip():
            raise ValueError("review decision requires a reviewer identity")
        if not _valid_timestamp(entry.timestamp):
            raise ValueError("review decision requires a whole-second UTC timestamp")
        if entry.target is not None and (not isinstance(entry.target, str) or not entry.target.strip()):
            raise ValueError("review target must be absent or non-blank text")
        if entry.comment is not None and (not isinstance(entry.comment, str) or not entry.comment.strip()):
            raise ValueError("review comment must be absent or non-blank text")
        key = (entry.artifact, entry.target)
        if key in seen:
            raise ValueError("review log has duplicate decisions for one artifact target")
        seen.add(key)


def phase3_review_log_to_dict(log: Phase3ReviewLog) -> dict[str, Any]:
    def ref(value: ArtifactRef) -> dict[str, str]:
        return {"artifact_id": value.artifact_id, "content_hash": value.content_hash}
    return {
        "schema": "plain2metta-phase3-review-log/v1",
        "inputs": {"elaborated_spec": ref(log.elaborated_spec), "test_spec": ref(log.test_spec)},
        "decisions": [
            {
                "artifact": ref(item.artifact), "decision": item.decision.value,
                "reviewer": item.reviewer, "timestamp": item.timestamp,
                "target": item.target, "comment": item.comment,
            }
            for item in log.decisions
        ],
    }


def canonical_phase3_review_log(log: Phase3ReviewLog) -> str:
    return json.dumps(phase3_review_log_to_dict(log), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def phase3_review_log_from_dict(payload: Mapping[str, Any]) -> Phase3ReviewLog:
    def exact(value: object, fields: set[str], label: str) -> Mapping[str, Any]:
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError(f"{label} has unknown or missing fields")
        return value
    def ref(value: object, label: str) -> ArtifactRef:
        item = exact(value, {"artifact_id", "content_hash"}, label)
        if any(not isinstance(item[key], str) or not item[key] for key in item):
            raise ValueError(f"{label} fields must be non-blank text")
        return ArtifactRef(item["artifact_id"], item["content_hash"])
    value = exact(payload, {"schema", "inputs", "decisions"}, "review log")
    if value["schema"] != "plain2metta-phase3-review-log/v1":
        raise ValueError("unsupported Phase 3 review-log schema")
    inputs = exact(value["inputs"], {"elaborated_spec", "test_spec"}, "review inputs")
    raw = value["decisions"]
    if not isinstance(raw, list):
        raise ValueError("review decisions must be a list")
    decisions = []
    for item in raw:
        item = exact(item, {"artifact", "decision", "reviewer", "timestamp", "target", "comment"}, "review decision")
        try:
            decision = ApprovalDecision(item["decision"])
        except (TypeError, ValueError) as exc:
            raise ValueError("review decision is not declared") from exc
        decisions.append(Phase3Decision(ref(item["artifact"], "decision artifact"), decision, item["reviewer"], item["timestamp"], item["target"], item["comment"]))
    return Phase3ReviewLog(ref(inputs["elaborated_spec"], "elaborated_spec"), ref(inputs["test_spec"], "test_spec"), tuple(decisions))

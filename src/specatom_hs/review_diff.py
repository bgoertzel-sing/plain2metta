"""Deterministic, content-bound Phase 3 review views.

The report is deliberately read-only.  It exposes exact immutable inputs and
line-oriented review material, but cannot approve or mutate any artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import unified_diff
from typing import Any, Mapping

from .projects import ArtifactKind, ArtifactRef, Project


@dataclass(frozen=True)
class Phase3ReviewDiff:
    original_spec: ArtifactRef
    elaborated_spec: ArtifactRef
    test_spec: ArtifactRef
    original_to_elaborated: tuple[str, ...]
    test_spec_addition: tuple[str, ...]


def _diff(before: str, after: str, before_name: str, after_name: str) -> tuple[str, ...]:
    return tuple(unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=before_name,
        tofile=after_name,
        lineterm="",
    ))


def build_phase3_review_diff(project: Project) -> Phase3ReviewDiff:
    original = project.current(ArtifactKind.ORIGINAL_SPEC)
    elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
    tests = project.current(ArtifactKind.TEST_SPEC)
    if original is None or elaborated is None or tests is None:
        raise ValueError("Phase 3 review requires exact current original, elaborated, and test specs")
    if not any(ref == original.ref for ref in elaborated.upstream):
        raise ValueError("current elaborated spec is not bound to the exact original spec")
    if not any(ref == elaborated.ref for ref in tests.upstream):
        raise ValueError("current test spec is not bound to the exact elaborated spec")
    return Phase3ReviewDiff(
        original.ref,
        elaborated.ref,
        tests.ref,
        _diff(original.content, elaborated.content, "original-spec", "elaborated-spec"),
        _diff("", tests.content, "/dev/null", "test-spec"),
    )


def phase3_review_diff_to_dict(report: Phase3ReviewDiff) -> dict[str, Any]:
    def ref(value: ArtifactRef) -> dict[str, str]:
        return {"artifact_id": value.artifact_id, "content_hash": value.content_hash}
    return {
        "schema": "plain2metta-phase3-review-diff/v1",
        "inputs": {
            "original_spec": ref(report.original_spec),
            "elaborated_spec": ref(report.elaborated_spec),
            "test_spec": ref(report.test_spec),
        },
        "original_to_elaborated": list(report.original_to_elaborated),
        "test_spec_addition": list(report.test_spec_addition),
    }


def phase3_review_diff_from_dict(payload: Mapping[str, Any]) -> Phase3ReviewDiff:
    def exact(value: object, fields: set[str], label: str) -> Mapping[str, Any]:
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError(f"{label} has unknown or missing fields")
        return value

    def ref(value: object, label: str) -> ArtifactRef:
        item = exact(value, {"artifact_id", "content_hash"}, label)
        if any(not isinstance(item[key], str) or not item[key] for key in item):
            raise ValueError(f"{label} fields must be non-blank text")
        return ArtifactRef(item["artifact_id"], item["content_hash"])

    value = exact(payload, {"schema", "inputs", "original_to_elaborated", "test_spec_addition"}, "review diff")
    if value["schema"] != "plain2metta-phase3-review-diff/v1":
        raise ValueError("unsupported Phase 3 review-diff schema")
    inputs = exact(value["inputs"], {"original_spec", "elaborated_spec", "test_spec"}, "review inputs")
    lines = []
    for field in ("original_to_elaborated", "test_spec_addition"):
        raw = value[field]
        if not isinstance(raw, list) or any(not isinstance(line, str) for line in raw):
            raise ValueError(f"{field} must be a list of text lines")
        lines.append(tuple(raw))
    return Phase3ReviewDiff(
        ref(inputs["original_spec"], "original_spec"),
        ref(inputs["elaborated_spec"], "elaborated_spec"),
        ref(inputs["test_spec"], "test_spec"),
        lines[0], lines[1],
    )


def validate_phase3_review_diff(project: Project, report: Phase3ReviewDiff) -> None:
    if report != build_phase3_review_diff(project):
        raise ValueError("Phase 3 review diff does not match exact current artifact versions")

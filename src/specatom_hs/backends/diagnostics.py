"""Diagnostics summaries and reports for SpecAtom-HS documents."""

from __future__ import annotations

from collections import Counter, defaultdict

from ..schema import (
    CheckRecord,
    CheckStatus,
    Role,
    SemanticLevel,
    SpecDocument,
    SpecObject,
    ValidationObligation,
)
from .petta import (
    SUPPORTED_REIFIED_LEVELS,
    admitted_source_span_ids,
    emit_reified_atoms,
    target_object_id,
)


def _status_key(status: object) -> str:
    if status == CheckStatus.PASS and isinstance(status, CheckStatus):
        return "pass"
    if status == CheckStatus.FAIL and isinstance(status, CheckStatus):
        return "fail"
    return "unknown"


def _admitted_checks(doc: SpecDocument) -> list[CheckRecord]:
    """Return checks whose scalar fields are safe and unambiguous for export."""
    emitted_span_ids = admitted_source_span_ids(doc)
    source_manifest_present = bool(doc.files or doc.spans)
    declared_object_ids = {
        obj.id
        for obj in doc.objects
        if isinstance(obj, SpecObject)
        and isinstance(obj.id, str)
        and obj.id.strip()
    }
    emitted_object_ids = {obj.id for obj in _admitted_objects(doc)}
    valid_obligations = [
        obligation
        for obligation in doc.validation_obligations
        if isinstance(obligation, ValidationObligation)
    ]
    obligation_id_counts = Counter(
        obligation.id
        for obligation in valid_obligations
        if isinstance(obligation.id, str) and obligation.id.strip()
    )
    admitted_obligations = {
        obligation.id: obligation
        for obligation in valid_obligations
        if isinstance(obligation.id, str)
        and obligation.id.strip()
        and obligation_id_counts[obligation.id] == 1
        and isinstance(obligation.property, str)
        and obligation.property.strip()
        and isinstance(obligation.target_id, str)
        and obligation.target_id.strip()
        and (
            target_object_id(obligation.target_id, declared_object_ids) is None
            or target_object_id(obligation.target_id, declared_object_ids)
            in emitted_object_ids
        )
        and isinstance(obligation.rationale, str)
        and obligation.rationale.strip()
        and (
            obligation.source_span_id is None
            or obligation.source_span_id == ""
            or (
                isinstance(obligation.source_span_id, str)
                and obligation.source_span_id.strip()
                and (
                    not source_manifest_present
                    or obligation.source_span_id in emitted_span_ids
                )
            )
        )
    }
    valid_checks = [check for check in doc.checks if isinstance(check, CheckRecord)]
    id_counts = Counter(
        check.id
        for check in valid_checks
        if isinstance(check.id, str) and check.id.strip()
    )
    return [
        check
        for check in valid_checks
        if isinstance(check.id, str)
        and check.id.strip()
        and id_counts[check.id] == 1
        and isinstance(check.obligation_id, str)
        and check.obligation_id.strip()
        and check.obligation_id in admitted_obligations
        and isinstance(check.property, str)
        and check.property.strip()
        and isinstance(check.target_id, str)
        and check.target_id.strip()
        and check.property == admitted_obligations[check.obligation_id].property
        and check.target_id == admitted_obligations[check.obligation_id].target_id
        and isinstance(check.status, CheckStatus)
        and isinstance(check.evidence, str)
        and check.evidence.strip()
    ]


def _admitted_objects(doc: SpecDocument) -> list[SpecObject]:
    """Return objects whose identities are safe and unambiguous for export."""
    emitted_span_ids = admitted_source_span_ids(doc)
    source_manifest_present = bool(doc.files or doc.spans)
    valid_objects = [obj for obj in doc.objects if isinstance(obj, SpecObject)]
    id_counts = Counter(
        obj.id for obj in valid_objects if isinstance(obj.id, str) and obj.id.strip()
    )
    return [
        obj
        for obj in valid_objects
        if isinstance(obj.id, str) and obj.id.strip() and id_counts[obj.id] == 1
        and isinstance(obj.role, Role)
        and isinstance(obj.semantic_level, SemanticLevel)
        and obj.semantic_level in SUPPORTED_REIFIED_LEVELS
        and isinstance(obj.facts, list)
        and (
            obj.source_span_id is None
            or obj.source_span_id == ""
            or (
                isinstance(obj.source_span_id, str)
                and obj.source_span_id.strip()
                and (
                    not source_manifest_present
                    or obj.source_span_id in emitted_span_ids
                )
            )
        )
    ]


def diagnostics_summary(doc: SpecDocument) -> dict:
    """Return compact validation/backend diagnostics for a document."""
    _, refusals = emit_reified_atoms(doc)
    by_property: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0, "unknown": 0})
    counts = {"pass": 0, "fail": 0, "unknown": 0}
    valid_checks = _admitted_checks(doc)
    for check in valid_checks:
        key = _status_key(check.status)
        counts[key] += 1
        property_key = (
            check.property
            if isinstance(check.property, str)
            else f"<invalid {type(check.property).__name__}: {check.property!r}>"
        )
        by_property[property_key][key] += 1

    concept_counts = {"defined": 0, "external": 0, "unresolved": 0}
    questions = 0
    requirements = 0
    acceptance_tests = 0
    for obj in _admitted_objects(doc):
        role = obj.role if isinstance(obj.role, Role) else None
        if role == Role.QUESTION_OBJECT:
            questions += 1
        if role == Role.REQUIREMENT_OBJECT:
            requirements += 1
        facts = obj.facts if isinstance(obj.facts, list) else []
        if role == Role.VALIDATION_OBJECT and any(
            isinstance(fact, tuple)
            and len(fact) == 3
            and fact[0] == "TestKind"
            and fact[1] == obj.id
            and fact[2] == "Acceptance"
            for fact in facts
        ):
            acceptance_tests += 1
        for fact in facts:
            if (
                isinstance(fact, tuple)
                and len(fact) == 3
                and fact[0] == "ConceptStatus"
                and fact[1] == obj.id
                and isinstance(fact[2], str)
                and fact[2] in concept_counts
            ):
                concept_counts[fact[2]] += 1

    coverage_checks = [
        check
        for check in valid_checks
        if isinstance(check.property, str)
        and check.property
        in {
            "requirement-has-acceptance-test",
            "acceptance-test-covers-requirement",
            "coverage-claim-target-resolved",
        }
    ]

    return {
        "total_objects": len(doc.objects),
        "total_obligations": len(doc.validation_obligations),
        "total_checks": len(doc.checks),
        "pass": counts["pass"],
        "fail": counts["fail"],
        "unknown": counts["unknown"],
        "refusals": len(refusals),
        "by_property": dict(sorted(by_property.items())),
        "questions": questions,
        "concepts": concept_counts,
        "requirements": requirements,
        "acceptance_tests": acceptance_tests,
        "coverage_pass": sum(1 for check in coverage_checks if _status_key(check.status) == "pass"),
        "coverage_unknown": sum(1 for check in coverage_checks if _status_key(check.status) == "unknown"),
    }


def _markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(str(cell).replace("\n", " ") for cell in row) + " |" for row in rows)
    return "\n".join(lines)


def _question_texts(doc: SpecDocument) -> list[str]:
    texts: list[str] = []
    for obj in _admitted_objects(doc):
        if not isinstance(obj.role, Role) or obj.role != Role.QUESTION_OBJECT:
            continue
        facts = obj.facts if isinstance(obj.facts, list) else []
        text = next(
            (
                fact[2]
                for fact in facts
                if isinstance(fact, tuple)
                and len(fact) == 3
                and fact[0] == "QuestionText"
                and fact[1] == obj.id
                and isinstance(fact[2], str)
                and fact[2].strip()
            ),
            "",
        )
        texts.append(f"- {obj.id}: {text}" if text else f"- {obj.id}")
    return texts


def format_diagnostics_report(doc: SpecDocument) -> str:
    """Return a human-readable Markdown diagnostics report."""
    summary = diagnostics_summary(doc)
    _, refusals = emit_reified_atoms(doc)

    summary_rows = [[key, value] for key, value in summary.items() if key not in {"by_property", "concepts"}]
    summary_rows.append(["concepts.defined", summary["concepts"]["defined"]])
    summary_rows.append(["concepts.external", summary["concepts"]["external"]])
    summary_rows.append(["concepts.unresolved", summary["concepts"]["unresolved"]])

    property_rows = [
        [prop, counts["pass"], counts["fail"], counts["unknown"]]
        for prop, counts in summary["by_property"].items()
    ] or [["(none)", 0, 0, 0]]

    valid_checks = _admitted_checks(doc)
    fail_lines = [f"- {c.id} `{c.property}` target `{c.target_id}`: {c.evidence}" for c in valid_checks if _status_key(c.status) == "fail"] or ["- (none)"]
    unknown_lines = [f"- {c.id} `{c.property}` target `{c.target_id}`: {c.evidence}" for c in valid_checks if _status_key(c.status) == "unknown"] or ["- (none)"]
    question_lines = _question_texts(doc) or ["- (none)"]
    refusal_lines = [f"- {r.reason} {r.object_id or ''}".rstrip() for r in refusals] or ["- (none)"]

    return "\n\n".join(
        [
            "# SpecAtom-HS Diagnostics Report",
            "## Summary Counts\n" + _markdown_table(["Metric", "Value"], summary_rows),
            "## Per-property Breakdown\n" + _markdown_table(["Property", "Pass", "Fail", "Unknown"], property_rows),
            "## FAIL Checks\n" + "\n".join(fail_lines),
            "## UNKNOWN Checks\n" + "\n".join(unknown_lines),
            "## Questions\n" + "\n".join(question_lines),
            "## Backend Refusals\n" + "\n".join(refusal_lines),
        ]
    )

"""Diagnostics summaries and reports for SpecAtom-HS documents."""

from __future__ import annotations

from collections import defaultdict

from ..schema import CheckRecord, CheckStatus, Role, SpecDocument, SpecObject
from .petta import emit_reified_atoms


def _status_key(status: object) -> str:
    value = status.value if hasattr(status, "value") else str(status)
    lowered = value.lower()
    if lowered == "pass":
        return "pass"
    if lowered == "fail":
        return "fail"
    return "unknown"


def diagnostics_summary(doc: SpecDocument) -> dict:
    """Return compact validation/backend diagnostics for a document."""
    _, refusals = emit_reified_atoms(doc)
    by_property: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0, "unknown": 0})
    counts = {"pass": 0, "fail": 0, "unknown": 0}
    valid_checks = [check for check in doc.checks if isinstance(check, CheckRecord)]
    for check in valid_checks:
        key = _status_key(check.status)
        counts[key] += 1
        by_property[check.property][key] += 1

    concept_counts = {"defined": 0, "external": 0, "unresolved": 0}
    questions = 0
    requirements = 0
    acceptance_tests = 0
    for obj in doc.objects:
        if not isinstance(obj, SpecObject):
            continue
        if obj.role == Role.QUESTION_OBJECT:
            questions += 1
        if obj.role == Role.REQUIREMENT_OBJECT:
            requirements += 1
        facts = obj.facts if isinstance(obj.facts, list) else []
        if obj.role == Role.VALIDATION_OBJECT and any(
            isinstance(fact, tuple)
            and len(fact) >= 3
            and fact[0] == "TestKind"
            and fact[2] == "Acceptance"
            for fact in facts
        ):
            acceptance_tests += 1
        for fact in facts:
            if (
                isinstance(fact, tuple)
                and len(fact) >= 3
                and fact[0] == "ConceptStatus"
                and fact[2] in concept_counts
            ):
                concept_counts[str(fact[2])] += 1

    coverage_checks = [check for check in valid_checks if check.property in {"requirement-has-acceptance-test", "acceptance-test-covers-requirement", "coverage-claim-target-resolved"}]

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
    for obj in doc.objects:
        if not isinstance(obj, SpecObject):
            continue
        if obj.role != Role.QUESTION_OBJECT:
            continue
        facts = obj.facts if isinstance(obj.facts, list) else []
        text = next(
            (
                str(fact[2])
                for fact in facts
                if isinstance(fact, tuple)
                and len(fact) >= 3
                and fact[0] == "QuestionText"
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

    valid_checks = [check for check in doc.checks if isinstance(check, CheckRecord)]
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

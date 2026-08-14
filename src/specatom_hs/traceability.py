"""Canonical Phase 7 traceability reports for persisted v2 artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from .compiler_output import CompilerOutputBundle
from .sandbox_protocol import SandboxTestResult


@dataclass(frozen=True)
class ProvenanceLink:
    phase: str
    artifact_id: str
    content_hash: str


@dataclass(frozen=True)
class TraceabilityEntry:
    spec_id: str
    code_locations: tuple[str, ...]
    planned_test_ids: tuple[str, ...]
    result_test_ids: tuple[str, ...]
    status: str
    failure_details: tuple[str, ...] = ()


@dataclass(frozen=True)
class TraceabilityReport:
    provenance: tuple[ProvenanceLink, ...]
    entries: tuple[TraceabilityEntry, ...]


def build_traceability_report(
    provenance: tuple[ProvenanceLink, ...],
    bundle: CompilerOutputBundle,
    result: SandboxTestResult,
) -> TraceabilityReport:
    """Join exact compiler traceability to exact sandbox results."""
    validate_provenance(provenance)
    spec_ids = sorted({value for item in bundle.files for value in item.spec_ids})
    planned_test_ids = {value for item in bundle.files for value in item.test_ids}
    result_test_ids = {test.test_id for test in result.tests}
    covered_spec_ids = {value for test in result.tests for value in test.covered_spec_ids}
    if result_test_ids - planned_test_ids:
        raise ValueError("traceability results contain test IDs absent from compiler output")
    if covered_spec_ids - set(spec_ids):
        raise ValueError("traceability results contain spec IDs absent from compiler output")
    entries = []
    for spec_id in spec_ids:
        files = tuple(sorted(item.path for item in bundle.files if spec_id in item.spec_ids))
        planned = tuple(sorted({test_id for item in bundle.files if spec_id in item.spec_ids for test_id in item.test_ids}))
        matching = tuple(test for test in result.tests if spec_id in test.covered_spec_ids)
        result_ids = tuple(sorted(test.test_id for test in matching))
        failures = tuple(
            f"{test.test_id}: {test.assertion or test.stderr or test.stdout or test.status}"
            for test in matching if test.status in {"failed", "error"}
        )
        if failures:
            status = "failing"
        elif any(test.status == "passed" for test in matching):
            status = "passing"
        elif matching and all(test.status == "skipped" for test in matching):
            status = "skipped"
        else:
            status = "untested"
        entries.append(TraceabilityEntry(spec_id, files, planned, result_ids, status, failures))
    report = TraceabilityReport(provenance, tuple(entries))
    validate_traceability_report(report)
    return report


def validate_provenance(provenance: tuple[ProvenanceLink, ...]) -> None:
    expected = (
        "original-spec", "elaborated-spec", "test-spec",
        "reviewed-elaborated-spec", "reviewed-test-spec", "logical-ir",
        "compiler-output", "sandbox-handoff", "test-result",
    )
    if tuple(link.phase for link in provenance) != expected:
        raise ValueError("traceability provenance chain is incomplete or out of order")
    for link in provenance:
        if not isinstance(link.artifact_id, str) or not link.artifact_id.strip():
            raise ValueError("traceability provenance artifact ID is invalid")
        if (
            not isinstance(link.content_hash, str) or not link.content_hash.startswith("sha256:")
            or len(link.content_hash) != 71
            or any(value not in "0123456789abcdef" for value in link.content_hash[7:])
        ):
            raise ValueError("traceability provenance content hash is invalid")


def validate_traceability_report(report: TraceabilityReport) -> None:
    if not isinstance(report, TraceabilityReport):
        raise ValueError("traceability report must be a TraceabilityReport")
    validate_provenance(report.provenance)
    if not report.entries:
        raise ValueError("traceability report requires at least one spec entry")
    if tuple(entry.spec_id for entry in report.entries) != tuple(sorted(entry.spec_id for entry in report.entries)):
        raise ValueError("traceability entries must be uniquely sorted by spec ID")
    if len({entry.spec_id for entry in report.entries}) != len(report.entries):
        raise ValueError("traceability report contains duplicate spec IDs")
    for entry in report.entries:
        if not isinstance(entry.spec_id, str) or not entry.spec_id.strip() or not entry.code_locations:
            raise ValueError("traceability entry requires a spec ID and code location")
        for values in (entry.code_locations, entry.planned_test_ids, entry.result_test_ids, entry.failure_details):
            if len(set(values)) != len(values) or any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError("traceability entry lists must contain unique non-blank text")
        if entry.status not in {"passing", "failing", "skipped", "untested"}:
            raise ValueError("traceability entry status is unsupported")
        if (entry.status == "failing") != bool(entry.failure_details):
            raise ValueError("traceability failure details do not match status")


def traceability_report_to_dict(report: TraceabilityReport) -> dict[str, Any]:
    validate_traceability_report(report)
    counts = {status: sum(entry.status == status for entry in report.entries) for status in ("passing", "failing", "skipped", "untested")}
    return {
        "schema_version": 1,
        "kind": "traceability-report",
        "summary": {**counts, "total": len(report.entries)},
        "provenance": [
            {"phase": link.phase, "artifact_id": link.artifact_id, "content_hash": link.content_hash}
            for link in report.provenance
        ],
        "entries": [
            {
                "spec_id": entry.spec_id,
                "code_locations": list(entry.code_locations),
                "planned_test_ids": list(entry.planned_test_ids),
                "result_test_ids": list(entry.result_test_ids),
                "status": entry.status,
                "failure_details": list(entry.failure_details),
            }
            for entry in report.entries
        ],
    }


def canonical_traceability_report(report: TraceabilityReport) -> str:
    return json.dumps(traceability_report_to_dict(report), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def traceability_report_from_dict(payload: Mapping[str, Any]) -> TraceabilityReport:
    if not isinstance(payload, Mapping) or set(payload) != {"schema_version", "kind", "summary", "provenance", "entries"}:
        raise ValueError("malformed traceability report envelope")
    if payload["schema_version"] != 1 or payload["kind"] != "traceability-report":
        raise ValueError("unsupported traceability report")
    if not isinstance(payload["provenance"], list) or not isinstance(payload["entries"], list):
        raise ValueError("traceability provenance and entries must be lists")
    if not isinstance(payload["summary"], Mapping) or set(payload["summary"]) != {"passing", "failing", "skipped", "untested", "total"}:
        raise ValueError("malformed traceability report summary")
    list_fields = ("code_locations", "planned_test_ids", "result_test_ids", "failure_details")
    if any(
        not isinstance(item, Mapping) or any(not isinstance(item.get(field), list) for field in list_fields)
        for item in payload["entries"]
    ):
        raise ValueError("traceability entry lists must be lists")
    try:
        provenance = tuple(ProvenanceLink(item["phase"], item["artifact_id"], item["content_hash"]) for item in payload["provenance"] if isinstance(item, Mapping) and set(item) == {"phase", "artifact_id", "content_hash"})
        entries = tuple(TraceabilityEntry(item["spec_id"], tuple(item["code_locations"]), tuple(item["planned_test_ids"]), tuple(item["result_test_ids"]), item["status"], tuple(item["failure_details"])) for item in payload["entries"] if isinstance(item, Mapping) and set(item) == {"spec_id", "code_locations", "planned_test_ids", "result_test_ids", "status", "failure_details"})
    except (KeyError, TypeError) as exc:
        raise ValueError(f"malformed traceability report: {exc}") from exc
    if len(provenance) != len(payload["provenance"]) or len(entries) != len(payload["entries"]):
        raise ValueError("malformed traceability report record")
    report = TraceabilityReport(provenance, entries)
    validate_traceability_report(report)
    expected_summary = traceability_report_to_dict(report)["summary"]
    if payload["summary"] != expected_summary:
        raise ValueError("traceability report summary is forged")
    return report

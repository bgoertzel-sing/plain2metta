"""Strict, non-executable Plain2MeTTa v2 logical-IR and review schemas."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Any, Mapping


_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}\Z")


class FindingSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class FindingCategory(str, Enum):
    MISSING_DEFINITION = "missing-definition"
    INCONSISTENT_TYPE = "inconsistent-type"
    CONTRADICTORY_INVARIANT = "contradictory-invariant"
    UNCOVERED_REQUIREMENT = "uncovered-requirement"
    INVALID_ORDERING_DATA_FLOW = "invalid-ordering-data-flow"
    POSSIBLE_LEAKAGE = "possible-leakage"
    UNREACHABLE_OBLIGATION = "unreachable-obligation"
    UNMARKED_OPERATIONAL_GAP = "unmarked-operational-gap"


class FindingDisposition(str, Enum):
    OPEN = "open"
    REPAIRED = "repaired"
    WAIVED = "waived"
    DEFERRED = "deferred"


@dataclass(frozen=True)
class TypeDeclaration:
    declaration_id: str
    name: str
    source_clause_ids: tuple[str, ...]


@dataclass(frozen=True)
class Contract:
    contract_id: str
    name: str
    inputs: tuple[str, ...]
    output: str
    preconditions: tuple[str, ...]
    postconditions: tuple[str, ...]
    invariants: tuple[str, ...]
    source_clause_ids: tuple[str, ...]
    requires_grounding: bool = False


@dataclass(frozen=True)
class RequirementObligation:
    requirement_id: str
    planned_test_ids: tuple[str, ...]
    source_clause_ids: tuple[str, ...]


@dataclass(frozen=True)
class DependencyDeclaration:
    dependency_id: str
    before: str
    after: str
    relation: str
    source_clause_ids: tuple[str, ...]


@dataclass(frozen=True)
class OperationalHole:
    hole_id: str
    contract_id: str
    expected_type: str
    rationale: str
    source_clause_ids: tuple[str, ...]


@dataclass(frozen=True)
class LogicalIRDocument:
    module_id: str
    types: tuple[TypeDeclaration, ...]
    contracts: tuple[Contract, ...]
    obligations: tuple[RequirementObligation, ...]
    dependencies: tuple[DependencyDeclaration, ...]
    operational_holes: tuple[OperationalHole, ...]


@dataclass(frozen=True)
class LogicalReviewFinding:
    finding_id: str
    category: FindingCategory
    severity: FindingSeverity
    message: str
    source_clause_ids: tuple[str, ...]
    disposition: FindingDisposition = FindingDisposition.OPEN
    reviewer: str | None = None
    rationale: str | None = None


@dataclass(frozen=True)
class LogicalReviewReport:
    logical_ir_hash: str
    findings: tuple[LogicalReviewFinding, ...]

    @property
    def blocks_compilation(self) -> bool:
        return any(
            finding.severity is FindingSeverity.CRITICAL
            and finding.disposition in (FindingDisposition.OPEN, FindingDisposition.DEFERRED)
            for finding in self.findings
        )


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-blank text")
    return value


def _identifier(value: object, label: str) -> str:
    value = _text(value, label)
    if _ID.fullmatch(value) is None:
        raise ValueError(f"{label} is not a canonical identifier")
    return value


def _source_ids(values: tuple[str, ...], label: str) -> None:
    if not values:
        raise ValueError(f"{label} requires source-clause provenance")
    for value in values:
        _identifier(value, f"{label} source clause")


def validate_logical_ir(document: LogicalIRDocument) -> None:
    """Validate only declarative structures; this schema has no executable body field."""
    _identifier(document.module_id, "module_id")
    ids: list[str] = []
    type_names: set[str] = set()
    for declaration in document.types:
        ids.append(_identifier(declaration.declaration_id, "declaration_id"))
        type_names.add(_identifier(declaration.name, "type name"))
        _source_ids(declaration.source_clause_ids, declaration.declaration_id)
    contract_ids: set[str] = set()
    for contract in document.contracts:
        ids.append(_identifier(contract.contract_id, "contract_id"))
        contract_ids.add(contract.contract_id)
        _identifier(contract.name, "contract name")
        for value in contract.inputs + (contract.output,):
            _identifier(value, "contract type")
        for value in contract.preconditions + contract.postconditions + contract.invariants:
            _text(value, "contract condition")
        _source_ids(contract.source_clause_ids, contract.contract_id)
    for obligation in document.obligations:
        ids.append(_identifier(obligation.requirement_id, "requirement_id"))
        for test_id in obligation.planned_test_ids:
            _identifier(test_id, "planned_test_id")
        _source_ids(obligation.source_clause_ids, obligation.requirement_id)
    for dependency in document.dependencies:
        ids.append(_identifier(dependency.dependency_id, "dependency_id"))
        _identifier(dependency.before, "dependency before")
        _identifier(dependency.after, "dependency after")
        _identifier(dependency.relation, "dependency relation")
        _source_ids(dependency.source_clause_ids, dependency.dependency_id)
    for hole in document.operational_holes:
        ids.append(_identifier(hole.hole_id, "hole_id"))
        if hole.contract_id not in contract_ids:
            raise ValueError(f"operational hole {hole.hole_id!r} cites an unknown contract")
        _identifier(hole.expected_type, "hole expected_type")
        _text(hole.rationale, "hole rationale")
        _source_ids(hole.source_clause_ids, hole.hole_id)
    if len(ids) != len(set(ids)):
        raise ValueError("logical IR identifiers must be globally unique")
    if len(type_names) != len(document.types):
        raise ValueError("logical IR type names must be unique")
    # A missing hole is structurally representable so the review report can retain
    # it as a critical finding; compilation remains blocked until disposition.


def logical_ir_to_dict(document: LogicalIRDocument) -> dict[str, Any]:
    validate_logical_ir(document)
    def source(values: tuple[str, ...]) -> list[str]:
        return list(values)
    return {
        "schema_version": 1,
        "artifact_type": "literate-logical-ir-verification-skeleton",
        "executable": False,
        "module_id": document.module_id,
        "types": [{"declaration_id": x.declaration_id, "name": x.name, "source_clause_ids": source(x.source_clause_ids)} for x in document.types],
        "contracts": [{"contract_id": x.contract_id, "name": x.name, "inputs": list(x.inputs), "output": x.output, "preconditions": list(x.preconditions), "postconditions": list(x.postconditions), "invariants": list(x.invariants), "source_clause_ids": source(x.source_clause_ids), "requires_grounding": x.requires_grounding} for x in document.contracts],
        "obligations": [{"requirement_id": x.requirement_id, "planned_test_ids": list(x.planned_test_ids), "source_clause_ids": source(x.source_clause_ids)} for x in document.obligations],
        "dependencies": [{"dependency_id": x.dependency_id, "before": x.before, "after": x.after, "relation": x.relation, "source_clause_ids": source(x.source_clause_ids)} for x in document.dependencies],
        "operational_holes": [{"hole_id": x.hole_id, "contract_id": x.contract_id, "expected_type": x.expected_type, "rationale": x.rationale, "source_clause_ids": source(x.source_clause_ids)} for x in document.operational_holes],
    }


def logical_ir_from_dict(payload: Mapping[str, Any]) -> LogicalIRDocument:
    """Strictly deserialize the schema, rejecting executable or additional fields."""
    expected = {"schema_version", "artifact_type", "executable", "module_id", "types", "contracts", "obligations", "dependencies", "operational_holes"}
    try:
        if set(payload) != expected or payload["schema_version"] != 1 or payload["artifact_type"] != "literate-logical-ir-verification-skeleton" or payload["executable"] is not False:
            raise ValueError("invalid logical IR envelope")
        shapes = (
            (payload["types"], {"declaration_id", "name", "source_clause_ids"}),
            (payload["contracts"], {"contract_id", "name", "inputs", "output", "preconditions", "postconditions", "invariants", "source_clause_ids", "requires_grounding"}),
            (payload["obligations"], {"requirement_id", "planned_test_ids", "source_clause_ids"}),
            (payload["dependencies"], {"dependency_id", "before", "after", "relation", "source_clause_ids"}),
            (payload["operational_holes"], {"hole_id", "contract_id", "expected_type", "rationale", "source_clause_ids"}),
        )
        if any(not isinstance(items, list) or any(not isinstance(item, Mapping) or set(item) != fields for item in items) for items, fields in shapes):
            raise ValueError("invalid logical IR record fields")
        if any(type(item["requires_grounding"]) is not bool for item in payload["contracts"]):
            raise ValueError("requires_grounding must be boolean")
        document = LogicalIRDocument(
            payload["module_id"],
            tuple(TypeDeclaration(x["declaration_id"], x["name"], tuple(x["source_clause_ids"])) for x in payload["types"]),
            tuple(Contract(x["contract_id"], x["name"], tuple(x["inputs"]), x["output"], tuple(x["preconditions"]), tuple(x["postconditions"]), tuple(x["invariants"]), tuple(x["source_clause_ids"]), x["requires_grounding"]) for x in payload["contracts"]),
            tuple(RequirementObligation(x["requirement_id"], tuple(x["planned_test_ids"]), tuple(x["source_clause_ids"])) for x in payload["obligations"]),
            tuple(DependencyDeclaration(x["dependency_id"], x["before"], x["after"], x["relation"], tuple(x["source_clause_ids"])) for x in payload["dependencies"]),
            tuple(OperationalHole(x["hole_id"], x["contract_id"], x["expected_type"], x["rationale"], tuple(x["source_clause_ids"])) for x in payload["operational_holes"]),
        )
        validate_logical_ir(document)
        return document
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed logical IR: {exc}") from exc


def canonical_logical_ir(document: LogicalIRDocument) -> str:
    return json.dumps(logical_ir_to_dict(document), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def logical_ir_hash(document: LogicalIRDocument) -> str:
    return "sha256:" + sha256(canonical_logical_ir(document).encode("utf-8")).hexdigest()


def review_logical_ir(document: LogicalIRDocument) -> LogicalReviewReport:
    """Produce deterministic structural critical findings without claiming execution."""
    validate_logical_ir(document)
    declared = {item.name for item in document.types}
    holes = {item.contract_id for item in document.operational_holes}
    findings: list[LogicalReviewFinding] = []
    def add(category: FindingCategory, subject: str, message: str, source_ids: tuple[str, ...]) -> None:
        digest = sha256(f"{category.value}\0{subject}\0{message}".encode()).hexdigest()[:16]
        findings.append(LogicalReviewFinding(f"finding-{digest}", category, FindingSeverity.CRITICAL, message, source_ids))
    for contract in document.contracts:
        for name in contract.inputs + (contract.output,):
            if name not in declared:
                add(FindingCategory.MISSING_DEFINITION, f"{contract.contract_id}:{name}", f"contract {contract.contract_id} references undefined type {name}", contract.source_clause_ids)
        if contract.requires_grounding and contract.contract_id not in holes:
            add(FindingCategory.UNMARKED_OPERATIONAL_GAP, contract.contract_id, f"grounded contract {contract.contract_id} lacks an OperationalHole", contract.source_clause_ids)
    for obligation in document.obligations:
        if not obligation.planned_test_ids:
            add(FindingCategory.UNCOVERED_REQUIREMENT, obligation.requirement_id, f"requirement {obligation.requirement_id} has no planned test", obligation.source_clause_ids)
    return LogicalReviewReport(logical_ir_hash(document), tuple(findings))


def decide_finding(report: LogicalReviewReport, finding_id: str, disposition: FindingDisposition, reviewer: str, rationale: str) -> LogicalReviewReport:
    if not isinstance(disposition, FindingDisposition):
        raise ValueError("invalid logical review disposition")
    if disposition is FindingDisposition.OPEN:
        raise ValueError("review decisions must repair, waive, or defer a finding")
    _text(reviewer, "reviewer")
    _text(rationale, "rationale")
    found = False
    findings = []
    for finding in report.findings:
        if finding.finding_id == finding_id:
            found = True
            findings.append(replace(finding, disposition=disposition, reviewer=reviewer, rationale=rationale))
        else:
            findings.append(finding)
    if not found:
        raise ValueError("unknown logical review finding")
    return replace(report, findings=tuple(findings))


def validate_review_for_document(report: LogicalReviewReport, document: LogicalIRDocument) -> None:
    """Require a review to be exactly the deterministic report plus decisions.

    This prevents a serialized project from dropping, adding, or rewriting a
    finding while retaining a superficially valid logical-IR hash.
    """
    expected = review_logical_ir(document)
    if report.logical_ir_hash != expected.logical_ir_hash:
        raise ValueError("logical review hash does not match logical IR")
    if len(report.findings) != len(expected.findings):
        raise ValueError("logical review findings do not match logical IR")
    expected_by_id = {finding.finding_id: finding for finding in expected.findings}
    for finding in report.findings:
        baseline = expected_by_id.get(finding.finding_id)
        if baseline is None or (
            finding.category,
            finding.severity,
            finding.message,
            finding.source_clause_ids,
        ) != (
            baseline.category,
            baseline.severity,
            baseline.message,
            baseline.source_clause_ids,
        ):
            raise ValueError("logical review findings do not match logical IR")


def logical_review_to_dict(report: LogicalReviewReport) -> dict[str, Any]:
    return {"schema_version": 1, "logical_ir_hash": report.logical_ir_hash, "blocks_compilation": report.blocks_compilation, "findings": [{"finding_id": x.finding_id, "category": x.category.value, "severity": x.severity.value, "message": x.message, "source_clause_ids": list(x.source_clause_ids), "disposition": x.disposition.value, "reviewer": x.reviewer, "rationale": x.rationale} for x in report.findings]}


def logical_review_from_dict(payload: Mapping[str, Any]) -> LogicalReviewReport:
    """Deserialize decisions and recompute the derived compilation-blocking flag."""
    try:
        if set(payload) != {"schema_version", "logical_ir_hash", "blocks_compilation", "findings"} or payload["schema_version"] != 1:
            raise ValueError("invalid logical review envelope")
        finding_fields = {"finding_id", "category", "severity", "message", "source_clause_ids", "disposition", "reviewer", "rationale"}
        if not isinstance(payload["findings"], list) or any(not isinstance(item, Mapping) or set(item) != finding_fields for item in payload["findings"]):
            raise ValueError("invalid logical review finding fields")
        findings = tuple(
            LogicalReviewFinding(
                item["finding_id"], FindingCategory(item["category"]), FindingSeverity(item["severity"]),
                item["message"], tuple(item["source_clause_ids"]), FindingDisposition(item["disposition"]),
                item.get("reviewer"), item.get("rationale"),
            )
            for item in payload["findings"]
        )
        report = LogicalReviewReport(payload["logical_ir_hash"], findings)
        if payload["blocks_compilation"] is not report.blocks_compilation:
            raise ValueError("forged blocks_compilation value")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", report.logical_ir_hash):
            raise ValueError("invalid logical_ir_hash")
        ids = set()
        for finding in findings:
            _identifier(finding.finding_id, "finding_id")
            _text(finding.message, "finding message")
            _source_ids(finding.source_clause_ids, finding.finding_id)
            if finding.finding_id in ids:
                raise ValueError("duplicate finding_id")
            ids.add(finding.finding_id)
            decided = finding.disposition is not FindingDisposition.OPEN
            if decided != bool(isinstance(finding.reviewer, str) and finding.reviewer.strip() and isinstance(finding.rationale, str) and finding.rationale.strip()):
                raise ValueError("finding decisions require reviewer and rationale; open findings prohibit them")
        return report
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed logical review: {exc}") from exc

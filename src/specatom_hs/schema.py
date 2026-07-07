"""Core SpecAtom-HS MVP schema.

The schema is intentionally tiny. It models source-preserving objects and
first-class validation records without claiming deep semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from typing import Iterable


class SemanticLevel(str, Enum):
    """Conservative semantic-level gates used by validators/backends."""

    RAW_TEXT_ONLY = "RawTextOnly"
    TEMPLATE_PARSED = "TemplateParsed"
    ACTION_SCHEMA_PARSED = "ActionSchemaParsed"
    PREDICATE_PARSED = "PredicateParsed"
    FORMALLY_TYPED = "FormallyTyped"
    BACKEND_LOWERED = "BackendLowered"
    EXECUTED = "Executed"
    VERIFIED = "Verified"
    REJECTED = "Rejected"


class Role(str, Enum):
    SOURCE_OBJECT = "SourceObject"
    CONCEPT_OBJECT = "ConceptObject"
    CONCEPT_REFERENCE_OBJECT = "ConceptReferenceObject"
    PROPOSITION_OBJECT = "PropositionObject"
    ACTION_TEMPLATE = "ActionTemplate"
    REQUIREMENT_OBJECT = "RequirementObject"
    OBLIGATION_OBJECT = "ObligationObject"
    VALIDATION_OBJECT = "ValidationObject"
    BACKEND_ARTIFACT = "BackendArtifact"
    QUESTION_OBJECT = "QuestionObject"


class CheckStatus(str, Enum):
    PASS = "Pass"
    FAIL = "Fail"
    UNKNOWN = "Unknown"


@dataclass(frozen=True)
class SourceSpan:
    id: str
    file_id: str
    start_byte: int
    end_byte: int
    start_line: int
    end_line: int


@dataclass(frozen=True)
class PlainFile:
    id: str
    path: str
    digest: str
    text: str


@dataclass(frozen=True)
class Section:
    id: str
    file_id: str
    title: str
    kind: str
    ordinal: int
    span: SourceSpan


@dataclass(frozen=True)
class PlainItem:
    id: str
    file_id: str
    section_id: str
    parent_item_id: str | None
    ordinal: int
    level: int
    raw_text: str
    span: SourceSpan


@dataclass
class SpecObject:
    id: str
    role: Role
    semantic_level: SemanticLevel
    source_span_id: str | None = None
    facts: list[tuple] = field(default_factory=list)


@dataclass(frozen=True)
class ValidationObligation:
    id: str
    property: str
    target_id: str
    rationale: str
    source_span_id: str | None = None


@dataclass(frozen=True)
class CheckRecord:
    id: str
    obligation_id: str
    property: str
    target_id: str
    status: CheckStatus
    evidence: str


@dataclass
class SpecDocument:
    files: list[PlainFile] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    items: list[PlainItem] = field(default_factory=list)
    spans: list[SourceSpan] = field(default_factory=list)
    objects: list[SpecObject] = field(default_factory=list)
    validation_obligations: list[ValidationObligation] = field(default_factory=list)
    checks: list[CheckRecord] = field(default_factory=list)
    # O(1) deduplication sets (kept in sync with the lists above)
    _obligation_ids: set[str] = field(default_factory=set, repr=False, compare=False)
    _check_ids: set[str] = field(default_factory=set, repr=False, compare=False)

    def facts(self) -> list[tuple]:
        """Return a compact reified fact view for tests and backends."""
        facts: list[tuple] = []
        for f in self.files:
            facts.append(("PlainFile", f.id, f.path, f.digest))
        for s in self.sections:
            facts.append(("Section", s.id, s.file_id, s.kind, s.ordinal))
            facts.append(("DerivedFrom", s.id, s.span.id))
        for item in self.items:
            facts.append(("PlainItem", item.id, item.section_id, item.parent_item_id or "none", item.ordinal, item.raw_text))
            facts.append(("DerivedFrom", item.id, item.span.id))
        for sp in self.spans:
            facts.append(("SourceSpan", sp.id, sp.file_id, sp.start_byte, sp.end_byte, sp.start_line, sp.end_line))
        for obj in self.objects:
            facts.extend([
                ("SpecObject", obj.id),
                ("PrimaryRole", obj.id, obj.role.value),
                ("SemanticLevel", obj.id, obj.semantic_level.value),
            ])
            if obj.source_span_id:
                facts.append(("DerivedFrom", obj.id, obj.source_span_id))
            facts.extend(obj.facts)
        for obl in self.validation_obligations:
            facts.append(("ValidationObligation", obl.id, obl.property, obl.target_id, obl.rationale))
            if obl.source_span_id:
                facts.append(("DerivedFrom", obl.id, obl.source_span_id))
        for check in self.checks:
            facts.extend([
                ("Check", check.id),
                ("CheckTargets", check.id, check.target_id),
                ("CheckProperty", check.id, check.property),
                ("CheckStatus", check.id, check.status.value),
                ("CheckEvidence", check.id, check.evidence),
            ])
        return facts


def stable_id(prefix: str, *parts: object, length: int = 10) -> str:
    h = sha256()
    for part in parts:
        h.update(str(part).encode("utf-8"))
        h.update(b"\0")
    return f"{prefix}-{h.hexdigest()[:length]}"


def one(items: Iterable[object]) -> object:
    seq = list(items)
    if len(seq) != 1:
        raise ValueError(f"expected exactly one item, got {len(seq)}")
    return seq[0]

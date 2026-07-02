"""Ordered pass registry for the local scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable

from .schema import CheckStatus, Role, SemanticLevel, SourceSpan, SpecDocument, SpecObject, stable_id
from .source_indexer import index_path, index_source
from .validators import add_check, add_validation_obligation, validate_document


PassFn = Callable[[SpecDocument], SpecDocument]


@dataclass(frozen=True)
class PassSpec:
    name: str
    description: str
    run: PassFn


def seed_raw_item_objects(doc: SpecDocument) -> SpecDocument:
    """Create RawTextOnly SpecObjects for indexed items, without semantic claims."""
    existing = {obj.id for obj in doc.objects}
    for item in doc.items:
        oid = stable_id("obj", item.id)
        if oid in existing:
            continue
        doc.objects.append(
            SpecObject(
                oid,
                Role.SOURCE_OBJECT,
                SemanticLevel.RAW_TEXT_ONLY,
                item.span.id,
                facts=[("RawText", oid, item.raw_text), ("SourceItem", oid, item.id)],
            )
        )
    return doc


CONCEPT_DEF_RE = re.compile(r"^:([^:\[\]\n]+):")
CONCEPT_REF_RE = re.compile(r":([^:\[\]\n]+):")
CONCEPT_ALIAS_RE = re.compile(r"\[(?P<kind>concept|def|ref):(?P<name>[^\]]+)\]", re.IGNORECASE)
BARE_DEFINITION_RE = re.compile(r"^(?:concept\s+|define\s+)?(?P<name>[A-Z][A-Za-z0-9_ -]{1,63}):(?:\s|$)")
EXTERNAL_REF_RE = re.compile(r"\[external:([^\]]+)\]|\bexternal:([A-Za-z0-9_.-]+)")
DEFINITION_SECTION_KINDS = {"Definitions", "Concepts", "Glossary"}


def _clean_concept_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def build_concept_table(doc: SpecDocument) -> SpecDocument:
    """Extract a conservative concept table from explicit Plain markers.

    The pass only trusts lightweight syntax: ``:Concept:`` definitions/references,
    conservative aliases, definition/glossary bullets, and external markers.
    Unresolved references become question objects plus Unknown validation checks
    instead of invented meaning.
    """
    definitions: dict[str, str] = {}
    references: dict[str, set[str]] = {}
    externals: dict[str, set[str]] = {}
    occurrences: list[tuple[str, str, str, str, str]] = []
    span_ids = {span.id for span in doc.spans}

    file_text = {plain_file.id: plain_file.text for plain_file in doc.files}
    section_kind_by_id = {section.id: section.kind for section in doc.sections}

    def raw_index_to_source_offset(item, raw_index: int) -> int:
        """Map an index in ``item.raw_text`` back into the source span.

        The item span includes bullet markers and continuation indentation, while
        ``raw_text`` stores only the bullet body with continuation lines stripped.
        This small alignment routine keeps occurrence spans exact without
        assuming a fixed bullet-prefix length.
        """
        segment = file_text[item.file_id][item.span.start_byte:item.span.end_byte]
        cursor = 0
        at_line_start = True
        for offset, ch in enumerate(segment):
            if cursor == raw_index:
                return item.span.start_byte + offset
            if at_line_start:
                if ch.isspace() and ch != "\n":
                    continue
                if ch == "-":
                    continue
                if ch == " ":
                    continue
                at_line_start = False
            if cursor < len(item.raw_text) and ch == item.raw_text[cursor]:
                cursor += 1
            if ch == "\n":
                at_line_start = True
        if cursor == raw_index:
            return item.span.end_byte
        raise ValueError(f"could not align raw index {raw_index} for item {item.id}")

    def line_for_offset(file_id: str, byte_offset: int) -> int:
        """Return a 1-based line number for a byte offset in the source text."""
        return file_text[file_id].count("\n", 0, byte_offset) + 1

    def add_occurrence(item, name: str, kind: str, match_start: int, match_end: int) -> str:
        """Preserve an exact source span for one explicit concept marker."""
        start = raw_index_to_source_offset(item, match_start)
        end = raw_index_to_source_offset(item, match_end)
        span_id = stable_id("span", item.file_id, start, end)
        if span_id not in span_ids:
            doc.spans.append(
                SourceSpan(
                    span_id,
                    item.file_id,
                    start,
                    end,
                    line_for_offset(item.file_id, start),
                    line_for_offset(item.file_id, max(start, end - 1)),
                )
            )
            span_ids.add(span_id)
        return span_id

    for item in doc.items:
        raw = item.raw_text
        definition_span: tuple[int, int] | None = None
        if match := CONCEPT_DEF_RE.search(raw):
            name = _clean_concept_name(match.group(1))
            span_id = add_occurrence(item, name, "definition", match.start(), match.end())
            definitions.setdefault(name, span_id)
            occurrences.append((name, "definition", span_id, item.id, f"{match.start()}:{match.end()}"))
            definition_span = (match.start(), match.end())
        for match in CONCEPT_REF_RE.finditer(raw):
            name = _clean_concept_name(match.group(1))
            span_id = add_occurrence(item, name, "reference", match.start(), match.end())
            references.setdefault(name, set()).add(span_id)
            if definition_span == (match.start(), match.end()):
                continue
            occurrences.append((name, "reference", span_id, item.id, f"{match.start()}:{match.end()}"))
        for match in CONCEPT_ALIAS_RE.finditer(raw):
            name = _clean_concept_name(match.group("name"))
            alias = match.group("kind").lower()
            kind = "definition" if alias == "def" or (alias == "concept" and section_kind_by_id.get(item.section_id) in DEFINITION_SECTION_KINDS) else "reference"
            span_id = add_occurrence(item, name, kind, match.start(), match.end())
            if kind == "definition":
                definitions.setdefault(name, span_id)
            else:
                references.setdefault(name, set()).add(span_id)
            occurrences.append((name, kind, span_id, item.id, f"{match.start()}:{match.end()}"))
        if section_kind_by_id.get(item.section_id) in DEFINITION_SECTION_KINDS and (match := BARE_DEFINITION_RE.search(raw)):
            name = _clean_concept_name(match.group("name"))
            span_id = add_occurrence(item, name, "definition", match.start("name"), match.end("name"))
            definitions.setdefault(name, span_id)
            occurrences.append((name, "definition", span_id, item.id, f"{match.start('name')}:{match.end('name')}"))
        for match in EXTERNAL_REF_RE.finditer(raw):
            name = _clean_concept_name(match.group(1) or match.group(2))
            span_id = add_occurrence(item, name, "external", match.start(), match.end())
            externals.setdefault(name, set()).add(span_id)
            occurrences.append((name, "external", span_id, item.id, f"{match.start()}:{match.end()}"))

    existing_ids = {obj.id for obj in doc.objects}
    all_names = set(definitions) | set(references) | set(externals)
    concept_ids: dict[str, str] = {}
    for name in sorted(all_names):
        if name in definitions:
            status = "defined"
            span_id = definitions[name]
        elif name in externals:
            status = "external"
            span_id = sorted(externals[name])[0]
        else:
            status = "unresolved"
            span_id = sorted(references[name])[0]

        cid = stable_id("concept", name)
        concept_ids[name] = cid
        if cid not in existing_ids:
            doc.objects.append(
                SpecObject(
                    cid,
                    Role.CONCEPT_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    span_id,
                    facts=[("ConceptName", cid, name), ("ConceptStatus", name, status)],
                )
            )
            existing_ids.add(cid)

        if status == "unresolved":
            qid = stable_id("question", "unresolved-concept", name, span_id)
            if qid not in existing_ids:
                doc.objects.append(
                    SpecObject(
                        qid,
                        Role.QUESTION_OBJECT,
                        SemanticLevel.TEMPLATE_PARSED,
                        span_id,
                        facts=[("UnresolvedConcept", qid, name), ("QuestionText", qid, f"Define concept '{name}' or mark it external.")],
                    )
                )
                existing_ids.add(qid)

    for name, kind, span_id, item_id, ordinal_hint in occurrences:
        oid = stable_id("cref", item_id, name, kind, ordinal_hint)
        if oid not in existing_ids:
            facts = [
                ("ConceptReference", oid, name),
                ("ConceptReferenceKind", oid, kind),
                ("SourceItem", oid, item_id),
            ]
            if name in concept_ids:
                facts.append(("RefersToConcept", oid, concept_ids[name]))
            doc.objects.append(SpecObject(oid, Role.CONCEPT_REFERENCE_OBJECT, SemanticLevel.TEMPLATE_PARSED, span_id, facts=facts))
            existing_ids.add(oid)

        if kind in {"reference", "external"}:
            target = f"{oid}:{name}"
            obligation = add_validation_obligation(
                doc,
                "concept-reference-resolved",
                target,
                "Every explicit concept reference must resolve to a local definition or external link.",
                span_id,
            )
            status = next((obj.facts[1][2] for obj in doc.objects if obj.id == concept_ids.get(name)), "unresolved")
            if status in {"defined", "external"}:
                add_check(doc, obligation, CheckStatus.PASS, status)
            else:
                add_check(doc, obligation, CheckStatus.UNKNOWN, "no local definition or external link found")
    return doc


REQUIREMENT_SECTION_KINDS = {"Requirements", "FunctionalSpecifications", "ImplementationRequirements"}
ACCEPTANCE_SECTION_KINDS = {"AcceptanceTests", "Tests"}
REQUIREMENT_LABEL_RE = re.compile(r"\[(?:id|req|requirement-id):\s*([^\]]+)\]", re.IGNORECASE)
COVERAGE_CLAIM_RE = re.compile(r"\[(?:covers|covers-requirement):\s*([^\]]+)\]", re.IGNORECASE)


def _clean_requirement_label(label: str) -> str:
    return re.sub(r"\s+", " ", label).strip()


def build_requirement_test_coverage(doc: SpecDocument) -> SpecDocument:
    """Create shallow requirement/test objects and coverage obligations.

    This is intentionally structural: it attaches explicit acceptance-test bullets
    to a parent requirement when the source nesting provides one, otherwise to the
    most recent requirement in document order. Missing coverage stays Unknown and
    emits a question rather than treating underspecification as success.
    """
    section_kind_by_id = {section.id: section.kind for section in doc.sections}
    existing_ids = {obj.id for obj in doc.objects}
    requirement_item_ids: set[str] = set()
    covered_requirement_item_ids: set[str] = set()
    requirement_label_to_item_ids: dict[str, list[str]] = {}
    pending_coverage_claims: list[tuple[str, str, str, str]] = []
    item_by_id = {item.id: item for item in doc.items}
    last_requirement_item_id: str | None = None

    def nearest_requirement_parent(item_id: str | None) -> str | None:
        while item_id:
            if item_id in requirement_item_ids:
                return item_id
            item_id = item_by_id[item_id].parent_item_id if item_id in item_by_id else None
        return None

    for item in doc.items:
        if section_kind_by_id.get(item.section_id) in REQUIREMENT_SECTION_KINDS:
            requirement_item_ids.add(item.id)
            last_requirement_item_id = item.id
            oid = stable_id("req", item.id)
            label_match = REQUIREMENT_LABEL_RE.search(item.raw_text)
            label = _clean_requirement_label(label_match.group(1)) if label_match else None
            if label:
                requirement_label_to_item_ids.setdefault(label, []).append(item.id)
            if oid not in existing_ids:
                facts = [("Requirement", oid), ("SourceItem", oid, item.id), ("RequirementText", oid, item.raw_text)]
                if label:
                    facts.append(("RequirementLabel", oid, label))
                doc.objects.append(SpecObject(oid, Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, item.span.id, facts=facts))
                existing_ids.add(oid)
        elif section_kind_by_id.get(item.section_id) in ACCEPTANCE_SECTION_KINDS or item.raw_text.lower().startswith("acceptance:"):
            oid = stable_id("test", item.id)
            explicit_labels = [_clean_requirement_label(match.group(1)) for match in COVERAGE_CLAIM_RE.finditer(item.raw_text)]
            target_item_ids: list[str] = []
            for label in explicit_labels:
                labelled_targets = requirement_label_to_item_ids.get(label, [])
                if len(labelled_targets) == 1:
                    target_item_ids.append(labelled_targets[0])
                elif len(labelled_targets) > 1:
                    pending_coverage_claims.append((oid, item.span.id, label, "ambiguous"))
                else:
                    pending_coverage_claims.append((oid, item.span.id, label, "missing"))
            if not target_item_ids and not explicit_labels:
                implicit_target = nearest_requirement_parent(item.parent_item_id) or last_requirement_item_id
                target_item_ids = [implicit_target] if implicit_target else []
            facts = [("TestCase", oid), ("TestKind", oid, "Acceptance"), ("SourceItem", oid, item.id)]
            for label in explicit_labels:
                facts.append(("CoverageClaim", oid, label))
            for target_item_id in dict.fromkeys(target_item_ids):
                facts.append(("Covers", oid, stable_id("req", target_item_id)))
                covered_requirement_item_ids.add(target_item_id)
            if oid not in existing_ids:
                doc.objects.append(SpecObject(oid, Role.VALIDATION_OBJECT, SemanticLevel.TEMPLATE_PARSED, item.span.id, facts=facts))
                existing_ids.add(oid)

    for label, labelled_item_ids in sorted(requirement_label_to_item_ids.items()):
        if len(labelled_item_ids) <= 1:
            continue
        for item_id in labelled_item_ids:
            item = item_by_id[item_id]
            req_id = stable_id("req", item_id)
            obligation = add_validation_obligation(
                doc,
                "requirement-label-is-unique",
                f"{req_id}:{label}",
                "Requirement labels used by explicit coverage claims must be unique before coverage can be resolved.",
                item.span.id,
            )
            add_check(doc, obligation, CheckStatus.UNKNOWN, f"duplicate requirement label {label}")
            qid = stable_id("question", "duplicate-requirement-label", req_id, label)
            if qid not in existing_ids:
                doc.objects.append(
                    SpecObject(
                        qid,
                        Role.QUESTION_OBJECT,
                        SemanticLevel.TEMPLATE_PARSED,
                        item.span.id,
                        facts=[
                            ("DuplicateRequirementLabel", qid, label),
                            ("QuestionText", qid, f"Rename or disambiguate duplicate requirement label '{label}'."),
                            ("Blocks", qid, obligation.id),
                        ],
                    )
                )
                existing_ids.add(qid)

    for test_id, span_id, label, reason in pending_coverage_claims:
        obligation = add_validation_obligation(
            doc,
            "coverage-claim-target-resolved",
            f"{test_id}:{label}",
            "Explicit coverage claims must name exactly one declared requirement label instead of falling back to proximity.",
            span_id,
        )
        evidence = f"no requirement label found for {label}" if reason == "missing" else f"multiple requirements share label {label}"
        add_check(doc, obligation, CheckStatus.UNKNOWN, evidence)
        fact_name = "MissingCoverageTarget" if reason == "missing" else "AmbiguousCoverageTarget"
        qid = stable_id("question", reason + "-coverage-target", test_id, label)
        if qid not in existing_ids:
            doc.objects.append(
                SpecObject(
                    qid,
                    Role.QUESTION_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    span_id,
                    facts=[
                        (fact_name, qid, label),
                        ("QuestionText", qid, f"Which unique requirement is named by coverage label '{label}'?"),
                        ("Blocks", qid, obligation.id),
                    ],
                )
            )
            existing_ids.add(qid)

    for item_id in sorted(requirement_item_ids):
        item = item_by_id[item_id]
        req_id = stable_id("req", item_id)
        obligation = add_validation_obligation(
            doc,
            "requirement-has-acceptance-test",
            req_id,
            "Every requirement should have at least one explicit acceptance test or an open coverage question.",
            item.span.id,
        )
        if item_id in covered_requirement_item_ids:
            add_check(doc, obligation, CheckStatus.PASS, "explicit acceptance test covers requirement")
        else:
            add_check(doc, obligation, CheckStatus.UNKNOWN, "no explicit acceptance test found")
            qid = stable_id("question", "missing-acceptance-test", req_id)
            if qid not in existing_ids:
                doc.objects.append(
                    SpecObject(
                        qid,
                        Role.QUESTION_OBJECT,
                        SemanticLevel.TEMPLATE_PARSED,
                        item.span.id,
                        facts=[
                            ("MissingAcceptanceTest", qid, req_id),
                            ("QuestionText", qid, "What acceptance test demonstrates this requirement?"),
                            ("Blocks", qid, obligation.id),
                        ],
                    )
                )
                existing_ids.add(qid)
    return doc


PASS_REGISTRY = [
    PassSpec("seed-raw-item-objects", "Wrap indexed Plain items as RawTextOnly source objects.", seed_raw_item_objects),
    PassSpec("build-concept-table", "Extract explicit concept definitions, references, external links, and unresolved-question records.", build_concept_table),
    PassSpec("build-requirement-test-coverage", "Create shallow requirement/test objects and Unknown coverage questions.", build_requirement_test_coverage),
    PassSpec("validate-document", "Emit first validation obligations/check records.", validate_document),
]


def run_passes(doc: SpecDocument, passes: list[PassSpec] | None = None) -> SpecDocument:
    for spec in passes or PASS_REGISTRY:
        doc = spec.run(doc)
    return doc


def compile_source(text: str, path: str = "inline.plain") -> SpecDocument:
    return run_passes(index_source(text, path))


def compile_path(path: str | Path) -> SpecDocument:
    return run_passes(index_path(path))

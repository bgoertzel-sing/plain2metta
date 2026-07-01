"""Validation obligation and check creation for the scaffold."""

from __future__ import annotations

from dataclasses import dataclass

from .schema import CheckRecord, CheckStatus, Role, SemanticLevel, SpecDocument, SpecObject, ValidationObligation, stable_id


def add_validation_obligation(doc: SpecDocument, property: str, target_id: str, rationale: str, source_span_id: str | None = None) -> ValidationObligation:
    obl = ValidationObligation(stable_id("vobl", property, target_id), property, target_id, rationale, source_span_id)
    if obl not in doc.validation_obligations:
        doc.validation_obligations.append(obl)
    return obl


def add_check(doc: SpecDocument, obligation: ValidationObligation, status: CheckStatus, evidence: str) -> CheckRecord:
    check = CheckRecord(stable_id("chk", obligation.id, status.value, evidence), obligation.id, obligation.property, obligation.target_id, status, evidence)
    if check not in doc.checks:
        doc.checks.append(check)
    return check


@dataclass(frozen=True)
class FactSchema:
    arity: int
    object_refs: tuple[int, ...] = ()
    item_refs: tuple[int, ...] = ()
    obligation_refs: tuple[int, ...] = ()


FACT_SCHEMAS = {
    "RawText": FactSchema(3),
    "SourceItem": FactSchema(3, item_refs=(2,)),
    "ConceptName": FactSchema(3),
    "ConceptStatus": FactSchema(3),
    "UnresolvedConcept": FactSchema(3),
    "QuestionText": FactSchema(3),
    "ConceptReference": FactSchema(3),
    "ConceptReferenceKind": FactSchema(3),
    "RefersToConcept": FactSchema(3, object_refs=(2,)),
    "Requirement": FactSchema(2),
    "RequirementText": FactSchema(3),
    "TestCase": FactSchema(2),
    "TestKind": FactSchema(3),
    "Covers": FactSchema(3, object_refs=(2,)),
    "MissingAcceptanceTest": FactSchema(3, object_refs=(2,)),
    "UnsupportedFactPredicate": FactSchema(3),
    "Blocks": FactSchema(3, obligation_refs=(2,)),
    "GeneratedFrom": FactSchema(3, object_refs=(2,)),
}


def _validate_object_facts(doc: SpecDocument) -> None:
    """Check fact arities and declared references without inferring semantics."""
    known_objects = {obj.id for obj in doc.objects}
    known_items = {item.id for item in doc.items}
    known_obligations = {obligation.id for obligation in doc.validation_obligations}
    existing_ids = {obj.id for obj in doc.objects}
    unknown_predicate_questions: list[SpecObject] = []

    for obj in list(doc.objects):
        for index, fact in enumerate(obj.facts):
            target = f"{obj.id}:fact:{index}:{fact[0] if fact else 'empty'}"
            arity_obligation = add_validation_obligation(
                doc,
                "fact-has-supported-arity",
                target,
                "Known fact predicates must use the scaffold arity; unknown predicates remain questions for the profile.",
                obj.source_span_id,
            )
            if not fact:
                add_check(doc, arity_obligation, CheckStatus.FAIL, "empty fact tuple")
                continue
            schema = FACT_SCHEMAS.get(str(fact[0]))
            if schema is None:
                add_check(doc, arity_obligation, CheckStatus.UNKNOWN, f"no scaffold fact schema for predicate={fact[0]}")
                qid = stable_id("question", "unsupported-fact-predicate", obj.id, index, fact[0])
                if qid not in existing_ids:
                    unknown_predicate_questions.append(
                        SpecObject(
                            qid,
                            Role.QUESTION_OBJECT,
                            SemanticLevel.TEMPLATE_PARSED,
                            obj.source_span_id,
                            facts=[
                                ("UnsupportedFactPredicate", qid, str(fact[0])),
                                ("QuestionText", qid, f"Should predicate '{fact[0]}' be added to the scaffold fact profile or rewritten?"),
                                ("Blocks", qid, arity_obligation.id),
                            ],
                        )
                    )
                    existing_ids.add(qid)
                continue
            if len(fact) != schema.arity:
                add_check(doc, arity_obligation, CheckStatus.FAIL, f"expected arity {schema.arity}; got {len(fact)}")
                continue
            add_check(doc, arity_obligation, CheckStatus.PASS, f"arity={len(fact)}")

            ref_obligation = add_validation_obligation(
                doc,
                "fact-references-known-targets",
                target,
                "Declared fact references must point to indexed objects, items, or validation obligations.",
                obj.source_span_id,
            )
            missing: list[str] = []
            for pos in schema.object_refs:
                if str(fact[pos]) not in known_objects:
                    missing.append(f"object@{pos}={fact[pos]}")
            for pos in schema.item_refs:
                if str(fact[pos]) not in known_items:
                    missing.append(f"item@{pos}={fact[pos]}")
            for pos in schema.obligation_refs:
                if str(fact[pos]) not in known_obligations:
                    missing.append(f"obligation@{pos}={fact[pos]}")
            add_check(doc, ref_obligation, CheckStatus.FAIL if missing else CheckStatus.PASS, "; ".join(missing) if missing else "all declared references resolve")

    doc.objects.extend(unknown_predicate_questions)


def _validate_check_records(doc: SpecDocument) -> None:
    """Validate the validation layer itself without recursively judging new checks."""
    obligation_by_id = {obligation.id: obligation for obligation in doc.validation_obligations}
    original_checks = list(doc.checks)

    for check in original_checks:
        source_span_id = obligation_by_id[check.obligation_id].source_span_id if check.obligation_id in obligation_by_id else None
        obligation = add_validation_obligation(
            doc,
            "check-links-known-obligation",
            check.id,
            "Every check record must cite an existing validation obligation.",
            source_span_id,
        )
        if check.obligation_id in obligation_by_id:
            add_check(doc, obligation, CheckStatus.PASS, f"obligation={check.obligation_id}")
        else:
            add_check(doc, obligation, CheckStatus.FAIL, f"missing obligation={check.obligation_id}")
            continue

        cited = obligation_by_id[check.obligation_id]
        obligation = add_validation_obligation(
            doc,
            "check-target-matches-obligation",
            check.id,
            "A check record should report the same property and target as its cited obligation.",
            cited.source_span_id,
        )
        mismatches: list[str] = []
        if check.property != cited.property:
            mismatches.append(f"property check={check.property} obligation={cited.property}")
        if check.target_id != cited.target_id:
            mismatches.append(f"target check={check.target_id} obligation={cited.target_id}")
        add_check(doc, obligation, CheckStatus.FAIL if mismatches else CheckStatus.PASS, "; ".join(mismatches) if mismatches else "check agrees with cited obligation")


def validate_document(doc: SpecDocument) -> SpecDocument:
    """Populate first crisp validation records in-place and return ``doc``."""
    known_sections = {s.id for s in doc.sections}
    known_spans = {s.id for s in doc.spans}
    known_levels = {level for level in SemanticLevel}

    for item in doc.items:
        o = add_validation_obligation(doc, "item-has-section", item.id, "Every indexed item must belong to an indexed section.", item.span.id)
        add_check(doc, o, CheckStatus.PASS if item.section_id in known_sections else CheckStatus.FAIL, f"section={item.section_id}")
        o = add_validation_obligation(doc, "item-has-source-span", item.id, "Every indexed item must have an exact source span.", item.span.id)
        add_check(doc, o, CheckStatus.PASS if item.span.id in known_spans else CheckStatus.FAIL, f"span={item.span.id}")

    for obj in doc.objects:
        o = add_validation_obligation(doc, "object-has-known-semantic-level", obj.id, "Backend gates depend on explicit semantic levels.", obj.source_span_id)
        add_check(doc, o, CheckStatus.PASS if obj.semantic_level in known_levels else CheckStatus.FAIL, obj.semantic_level.value)
        o = add_validation_obligation(doc, "object-has-source-or-generated-provenance", obj.id, "Objects must be source-derived or explicitly generated.", obj.source_span_id)
        ok = obj.source_span_id in known_spans or any(f[0] == "GeneratedFrom" for f in obj.facts)
        add_check(doc, o, CheckStatus.PASS if ok else CheckStatus.FAIL, obj.source_span_id or "missing")

    _validate_object_facts(doc)
    _validate_check_records(doc)

    if not doc.objects:
        o = add_validation_obligation(doc, "semantic-objects-present", doc.files[0].id if doc.files else "document", "A compiler pass should create semantic objects after source indexing.")
        add_check(doc, o, CheckStatus.UNKNOWN, "source indexing only; semantic pass not yet run")
    return doc

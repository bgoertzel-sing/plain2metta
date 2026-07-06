"""Validation obligation and check creation for the scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .schema import CheckRecord, CheckStatus, Role, SemanticLevel, SpecDocument, SpecObject, ValidationObligation, stable_id


def _line_for_offset(text: str, offset: int) -> int:
    """Return the 1-based line number containing ``offset`` in ``text``."""
    return text.count("\n", 0, offset) + 1


def add_validation_obligation(doc: SpecDocument, property: str, target_id: str, rationale: str, source_span_id: str | None = None) -> ValidationObligation:
    """Append a validation obligation once, keyed by stable ID.

    Some larger examples create many structurally similar records. Comparing whole
    dataclasses repeatedly makes validation noticeably slow, so duplicate checks
    use the deterministic ID that already defines obligation identity.
    """
    obl = ValidationObligation(stable_id("vobl", property, target_id), property, target_id, rationale, source_span_id)
    if obl.id not in doc._obligation_ids:
        doc._obligation_ids.add(obl.id)
        doc.validation_obligations.append(obl)
    return obl


def add_check(doc: SpecDocument, obligation: ValidationObligation, status: CheckStatus, evidence: str) -> CheckRecord:
    """Append a check record once, keyed by stable ID."""
    check = CheckRecord(stable_id("chk", obligation.id, status.value, evidence), obligation.id, obligation.property, obligation.target_id, status, evidence)
    if check.id not in doc._check_ids:
        doc._check_ids.add(check.id)
        doc.checks.append(check)
    return check


@dataclass(frozen=True)
class FactSchema:
    arity: int
    object_refs: tuple[int, ...] = ()
    item_refs: tuple[int, ...] = ()
    obligation_refs: tuple[int, ...] = ()
    subject_pos: int | None = 1


FACT_SCHEMAS = {
    "RawText": FactSchema(3),
    "SourceItem": FactSchema(3, item_refs=(2,)),
    "ConceptName": FactSchema(3),
    "ConceptStatus": FactSchema(3, subject_pos=None),
    "UnresolvedConcept": FactSchema(3),
    "QuestionText": FactSchema(3),
    "ConceptReference": FactSchema(3),
    "ConceptReferenceKind": FactSchema(3),
    "RefersToConcept": FactSchema(3, object_refs=(2,)),
    "Requirement": FactSchema(2),
    "RequirementText": FactSchema(3),
    "RequirementLabel": FactSchema(3),
    "TestCase": FactSchema(2),
    "TestKind": FactSchema(3),
    "CoverageClaim": FactSchema(3),
    "Covers": FactSchema(3, object_refs=(2,)),
    "MissingAcceptanceTest": FactSchema(3, object_refs=(2,)),
    "OrphanAcceptanceTest": FactSchema(3, object_refs=(2,)),
    "MissingCoverageTarget": FactSchema(3),
    "AmbiguousCoverageTarget": FactSchema(3),
    "DuplicateRequirementLabel": FactSchema(3),
    "UnsupportedFactPredicate": FactSchema(3),
    "UnsupportedSemanticLevel": FactSchema(3),
    "MLTimeSeriesExperiment": FactSchema(2),
    "MethodologySignal": FactSchema(3),
    "MissingMethodologyEvidence": FactSchema(3),
    "SecurityPrivacyReview": FactSchema(2),
    "SecurityPrivacySignal": FactSchema(3),
    "MissingSecurityPrivacyEvidence": FactSchema(3),
    "InformationFlowReview": FactSchema(2),
    "InformationFlowSignal": FactSchema(3),
    "DataFlowEdge": FactSchema(5, subject_pos=None),
    "TemporalOrderEdge": FactSchema(4, subject_pos=None),
    "MissingInformationFlowEvidence": FactSchema(3),
    "Blocks": FactSchema(3, obligation_refs=(2,)),
    "GeneratedFrom": FactSchema(3, object_refs=(2,)),
}


SUPPORTED_PETTA_REIFIED_LEVELS = {
    SemanticLevel.TEMPLATE_PARSED,
    SemanticLevel.ACTION_SCHEMA_PARSED,
    SemanticLevel.PREDICATE_PARSED,
    SemanticLevel.FORMALLY_TYPED,
    SemanticLevel.BACKEND_LOWERED,
    SemanticLevel.VERIFIED,
}


def _validate_plain_files(doc: SpecDocument) -> None:
    """Check indexed file digests against the preserved source text."""
    for plain_file in doc.files:
        obligation = add_validation_obligation(
            doc,
            "plain-file-digest-matches-content",
            plain_file.id,
            "Every PlainFile digest must be reproducible from the preserved UTF-8 source text.",
            None,
        )
        expected = "sha256:" + sha256(plain_file.text.encode("utf-8")).hexdigest()
        add_check(
            doc,
            obligation,
            CheckStatus.PASS if plain_file.digest == expected else CheckStatus.FAIL,
            f"digest={plain_file.digest} expected={expected}",
        )


def _validate_source_spans(doc: SpecDocument) -> None:
    """Check source-span file links, byte bounds, and line numbers."""
    files_by_id = {plain_file.id: plain_file for plain_file in doc.files}

    for span in doc.spans:
        bounds_obligation = add_validation_obligation(
            doc,
            "source-span-within-file-bounds",
            span.id,
            "Every SourceSpan must cite an indexed file and a non-empty byte range within that file.",
            span.id,
        )
        plain_file = files_by_id.get(span.file_id)
        if plain_file is None:
            add_check(doc, bounds_obligation, CheckStatus.FAIL, f"missing file_id={span.file_id}")
            continue
        file_length = len(plain_file.text)
        in_bounds = 0 <= span.start_byte < span.end_byte <= file_length
        add_check(
            doc,
            bounds_obligation,
            CheckStatus.PASS if in_bounds else CheckStatus.FAIL,
            f"bytes={span.start_byte}:{span.end_byte} file_length={file_length}",
        )

        line_obligation = add_validation_obligation(
            doc,
            "source-span-lines-match-byte-offsets",
            span.id,
            "SourceSpan line numbers should match the source byte offsets they summarize.",
            span.id,
        )
        if not in_bounds:
            add_check(doc, line_obligation, CheckStatus.FAIL, "line check skipped because byte range is outside file bounds")
            continue
        expected_start = _line_for_offset(plain_file.text, span.start_byte)
        expected_end = _line_for_offset(plain_file.text, span.end_byte - 1)
        lines_match = span.start_line == expected_start and span.end_line == expected_end and span.start_line <= span.end_line
        add_check(
            doc,
            line_obligation,
            CheckStatus.PASS if lines_match else CheckStatus.FAIL,
            f"lines={span.start_line}:{span.end_line} expected={expected_start}:{expected_end}",
        )


def _validate_petta_reified_profile_levels(doc: SpecDocument) -> None:
    """Make PeTTa reified-profile semantic-level support explicit in validation."""
    existing_ids = {obj.id for obj in doc.objects}
    profile_questions: list[SpecObject] = []

    for obj in list(doc.objects):
        obligation = add_validation_obligation(
            doc,
            "object-supported-by-petta-reified-profile",
            obj.id,
            "The petta_reified_v0 profile exports only conservative semantic levels; unsupported objects require a refusal/question instead of emission.",
            obj.source_span_id,
        )
        if obj.semantic_level in SUPPORTED_PETTA_REIFIED_LEVELS:
            add_check(doc, obligation, CheckStatus.PASS, obj.semantic_level.value)
            continue

        add_check(doc, obligation, CheckStatus.UNKNOWN, f"unsupported semantic level for petta_reified_v0: {obj.semantic_level.value}")
        qid = stable_id("question", "unsupported-petta-reified-level", obj.id, obj.semantic_level.value)
        if qid not in existing_ids:
            profile_questions.append(
                SpecObject(
                    qid,
                    Role.QUESTION_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    obj.source_span_id,
                    facts=[
                        ("UnsupportedSemanticLevel", qid, obj.semantic_level.value),
                        ("QuestionText", qid, f"Should object '{obj.id}' be lifted above {obj.semantic_level.value} before petta_reified_v0 export, or refused?"),
                        ("Blocks", qid, obligation.id),
                    ],
                )
            )
            existing_ids.add(qid)

    doc.objects.extend(profile_questions)


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

            subject_obligation = add_validation_obligation(
                doc,
                "fact-subject-matches-object",
                target,
                "Object-scoped facts must name their owning SpecObject as subject before profile export.",
                obj.source_span_id,
            )
            subject_mismatch = schema.subject_pos is not None and str(fact[schema.subject_pos]) != obj.id
            add_check(
                doc,
                subject_obligation,
                CheckStatus.FAIL if subject_mismatch else CheckStatus.PASS,
                f"subject@{schema.subject_pos}={fact[schema.subject_pos]} object={obj.id}" if subject_mismatch else "fact subject matches owning object or is predicate-scoped",
            )

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


def _validate_question_objects(doc: SpecDocument) -> None:
    """Ensure human-review questions are actionable and tied to blockers."""
    known_obligations = {obligation.id for obligation in doc.validation_obligations}

    for obj in doc.objects:
        if obj.role != Role.QUESTION_OBJECT:
            continue
        question_texts = [str(fact[2]).strip() for fact in obj.facts if len(fact) == 3 and fact[0] == "QuestionText"]
        text_obligation = add_validation_obligation(
            doc,
            "question-has-review-text",
            obj.id,
            "QuestionObject records must preserve a non-empty human-review prompt instead of only a machine tag.",
            obj.source_span_id,
        )
        add_check(
            doc,
            text_obligation,
            CheckStatus.PASS if any(question_texts) else CheckStatus.FAIL,
            "question text present" if any(question_texts) else "missing non-empty QuestionText fact",
        )

        block_targets = [str(fact[2]) for fact in obj.facts if len(fact) == 3 and fact[0] == "Blocks"]
        known_block_targets = [target for target in block_targets if target in known_obligations]
        block_obligation = add_validation_obligation(
            doc,
            "question-blocks-validation-obligation",
            obj.id,
            "QuestionObject records should identify the validation obligation they block so Unknown diagnostics are reviewable.",
            obj.source_span_id,
        )
        if known_block_targets:
            add_check(doc, block_obligation, CheckStatus.PASS, "blocks=" + ",".join(sorted(known_block_targets)))
        elif block_targets:
            add_check(doc, block_obligation, CheckStatus.FAIL, "Blocks facts cite unknown obligations: " + ",".join(sorted(block_targets)))
        else:
            add_check(doc, block_obligation, CheckStatus.FAIL, "missing Blocks fact")


def _validate_validation_obligations(doc: SpecDocument) -> None:
    """Validate obligation provenance and target links without recursion."""
    original_obligations = list(doc.validation_obligations)
    known_targets = (
        {plain_file.id for plain_file in doc.files}
        | {section.id for section in doc.sections}
        | {item.id for item in doc.items}
        | {span.id for span in doc.spans}
        | {obj.id for obj in doc.objects}
        | {obligation.id for obligation in original_obligations}
        | {check.id for check in doc.checks}
    )
    known_spans = {span.id for span in doc.spans}
    object_ids = {obj.id for obj in doc.objects}

    def target_is_declared(target_id: str) -> bool:
        if target_id in known_targets:
            return True
        if ":fact:" in target_id:
            return target_id.split(":fact:", 1)[0] in object_ids
        if ":" in target_id:
            return target_id.split(":", 1)[0] in object_ids
        return False

    for original in original_obligations:
        obligation = add_validation_obligation(
            doc,
            "obligation-has-source-provenance",
            original.id,
            "Validation obligations should cite a known source span, or remain Unknown when generated without a direct source slice.",
            original.source_span_id,
        )
        if original.source_span_id is None:
            add_check(doc, obligation, CheckStatus.UNKNOWN, "no source span declared")
        elif original.source_span_id in known_spans:
            add_check(doc, obligation, CheckStatus.PASS, f"source_span={original.source_span_id}")
        else:
            add_check(doc, obligation, CheckStatus.FAIL, f"missing source_span={original.source_span_id}")

        obligation = add_validation_obligation(
            doc,
            "obligation-target-is-declared",
            original.id,
            "Validation obligation targets must be declared document entities, check IDs, obligation IDs, or supported object-scoped subtargets.",
            original.source_span_id,
        )
        add_check(
            doc,
            obligation,
            CheckStatus.PASS if target_is_declared(original.target_id) else CheckStatus.FAIL,
            f"target={original.target_id}" if target_is_declared(original.target_id) else f"undeclared target={original.target_id}",
        )


def _validate_check_records(doc: SpecDocument) -> None:
    """Validate the validation layer itself without recursively judging new checks."""
    obligation_by_id = {obligation.id: obligation for obligation in doc.validation_obligations}
    original_checks = list(doc.checks)

    for check in original_checks:
        source_span_id = obligation_by_id[check.obligation_id].source_span_id if check.obligation_id in obligation_by_id else None
        obligation = add_validation_obligation(
            doc,
            "check-status-is-known",
            check.id,
            "Every check record status must be one of the declared SpecAtom-HS check statuses before backend export.",
            source_span_id,
        )
        status_value = check.status.value if isinstance(check.status, CheckStatus) else str(check.status)
        add_check(
            doc,
            obligation,
            CheckStatus.PASS if isinstance(check.status, CheckStatus) else CheckStatus.FAIL,
            f"status={status_value}",
        )

        obligation = add_validation_obligation(
            doc,
            "check-has-evidence",
            check.id,
            "Every check record should preserve a non-empty evidence string so Pass/Fail/Unknown statuses remain auditable.",
            source_span_id,
        )
        evidence_text = str(check.evidence).strip()
        add_check(
            doc,
            obligation,
            CheckStatus.PASS if evidence_text else CheckStatus.FAIL,
            "evidence present" if evidence_text else "empty check evidence",
        )

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


def _validate_edge_source_provenance(doc: SpecDocument) -> None:
    """Check that DataFlowEdge and TemporalOrderEdge objects cite per-item source spans.

    Edge objects should carry the source span of the specific item where the edge
    was extracted, not a generic first-item span.  This check verifies that edge
    objects have a source span that belongs to an indexed PlainItem, making edge
    provenance auditable and traceable back to the exact source text.
    """
    item_span_ids = {item.span.id for item in doc.items}
    edge_predicates = {"DataFlowEdge", "TemporalOrderEdge"}

    for obj in doc.objects:
        has_edge_fact = any(fact and str(fact[0]) in edge_predicates for fact in obj.facts)
        if not has_edge_fact:
            continue
        obligation = add_validation_obligation(
            doc,
            "edge-has-item-level-source-provenance",
            obj.id,
            "DataFlowEdge and TemporalOrderEdge objects should cite the source span of the specific item where the edge was found, not a generic first-item span.",
            obj.source_span_id,
        )
        if obj.source_span_id and obj.source_span_id in item_span_ids:
            add_check(doc, obligation, CheckStatus.PASS, f"source_span={obj.source_span_id} belongs to an indexed item")
        elif obj.source_span_id:
            add_check(doc, obligation, CheckStatus.UNKNOWN, f"source_span={obj.source_span_id} does not belong to an indexed item")
        else:
            add_check(doc, obligation, CheckStatus.FAIL, "missing source span for edge object")


def validate_document(doc: SpecDocument) -> SpecDocument:
    """Populate first crisp validation records in-place and return ``doc``."""
    known_files = {f.id for f in doc.files}
    known_sections = {s.id for s in doc.sections}
    known_spans = {s.id for s in doc.spans}
    sections_by_id = {s.id: s for s in doc.sections}
    spans_by_id = {s.id: s for s in doc.spans}
    known_levels = {level for level in SemanticLevel}

    _validate_plain_files(doc)
    _validate_source_spans(doc)

    for section in doc.sections:
        o = add_validation_obligation(doc, "section-file-is-indexed", section.id, "Every indexed section must belong to an indexed PlainFile.", section.span.id)
        add_check(doc, o, CheckStatus.PASS if section.file_id in known_files else CheckStatus.FAIL, f"file={section.file_id}")
        o = add_validation_obligation(doc, "section-has-source-span", section.id, "Every indexed section must have an exact source span.", section.span.id)
        add_check(doc, o, CheckStatus.PASS if section.span.id in known_spans else CheckStatus.FAIL, f"span={section.span.id}")
        o = add_validation_obligation(doc, "section-span-file-matches-section-file", section.id, "A section source span must cite the same PlainFile as the section record.", section.span.id)
        add_check(
            doc,
            o,
            CheckStatus.PASS if section.span.file_id == section.file_id else CheckStatus.FAIL,
            f"section.file_id={section.file_id} span.file_id={section.span.file_id}",
        )

    for item in doc.items:
        o = add_validation_obligation(doc, "item-file-is-indexed", item.id, "Every indexed item must belong to an indexed PlainFile.", item.span.id)
        add_check(doc, o, CheckStatus.PASS if item.file_id in known_files else CheckStatus.FAIL, f"file={item.file_id}")
        o = add_validation_obligation(doc, "item-has-section", item.id, "Every indexed item must belong to an indexed section.", item.span.id)
        add_check(doc, o, CheckStatus.PASS if item.section_id in known_sections else CheckStatus.FAIL, f"section={item.section_id}")
        o = add_validation_obligation(doc, "item-file-matches-section-file", item.id, "An item must cite the same PlainFile as its containing section.", item.span.id)
        section = sections_by_id.get(item.section_id)
        section_file_matches = section is not None and item.file_id == section.file_id
        add_check(
            doc,
            o,
            CheckStatus.PASS if section_file_matches else CheckStatus.FAIL,
            f"item.file_id={item.file_id} section.file_id={section.file_id}" if section else f"missing section={item.section_id}",
        )
        o = add_validation_obligation(doc, "item-has-source-span", item.id, "Every indexed item must have an exact source span.", item.span.id)
        add_check(doc, o, CheckStatus.PASS if item.span.id in known_spans else CheckStatus.FAIL, f"span={item.span.id}")
        o = add_validation_obligation(doc, "item-span-file-matches-item-file", item.id, "An item source span must cite the same PlainFile as the item record.", item.span.id)
        span = spans_by_id.get(item.span.id)
        span_file_matches = span is not None and span.file_id == item.file_id
        add_check(
            doc,
            o,
            CheckStatus.PASS if span_file_matches else CheckStatus.FAIL,
            f"item.file_id={item.file_id} span.file_id={span.file_id}" if span else f"missing span={item.span.id}",
        )

    for obj in doc.objects:
        o = add_validation_obligation(doc, "object-has-known-semantic-level", obj.id, "Backend gates depend on explicit semantic levels.", obj.source_span_id)
        add_check(doc, o, CheckStatus.PASS if obj.semantic_level in known_levels else CheckStatus.FAIL, obj.semantic_level.value)
        o = add_validation_obligation(doc, "object-has-source-or-generated-provenance", obj.id, "Objects must be source-derived or explicitly generated.", obj.source_span_id)
        ok = obj.source_span_id in known_spans or any(f[0] == "GeneratedFrom" for f in obj.facts)
        add_check(doc, o, CheckStatus.PASS if ok else CheckStatus.FAIL, obj.source_span_id or "missing")

    _validate_petta_reified_profile_levels(doc)
    _validate_object_facts(doc)
    _validate_question_objects(doc)
    _validate_validation_obligations(doc)
    _validate_check_records(doc)
    _validate_edge_source_provenance(doc)

    if not doc.objects:
        o = add_validation_obligation(doc, "semantic-objects-present", doc.files[0].id if doc.files else "document", "A compiler pass should create semantic objects after source indexing.")
        add_check(doc, o, CheckStatus.UNKNOWN, "source indexing only; semantic pass not yet run")
    return doc

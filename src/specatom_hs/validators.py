"""Validation obligation and check creation for the scaffold."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import math
import unicodedata

from .schema import CheckRecord, CheckStatus, PlainFile, PlainItem, Role, Section, SemanticLevel, SourceSpan, SpecDocument, SpecObject, ValidationObligation, stable_id


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
    "Scope": FactSchema(3),
    "ScopeText": FactSchema(3),
    "ScopedObject": FactSchema(3, object_refs=(2,)),
    "EpistemicStatus": FactSchema(3),
    "Confidence": FactSchema(3, object_refs=(2,)),
    "ConfidenceValue": FactSchema(3),
    "UnsupportedConfidenceValue": FactSchema(3),
    "Evidence": FactSchema(3),
    "EvidenceText": FactSchema(3),
    "EvidenceSupports": FactSchema(3, object_refs=(2,)),
    "Proof": FactSchema(3, object_refs=(2,)),
    "ProofText": FactSchema(3),
    "ProofFor": FactSchema(3, object_refs=(2,)),
    "MissingProofDetail": FactSchema(3, object_refs=(2,)),
    "Rationale": FactSchema(3, object_refs=(2,)),
    "RationaleText": FactSchema(3),
    "RationaleFor": FactSchema(3, object_refs=(2,)),
    "Interpretation": FactSchema(3),
    "InterpretationText": FactSchema(3),
    "InterpretationOf": FactSchema(3, object_refs=(2,)),
    "InterpretationEvidence": FactSchema(3, object_refs=(2,)),
    "Bridge": FactSchema(4),
    "BridgeOntology": FactSchema(3),
    "BridgeTarget": FactSchema(3),
    "BridgeRelation": FactSchema(3),
    "Revision": FactSchema(3, object_refs=(2,)),
    "RevisionText": FactSchema(3),
    "Revises": FactSchema(3, object_refs=(2,)),
    "Decision": FactSchema(3, object_refs=(2,)),
    "DecisionText": FactSchema(3),
    "DecidesFor": FactSchema(3, object_refs=(2,)),
    "Outcome": FactSchema(3, object_refs=(2,)),
    "OutcomeText": FactSchema(3),
    "OutcomeFor": FactSchema(3, object_refs=(2,)),
    "Observation": FactSchema(3, object_refs=(2,)),
    "ObservationText": FactSchema(3),
    "ObservationFor": FactSchema(3, object_refs=(2,)),
    "Counterexample": FactSchema(3, object_refs=(2,)),
    "CounterexampleText": FactSchema(3),
    "CounterexampleFor": FactSchema(3, object_refs=(2,)),
    "Example": FactSchema(3, object_refs=(2,)),
    "ExampleText": FactSchema(3),
    "ExampleFor": FactSchema(3, object_refs=(2,)),
    "MissingExampleDetail": FactSchema(3, object_refs=(2,)),
    "Citation": FactSchema(3, object_refs=(2,)),
    "CitationText": FactSchema(3),
    "CitationFor": FactSchema(3, object_refs=(2,)),
    "MissingCitationReference": FactSchema(3, object_refs=(2,)),
    "Metric": FactSchema(3, object_refs=(2,)),
    "MetricText": FactSchema(3),
    "MetricFor": FactSchema(3, object_refs=(2,)),
    "MissingMetricDefinition": FactSchema(3, object_refs=(2,)),
    "Validation": FactSchema(3, object_refs=(2,)),
    "ValidationText": FactSchema(3),
    "ValidationFor": FactSchema(3, object_refs=(2,)),
    "MissingValidationDetail": FactSchema(3, object_refs=(2,)),
    "Witness": FactSchema(3, object_refs=(2,)),
    "WitnessText": FactSchema(3),
    "WitnessFor": FactSchema(3, object_refs=(2,)),
    "MissingWitnessArtifact": FactSchema(3, object_refs=(2,)),
    "Process": FactSchema(3, object_refs=(2,)),
    "ProcessText": FactSchema(3),
    "ProcessFor": FactSchema(3, object_refs=(2,)),
    "MissingProcessDefinition": FactSchema(3, object_refs=(2,)),
    "Resource": FactSchema(3, object_refs=(2,)),
    "ResourceText": FactSchema(3),
    "ResourceFor": FactSchema(3, object_refs=(2,)),
    "MissingResourceRequirement": FactSchema(3, object_refs=(2,)),
    "Dependency": FactSchema(3, object_refs=(2,)),
    "DependencyText": FactSchema(3),
    "DependencyFor": FactSchema(3, object_refs=(2,)),
    "MissingDependencyDetail": FactSchema(3, object_refs=(2,)),
    "ExplicitQuestion": FactSchema(3, object_refs=(2,)),
    "QuestionsObject": FactSchema(3, object_refs=(2,)),
    "OpenIssue": FactSchema(3, object_refs=(2,)),
    "OpenIssueText": FactSchema(3),
    "IssueFor": FactSchema(3, object_refs=(2,)),
    "TodoItem": FactSchema(3, object_refs=(2,)),
    "TodoText": FactSchema(3),
    "TodoFor": FactSchema(3, object_refs=(2,)),
    "Assumption": FactSchema(3, object_refs=(2,)),
    "AssumptionText": FactSchema(3),
    "AssumptionFor": FactSchema(3, object_refs=(2,)),
    "AssumptionEvidence": FactSchema(3, object_refs=(2,)),
    "MissingAssumptionEvidence": FactSchema(3, object_refs=(2,)),
    "Invariant": FactSchema(3, object_refs=(2,)),
    "InvariantText": FactSchema(3),
    "InvariantFor": FactSchema(3, object_refs=(2,)),
    "InvariantEvidence": FactSchema(3, object_refs=(2,)),
    "MissingInvariantEvidence": FactSchema(3, object_refs=(2,)),
    "Constraint": FactSchema(3, object_refs=(2,)),
    "ConstraintText": FactSchema(3),
    "ConstraintFor": FactSchema(3, object_refs=(2,)),
    "ConstraintEvidence": FactSchema(3, object_refs=(2,)),
    "MissingConstraintEvidence": FactSchema(3, object_refs=(2,)),
    "Hypothesis": FactSchema(3, object_refs=(2,)),
    "HypothesisText": FactSchema(3),
    "HypothesisFor": FactSchema(3, object_refs=(2,)),
    "HypothesisEvidence": FactSchema(3, object_refs=(2,)),
    "MissingHypothesisEvidence": FactSchema(3, object_refs=(2,)),
    "Claim": FactSchema(3, object_refs=(2,)),
    "ClaimText": FactSchema(3),
    "ClaimFor": FactSchema(3, object_refs=(2,)),
    "ClaimEvidence": FactSchema(3, object_refs=(2,)),
    "MissingClaimEvidence": FactSchema(3, object_refs=(2,)),
    "Axiom": FactSchema(3, object_refs=(2,)),
    "AxiomText": FactSchema(3),
    "AxiomFor": FactSchema(3, object_refs=(2,)),
    "AxiomEvidence": FactSchema(3, object_refs=(2,)),
    "MissingAxiomJustification": FactSchema(3, object_refs=(2,)),
    "Precondition": FactSchema(3, object_refs=(2,)),
    "PreconditionText": FactSchema(3),
    "PreconditionFor": FactSchema(3, object_refs=(2,)),
    "PreconditionEvidence": FactSchema(3, object_refs=(2,)),
    "MissingPreconditionEvidence": FactSchema(3, object_refs=(2,)),
    "Postcondition": FactSchema(3, object_refs=(2,)),
    "PostconditionText": FactSchema(3),
    "PostconditionFor": FactSchema(3, object_refs=(2,)),
    "PostconditionEvidence": FactSchema(3, object_refs=(2,)),
    "MissingPostconditionEvidence": FactSchema(3, object_refs=(2,)),
    "Risk": FactSchema(3, object_refs=(2,)),
    "RiskText": FactSchema(3),
    "RiskFor": FactSchema(3, object_refs=(2,)),
    "RiskMitigation": FactSchema(3, object_refs=(2,)),
    "RiskMitigationText": FactSchema(3),
    "MitigatesRiskFor": FactSchema(3, object_refs=(2,)),
    "RiskMitigatedBy": FactSchema(3, object_refs=(2,)),
    "MissingRiskMitigation": FactSchema(3, object_refs=(2,)),
    "Priority": FactSchema(3, object_refs=(2,)),
    "PriorityText": FactSchema(3),
    "PriorityValue": FactSchema(3),
    "PriorityFor": FactSchema(3, object_refs=(2,)),
    "UnsupportedPriorityValue": FactSchema(3, object_refs=(2,)),
    "Deadline": FactSchema(3, object_refs=(2,)),
    "DeadlineText": FactSchema(3),
    "DeadlineValue": FactSchema(3),
    "DeadlineFor": FactSchema(3, object_refs=(2,)),
    "UnsupportedDeadlineValue": FactSchema(3, object_refs=(2,)),
    "Owner": FactSchema(3, object_refs=(2,)),
    "OwnerText": FactSchema(3),
    "OwnerFor": FactSchema(3, object_refs=(2,)),
    "MissingOwnerAssignment": FactSchema(3, object_refs=(2,)),
    "Limitation": FactSchema(3, object_refs=(2,)),
    "LimitationText": FactSchema(3),
    "LimitationFor": FactSchema(3, object_refs=(2,)),
    "LimitationMitigatedBy": FactSchema(3, object_refs=(2,)),
    "MissingLimitationDisposition": FactSchema(3, object_refs=(2,)),
    "NonGoal": FactSchema(3, object_refs=(2,)),
    "NonGoalText": FactSchema(3),
    "NonGoalFor": FactSchema(3, object_refs=(2,)),
    "Deprecated": FactSchema(3, object_refs=(2,)),
    "DeprecatedText": FactSchema(3),
    "DeprecatedFor": FactSchema(3, object_refs=(2,)),
    "Replacement": FactSchema(3, object_refs=(2,)),
    "ReplacementText": FactSchema(3),
    "Replaces": FactSchema(3, object_refs=(2,)),
    "DeprecatedReplacedBy": FactSchema(3, object_refs=(2,)),
    "MissingDeprecationDisposition": FactSchema(3, object_refs=(2,)),
    "AcceptanceCriterion": FactSchema(3, object_refs=(2,)),
    "AcceptanceCriterionText": FactSchema(3),
    "AcceptanceCriterionFor": FactSchema(3, object_refs=(2,)),
    "MissingAcceptanceCriterionDetail": FactSchema(3, object_refs=(2,)),
    "UnsupportedEpistemicStatus": FactSchema(3),
    "MissingInterpretationEvidence": FactSchema(3, object_refs=(2,)),
    "UnsupportedBridgeOntology": FactSchema(3),
    "UnsupportedBridgeRelation": FactSchema(3),
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
    for index, plain_file in enumerate(doc.files):
        record_target = (
            plain_file.id
            if isinstance(plain_file, PlainFile)
            and isinstance(plain_file.id, str)
            and plain_file.id.strip()
            else stable_id("malformed-plain-file", index, repr(plain_file))
        )
        record_obligation = add_validation_obligation(
            doc,
            "plain-file-has-valid-record-type",
            record_target,
            "Every source-manifest file entry must be a PlainFile record.",
            None,
        )
        is_plain_file = isinstance(plain_file, PlainFile)
        add_check(
            doc,
            record_obligation,
            CheckStatus.PASS if is_plain_file else CheckStatus.FAIL,
            "record type=PlainFile"
            if is_plain_file
            else f"unsupported plain file record type={type(plain_file).__name__}",
        )
        if not is_plain_file:
            continue
        fields_obligation = add_validation_obligation(
            doc,
            "plain-file-has-safe-fields",
            plain_file.id,
            "Backend-safe PlainFile paths and digests must be non-blank strings, and preserved source text must be a string.",
            None,
        )
        unsafe_fields = []
        for name, value in (("path", plain_file.path), ("digest", plain_file.digest)):
            if not isinstance(value, str):
                unsafe_fields.append(f"{name}={value!r} type={type(value).__name__}")
            elif not value.strip():
                unsafe_fields.append(f"{name} is empty")
        if not isinstance(plain_file.text, str):
            unsafe_fields.append(
                f"text={plain_file.text!r} type={type(plain_file.text).__name__}"
            )
        add_check(
            doc,
            fields_obligation,
            CheckStatus.FAIL if unsafe_fields else CheckStatus.PASS,
            "; ".join(unsafe_fields) if unsafe_fields else "path, digest, and text are backend-safe",
        )
        if unsafe_fields:
            continue

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
    file_id_counts = Counter(
        plain_file.id
        for plain_file in doc.files
        if isinstance(plain_file, PlainFile)
        and isinstance(plain_file.id, str)
        and plain_file.id.strip()
    )
    files_by_id = {
        plain_file.id: plain_file
        for plain_file in doc.files
        if isinstance(plain_file, PlainFile)
        and isinstance(plain_file.id, str)
        and plain_file.id.strip()
        and file_id_counts[plain_file.id] == 1
    }

    for index, span in enumerate(doc.spans):
        record_target = (
            span.id
            if isinstance(span, SourceSpan)
            and isinstance(span.id, str)
            and span.id.strip()
            else stable_id("malformed-source-span", index, repr(span))
        )
        record_obligation = add_validation_obligation(
            doc,
            "source-span-has-valid-record-type",
            record_target,
            "Every source-manifest span entry must be a SourceSpan record.",
            None,
        )
        is_source_span = isinstance(span, SourceSpan)
        add_check(
            doc,
            record_obligation,
            CheckStatus.PASS if is_source_span else CheckStatus.FAIL,
            "record type=SourceSpan"
            if is_source_span
            else f"unsupported source span record type={type(span).__name__}",
        )
        if not is_source_span:
            continue

        file_obligation = add_validation_obligation(
            doc,
            "source-span-has-safe-file-identity",
            span.id,
            "Backend-safe SourceSpan file links must be non-blank strings.",
            span.id,
        )
        file_identity_is_safe = isinstance(span.file_id, str) and bool(span.file_id.strip())
        file_evidence = (
            f"file={span.file_id}"
            if file_identity_is_safe
            else f"unsupported source span file identity={span.file_id!r} type={type(span.file_id).__name__}"
        )
        add_check(
            doc,
            file_obligation,
            CheckStatus.PASS if file_identity_is_safe else CheckStatus.FAIL,
            file_evidence,
        )
        if not file_identity_is_safe:
            continue

        field_obligation = add_validation_obligation(
            doc,
            "source-span-has-safe-bounds",
            span.id,
            "Backend-safe SourceSpan byte and line bounds must be ordered non-boolean integers.",
            span.id,
        )
        byte_fields = (span.start_byte, span.end_byte)
        line_fields = (span.start_line, span.end_line)
        byte_types_are_safe = all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in byte_fields
        )
        line_types_are_safe = all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in line_fields
        )
        bounds_are_safe = (
            byte_types_are_safe
            and line_types_are_safe
            and span.start_byte >= 0
            and span.end_byte >= span.start_byte
            and span.start_line >= 1
            and span.end_line >= span.start_line
        )
        if bounds_are_safe:
            bounds_evidence = (
                f"bytes={span.start_byte}:{span.end_byte} "
                f"lines={span.start_line}:{span.end_line}"
            )
        elif not byte_types_are_safe:
            bounds_evidence = (
                "unsupported source span byte bounds "
                f"start={span.start_byte!r} type={type(span.start_byte).__name__} "
                f"end={span.end_byte!r} type={type(span.end_byte).__name__}"
            )
        elif not line_types_are_safe:
            bounds_evidence = (
                "unsupported source span line bounds "
                f"start={span.start_line!r} type={type(span.start_line).__name__} "
                f"end={span.end_line!r} type={type(span.end_line).__name__}"
            )
        else:
            bounds_evidence = (
                f"invalid source span bounds bytes={span.start_byte}:{span.end_byte} "
                f"lines={span.start_line}:{span.end_line}"
            )
        add_check(
            doc,
            field_obligation,
            CheckStatus.PASS if bounds_are_safe else CheckStatus.FAIL,
            bounds_evidence,
        )
        if not bounds_are_safe:
            continue

        bounds_obligation = add_validation_obligation(
            doc,
            "source-span-within-file-bounds",
            span.id,
            "Every SourceSpan must cite an indexed file and a non-empty byte range within that file.",
            span.id,
        )
        plain_file = files_by_id.get(span.file_id)
        if plain_file is None:
            if file_id_counts[span.file_id] > 1:
                evidence = f"ambiguous duplicate file={span.file_id} count={file_id_counts[span.file_id]}"
            else:
                evidence = f"missing file_id={span.file_id}"
            add_check(doc, bounds_obligation, CheckStatus.FAIL, evidence)
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
    existing_ids = {
        obj.id for obj in doc.objects if isinstance(obj, SpecObject) and isinstance(obj.id, str) and obj.id.strip()
    }
    profile_questions: list[SpecObject] = []

    for obj in list(doc.objects):
        if not isinstance(obj, SpecObject):
            continue
        semantic_level_value = (
            obj.semantic_level.value
            if isinstance(obj.semantic_level, SemanticLevel)
            else repr(obj.semantic_level)
        )
        obligation = add_validation_obligation(
            doc,
            "object-supported-by-petta-reified-profile",
            obj.id,
            "The petta_reified_v0 profile exports only conservative semantic levels; unsupported objects require a refusal/question instead of emission.",
            obj.source_span_id,
        )
        if (
            isinstance(obj.semantic_level, SemanticLevel)
            and obj.semantic_level in SUPPORTED_PETTA_REIFIED_LEVELS
        ):
            add_check(doc, obligation, CheckStatus.PASS, semantic_level_value)
            continue

        add_check(doc, obligation, CheckStatus.UNKNOWN, f"unsupported semantic level for petta_reified_v0: {semantic_level_value}")
        qid = stable_id("question", "unsupported-petta-reified-level", obj.id, semantic_level_value)
        if qid not in existing_ids:
            profile_questions.append(
                SpecObject(
                    qid,
                    Role.QUESTION_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    obj.source_span_id,
                    facts=[
                        ("UnsupportedSemanticLevel", qid, semantic_level_value),
                        ("QuestionText", qid, f"Should object '{obj.id}' be lifted above {semantic_level_value} before petta_reified_v0 export, or refused?"),
                        ("Blocks", qid, obligation.id),
                    ],
                )
            )
            existing_ids.add(qid)

    doc.objects.extend(profile_questions)


def _validate_object_facts(doc: SpecDocument) -> None:
    """Check fact arities and declared references without inferring semantics."""
    known_objects = {
        obj.id for obj in doc.objects if isinstance(obj, SpecObject) and isinstance(obj.id, str) and obj.id.strip()
    }
    known_items = {
        item.id
        for item in doc.items
        if isinstance(item, PlainItem) and isinstance(item.id, str) and item.id.strip()
    }
    known_obligations = {
        obligation.id
        for obligation in doc.validation_obligations
        if isinstance(obligation, ValidationObligation)
        and isinstance(obligation.id, str)
        and obligation.id.strip()
    }
    existing_ids = {
        obj.id for obj in doc.objects if isinstance(obj, SpecObject) and isinstance(obj.id, str) and obj.id.strip()
    }
    unknown_predicate_questions: list[SpecObject] = []

    for obj in list(doc.objects):
        if not isinstance(obj, SpecObject):
            continue
        if not isinstance(obj.facts, list):
            continue
        for index, fact in enumerate(obj.facts):
            is_fact_tuple = isinstance(fact, tuple)
            predicate = fact[0] if is_fact_tuple and fact else "empty"
            target = f"{obj.id}:fact:{index}:{predicate}"
            arity_obligation = add_validation_obligation(
                doc,
                "fact-has-supported-arity",
                target,
                "Known fact predicates must use the scaffold arity; unknown predicates remain questions for the profile.",
                obj.source_span_id,
            )
            if not is_fact_tuple:
                add_check(
                    doc,
                    arity_obligation,
                    CheckStatus.FAIL,
                    f"unsupported fact record type={type(fact).__name__}",
                )
                continue
            if not fact:
                add_check(doc, arity_obligation, CheckStatus.FAIL, "empty fact tuple")
                continue
            if not isinstance(fact[0], str):
                add_check(
                    doc,
                    arity_obligation,
                    CheckStatus.FAIL,
                    f"unsupported fact predicate type={type(fact[0]).__name__}",
                )
                continue
            schema = FACT_SCHEMAS.get(fact[0])
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

            argument_obligation = add_validation_obligation(
                doc,
                "fact-arguments-are-backend-safe",
                target,
                "Fact arguments must use non-empty scalar values, with string identities for declared object references, before profile export.",
                obj.source_span_id,
            )
            unsafe_arguments: list[str] = []
            for pos, value in enumerate(fact[1:], start=1):
                if not isinstance(value, (str, int, float, bool)) and value is not None:
                    unsafe_arguments.append(f"argument@{pos} unsupported type={type(value).__name__}")
                    continue
                if pos in schema.object_refs and not isinstance(value, str):
                    unsafe_arguments.append(f"object-reference@{pos} unsupported type={type(value).__name__}")
                    continue
                if value is None or not str(value).strip():
                    unsafe_arguments.append(f"argument@{pos} is empty")
                    continue
                if isinstance(value, float) and not math.isfinite(value):
                    unsafe_arguments.append(f"argument@{pos} is non-finite")
            add_check(
                doc,
                argument_obligation,
                CheckStatus.FAIL if unsafe_arguments else CheckStatus.PASS,
                "; ".join(unsafe_arguments) if unsafe_arguments else "all fact arguments are backend-safe scalars",
            )

            subject_obligation = add_validation_obligation(
                doc,
                "fact-subject-matches-object",
                target,
                "Object-scoped facts must name their owning SpecObject as subject before profile export.",
                obj.source_span_id,
            )
            subject = fact[schema.subject_pos] if schema.subject_pos is not None else None
            subject_type_invalid = schema.subject_pos is not None and not isinstance(subject, str)
            subject_mismatch = (
                schema.subject_pos is not None
                and not subject_type_invalid
                and subject != obj.id
            )
            add_check(
                doc,
                subject_obligation,
                CheckStatus.FAIL if subject_type_invalid or subject_mismatch else CheckStatus.PASS,
                (
                    f"subject@{schema.subject_pos} unsupported type={type(subject).__name__}"
                    if subject_type_invalid
                    else f"subject@{schema.subject_pos}={subject} object={obj.id}"
                    if subject_mismatch
                    else "fact subject matches owning object or is predicate-scoped"
                ),
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
    known_obligations = {
        obligation.id
        for obligation in doc.validation_obligations
        if isinstance(obligation, ValidationObligation)
        and isinstance(obligation.id, str)
        and obligation.id.strip()
    }

    for obj in doc.objects:
        if not isinstance(obj, SpecObject):
            continue
        if obj.role != Role.QUESTION_OBJECT:
            continue
        if not isinstance(obj.facts, list):
            continue
        question_texts = [
            fact[2].strip()
            for fact in obj.facts
            if isinstance(fact, tuple)
            and len(fact) == 3
            and fact[0] == "QuestionText"
            and isinstance(fact[2], str)
        ]
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

        block_targets = [
            fact[2]
            for fact in obj.facts
            if isinstance(fact, tuple)
            and len(fact) == 3
            and fact[0] == "Blocks"
            and isinstance(fact[2], str)
            and fact[2].strip()
        ]
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
        {
            plain_file.id
            for plain_file in doc.files
            if isinstance(plain_file, PlainFile)
            and isinstance(plain_file.id, str)
            and plain_file.id.strip()
        }
        | {section.id for section in doc.sections if isinstance(section, Section) and isinstance(section.id, str) and section.id.strip()}
        | {item.id for item in doc.items if isinstance(item, PlainItem) and isinstance(item.id, str) and item.id.strip()}
        | {
            span.id
            for span in doc.spans
            if isinstance(span, SourceSpan)
            and isinstance(span.id, str)
            and span.id.strip()
        }
        | {
            obj.id
            for obj in doc.objects
            if isinstance(obj, SpecObject) and isinstance(obj.id, str) and obj.id.strip()
        }
        | {
            obligation.id
            for obligation in original_obligations
            if isinstance(obligation, ValidationObligation)
            and isinstance(obligation.id, str)
            and obligation.id.strip()
        }
        | {
            check.id
            for check in doc.checks
            if isinstance(check, CheckRecord)
            and isinstance(check.id, str)
            and check.id.strip()
        }
    )
    known_spans = {
        span.id
        for span in doc.spans
        if isinstance(span, SourceSpan)
        and isinstance(span.id, str)
        and span.id.strip()
    }
    object_ids = {
        obj.id for obj in doc.objects if isinstance(obj, SpecObject) and isinstance(obj.id, str) and obj.id.strip()
    }

    def target_is_declared(target_id: str) -> bool:
        if not isinstance(target_id, str):
            return False
        if target_id in known_targets:
            return True
        return any(
            target_id.startswith(f"{object_id}:")
            and bool(target_id[len(object_id) + 1 :])
            and target_id[len(object_id) + 1 :]
            == target_id[len(object_id) + 1 :].strip()
            and unicodedata.category(target_id[len(object_id) + 1]) != "Cf"
            for object_id in object_ids
        )

    for original in original_obligations:
        if not isinstance(original, ValidationObligation):
            continue
        obligation = add_validation_obligation(
            doc,
            "validation-obligation-has-safe-property",
            original.id,
            "Validation obligation properties must be non-blank strings before backend export.",
            original.source_span_id,
        )
        property_is_safe = isinstance(original.property, str) and bool(original.property.strip())
        add_check(
            doc,
            obligation,
            CheckStatus.PASS if property_is_safe else CheckStatus.FAIL,
            (
                f"property={original.property}"
                if property_is_safe
                else "empty validation obligation property"
                if isinstance(original.property, str)
                else f"unsupported validation obligation property={original.property!r} type={type(original.property).__name__}"
            ),
        )

        obligation = add_validation_obligation(
            doc,
            "validation-obligation-has-reviewable-rationale",
            original.id,
            "Validation obligation rationales must be non-blank reviewable text before backend export.",
            original.source_span_id,
        )
        rationale_is_safe = isinstance(original.rationale, str) and bool(original.rationale.strip())
        add_check(
            doc,
            obligation,
            CheckStatus.PASS if rationale_is_safe else CheckStatus.FAIL,
            (
                "rationale present"
                if rationale_is_safe
                else "empty validation obligation rationale"
                if isinstance(original.rationale, str)
                else f"unsupported validation obligation rationale={original.rationale!r} type={type(original.rationale).__name__}"
            ),
        )

        obligation = add_validation_obligation(
            doc,
            "validation-obligation-has-safe-target",
            original.id,
            "Validation obligation target identities must be non-blank strings before backend export.",
            original.source_span_id,
        )
        target_is_safe = isinstance(original.target_id, str) and bool(original.target_id.strip())
        add_check(
            doc,
            obligation,
            CheckStatus.PASS if target_is_safe else CheckStatus.FAIL,
            (
                f"target={original.target_id}"
                if target_is_safe
                else "empty validation obligation target"
                if isinstance(original.target_id, str)
                else f"unsupported validation obligation target={original.target_id!r} type={type(original.target_id).__name__}"
            ),
        )

        obligation = add_validation_obligation(
            doc,
            "validation-obligation-has-safe-source-span-id",
            original.id,
            "Validation obligation source-span identities must be absent or non-blank strings before backend export.",
            original.source_span_id if isinstance(original.source_span_id, str) else None,
        )
        source_span_id_is_safe = (
            original.source_span_id is None
            or (
                isinstance(original.source_span_id, str)
                and bool(original.source_span_id.strip())
            )
        )
        add_check(
            doc,
            obligation,
            CheckStatus.PASS if source_span_id_is_safe else CheckStatus.FAIL,
            (
                "source span absent"
                if original.source_span_id is None
                else f"source_span={original.source_span_id}"
                if source_span_id_is_safe
                else "empty validation obligation source span identity"
                if isinstance(original.source_span_id, str)
                else f"unsupported validation obligation source span identity={original.source_span_id!r} type={type(original.source_span_id).__name__}"
            ),
        )

        obligation = add_validation_obligation(
            doc,
            "obligation-has-source-provenance",
            original.id,
            "Validation obligations should cite a known source span, or remain Unknown when generated without a direct source slice.",
            original.source_span_id,
        )
        if original.source_span_id is None:
            add_check(doc, obligation, CheckStatus.UNKNOWN, "no source span declared")
        elif isinstance(original.source_span_id, str) and original.source_span_id in known_spans:
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
    obligation_by_id = {
        obligation.id: obligation
        for obligation in doc.validation_obligations
        if isinstance(obligation, ValidationObligation)
        and isinstance(obligation.id, str)
        and obligation.id.strip()
    }
    original_checks = list(doc.checks)

    for check in original_checks:
        if not isinstance(check, CheckRecord):
            continue
        obligation_id_is_safe = (
            isinstance(check.obligation_id, str)
            and bool(check.obligation_id.strip())
        )
        linked_obligation = (
            obligation_by_id.get(check.obligation_id)
            if obligation_id_is_safe
            else None
        )
        source_span_id = linked_obligation.source_span_id if linked_obligation else None
        obligation = add_validation_obligation(
            doc,
            "check-has-safe-property",
            check.id,
            "Check properties must be non-blank strings before backend export.",
            source_span_id,
        )
        property_is_safe = isinstance(check.property, str) and bool(check.property.strip())
        add_check(
            doc,
            obligation,
            CheckStatus.PASS if property_is_safe else CheckStatus.FAIL,
            (
                f"property={check.property}"
                if property_is_safe
                else "empty check property"
                if isinstance(check.property, str)
                else f"unsupported check property={check.property!r} type={type(check.property).__name__}"
            ),
        )

        obligation = add_validation_obligation(
            doc,
            "check-has-safe-target",
            check.id,
            "Check target identities must be non-blank strings before backend export.",
            source_span_id,
        )
        target_is_safe = isinstance(check.target_id, str) and bool(check.target_id.strip())
        add_check(
            doc,
            obligation,
            CheckStatus.PASS if target_is_safe else CheckStatus.FAIL,
            (
                f"target={check.target_id}"
                if target_is_safe
                else "empty check target"
                if isinstance(check.target_id, str)
                else f"unsupported check target={check.target_id!r} type={type(check.target_id).__name__}"
            ),
        )

        obligation = add_validation_obligation(
            doc,
            "check-status-is-known",
            check.id,
            "Every check record status must be one of the declared SpecAtom-HS check statuses before backend export.",
            source_span_id,
        )
        status_is_known = isinstance(check.status, CheckStatus)
        add_check(
            doc,
            obligation,
            CheckStatus.PASS if status_is_known else CheckStatus.FAIL,
            (
                f"status={check.status.value}"
                if status_is_known
                else f"unsupported check status={check.status!r} type={type(check.status).__name__}"
            ),
        )

        obligation = add_validation_obligation(
            doc,
            "check-has-evidence",
            check.id,
            "Every check record should preserve a non-empty evidence string so Pass/Fail/Unknown statuses remain auditable.",
            source_span_id,
        )
        evidence_is_safe = isinstance(check.evidence, str) and bool(check.evidence.strip())
        add_check(
            doc,
            obligation,
            CheckStatus.PASS if evidence_is_safe else CheckStatus.FAIL,
            (
                "evidence present"
                if evidence_is_safe
                else "empty check evidence"
                if isinstance(check.evidence, str)
                else f"unsupported check evidence={check.evidence!r} type={type(check.evidence).__name__}"
            ),
        )

        obligation = add_validation_obligation(
            doc,
            "check-has-safe-obligation-id",
            check.id,
            "Check obligation identities must be non-blank strings before backend export.",
            source_span_id,
        )
        add_check(
            doc,
            obligation,
            CheckStatus.PASS if obligation_id_is_safe else CheckStatus.FAIL,
            (
                f"obligation={check.obligation_id}"
                if obligation_id_is_safe
                else "empty check obligation identity"
                if isinstance(check.obligation_id, str)
                else f"unsupported check obligation identity={check.obligation_id!r} type={type(check.obligation_id).__name__}"
            ),
        )

        obligation = add_validation_obligation(
            doc,
            "check-links-known-obligation",
            check.id,
            "Every check record must cite an existing validation obligation.",
            source_span_id,
        )
        if obligation_id_is_safe and check.obligation_id in obligation_by_id:
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
    """Check that edge objects cite source spans inside indexed PlainItems.

    Edge objects should carry the exact match span when available, or at least a
    source span contained in the specific item where the edge was extracted, not
    a generic first-item span. This keeps edge provenance auditable and traceable
    back to the exact source text.
    """
    spans_by_id = {
        span.id: span
        for span in doc.spans
        if isinstance(span, SourceSpan)
        and isinstance(span.id, str)
        and span.id.strip()
    }
    item_spans = [item.span for item in doc.items if isinstance(item, PlainItem)]
    edge_predicates = {"DataFlowEdge", "TemporalOrderEdge"}

    def containing_item_span_id(span_id: str | None) -> str | None:
        if not span_id or span_id not in spans_by_id:
            return None
        span = spans_by_id[span_id]
        for item_span in item_spans:
            if (
                span.file_id == item_span.file_id
                and item_span.start_byte <= span.start_byte
                and span.end_byte <= item_span.end_byte
            ):
                return item_span.id
        return None

    for obj in doc.objects:
        if not isinstance(obj, SpecObject):
            continue
        if not isinstance(obj.facts, list):
            continue
        has_edge_fact = any(
            isinstance(fact, tuple)
            and bool(fact)
            and str(fact[0]) in edge_predicates
            for fact in obj.facts
        )
        if not has_edge_fact:
            continue
        obligation = add_validation_obligation(
            doc,
            "edge-has-item-level-source-provenance",
            obj.id,
            "DataFlowEdge and TemporalOrderEdge objects should cite an exact or item-contained source span for the specific item where the edge was found, not a generic first-item span.",
            obj.source_span_id,
        )
        container_id = containing_item_span_id(obj.source_span_id)
        if container_id:
            if obj.source_span_id == container_id:
                evidence = f"source_span={obj.source_span_id} is the indexed item span"
            else:
                evidence = f"source_span={obj.source_span_id} is contained in indexed item span {container_id}"
            add_check(doc, obligation, CheckStatus.PASS, evidence)
        elif obj.source_span_id:
            add_check(doc, obligation, CheckStatus.UNKNOWN, f"source_span={obj.source_span_id} is not contained in an indexed item span")
        else:
            add_check(doc, obligation, CheckStatus.FAIL, "missing source span for edge object")


def validate_document(doc: SpecDocument) -> SpecDocument:
    """Populate first crisp validation records in-place and return ``doc``."""
    original_obligations = list(doc.validation_obligations)
    original_checks = list(doc.checks)
    file_id_counts = Counter(
        f.id
        for f in doc.files
        if isinstance(f, PlainFile) and isinstance(f.id, str) and f.id.strip()
    )
    known_files = {
        f.id
        for f in doc.files
        if isinstance(f, PlainFile)
        and isinstance(f.id, str)
        and f.id.strip()
        and file_id_counts[f.id] == 1
    }
    section_id_counts = Counter(
        s.id
        for s in doc.sections
        if isinstance(s, Section) and isinstance(s.id, str) and s.id.strip()
    )
    known_sections = {s.id for s in doc.sections if isinstance(s, Section) and isinstance(s.id, str) and s.id.strip() and section_id_counts[s.id] == 1}
    sections_by_id = {s.id: s for s in doc.sections if isinstance(s, Section) and isinstance(s.id, str) and s.id.strip() and section_id_counts[s.id] == 1}
    item_id_counts = Counter(
        item.id
        for item in doc.items
        if isinstance(item, PlainItem) and isinstance(item.id, str) and item.id.strip()
    )
    items_by_id = {item.id: item for item in doc.items if isinstance(item, PlainItem) and isinstance(item.id, str) and item.id.strip() and item_id_counts[item.id] == 1}
    span_id_counts = Counter(
        s.id
        for s in doc.spans
        if isinstance(s, SourceSpan) and isinstance(s.id, str) and s.id.strip()
    )
    known_spans = {
        s.id
        for s in doc.spans
        if isinstance(s, SourceSpan)
        and isinstance(s.id, str)
        and s.id.strip()
        and span_id_counts[s.id] == 1
    }
    spans_by_id = {
        s.id: s
        for s in doc.spans
        if isinstance(s, SourceSpan)
        and isinstance(s.id, str)
        and s.id.strip()
        and span_id_counts[s.id] == 1
    }
    object_id_counts = Counter(
        obj.id
        for obj in doc.objects
        if isinstance(obj, SpecObject) and isinstance(obj.id, str) and obj.id.strip()
    )
    obligation_id_counts = Counter(
        obligation.id
        for obligation in original_obligations
        if isinstance(obligation, ValidationObligation)
        and isinstance(obligation.id, str)
        and obligation.id.strip()
    )
    check_id_counts = Counter(
        check.id
        for check in original_checks
        if isinstance(check, CheckRecord)
        and isinstance(check.id, str)
        and check.id.strip()
    )
    known_levels = {level for level in SemanticLevel}

    _validate_plain_files(doc)
    _validate_source_spans(doc)

    for plain_file in doc.files:
        if not isinstance(plain_file, PlainFile):
            continue
        o = add_validation_obligation(doc, "plain-file-identity-is-unique", plain_file.id, "Every indexed PlainFile must have a unique identity.")
        identity_is_safe = isinstance(plain_file.id, str) and bool(plain_file.id.strip())
        count = file_id_counts[plain_file.id] if identity_is_safe else 0
        evidence = (
            f"ambiguous duplicate file={plain_file.id} count={count}"
            if count > 1
            else f"file={plain_file.id}"
            if count == 1
            else f"identity cannot be indexed safely: {plain_file.id!r} type={type(plain_file.id).__name__}"
        )
        add_check(doc, o, CheckStatus.PASS if count == 1 else CheckStatus.FAIL, evidence)
        o = add_validation_obligation(doc, "plain-file-has-safe-identity", plain_file.id, "Backend-safe PlainFile identities must be non-blank strings.")
        identity_evidence = (
            f"file={plain_file.id}"
            if identity_is_safe
            else f"unsupported file identity={plain_file.id!r} type={type(plain_file.id).__name__}"
        )
        add_check(doc, o, CheckStatus.PASS if identity_is_safe else CheckStatus.FAIL, identity_evidence)

    for span in doc.spans:
        if not isinstance(span, SourceSpan):
            continue
        o = add_validation_obligation(doc, "source-span-identity-is-unique", span.id, "Every indexed SourceSpan must have a unique identity.", span.id)
        identity_is_safe = isinstance(span.id, str) and bool(span.id.strip())
        count = span_id_counts[span.id] if identity_is_safe else 0
        evidence = (
            f"ambiguous duplicate span={span.id} count={count}"
            if count > 1
            else f"span={span.id}"
            if count == 1
            else f"identity cannot be indexed safely: {span.id!r} type={type(span.id).__name__}"
        )
        add_check(doc, o, CheckStatus.PASS if count == 1 else CheckStatus.FAIL, evidence)
        o = add_validation_obligation(doc, "source-span-has-safe-identity", span.id, "Backend-safe SourceSpan identities must be non-blank strings.", span.id)
        identity_evidence = (
            f"span={span.id}"
            if identity_is_safe
            else f"unsupported span identity={span.id!r} type={type(span.id).__name__}"
        )
        add_check(doc, o, CheckStatus.PASS if identity_is_safe else CheckStatus.FAIL, identity_evidence)

    for index, section in enumerate(doc.sections):
        record_target = (
            section.id
            if isinstance(section, Section)
            and isinstance(section.id, str)
            and section.id.strip()
            else stable_id("malformed-section", index, repr(section))
        )
        record_obligation = add_validation_obligation(
            doc,
            "section-has-valid-record-type",
            record_target,
            "Every source-manifest section entry must be a Section record.",
            None,
        )
        is_section = isinstance(section, Section)
        add_check(
            doc,
            record_obligation,
            CheckStatus.PASS if is_section else CheckStatus.FAIL,
            "record type=Section"
            if is_section
            else f"unsupported section record type={type(section).__name__}",
        )
        if not is_section:
            continue

        section_span_id = (
            section.span.id
            if isinstance(section.span, SourceSpan)
            and isinstance(section.span.id, str)
            and section.span.id.strip()
            else None
        )
        o = add_validation_obligation(
            doc,
            "section-has-safe-source-span",
            section.id,
            "A backend-safe Section source span must be a SourceSpan with a non-blank string identity.",
            section_span_id,
        )
        span_is_safe = section_span_id is not None
        span_evidence = (
            f"span={section_span_id}"
            if span_is_safe
            else f"unsupported section span={section.span!r} type={type(section.span).__name__}"
        )
        add_check(
            doc,
            o,
            CheckStatus.PASS if span_is_safe else CheckStatus.FAIL,
            span_evidence,
        )
        if not span_is_safe:
            continue

        o = add_validation_obligation(doc, "section-identity-is-unique", section.id, "Every indexed section must have a unique identity.", section_span_id)
        identity_is_safe = isinstance(section.id, str) and bool(section.id.strip())
        count = section_id_counts[section.id] if identity_is_safe else 0
        section_identity_evidence = (
            f"ambiguous duplicate section={section.id} count={count}"
            if count > 1
            else f"section={section.id}"
            if count == 1
            else f"identity cannot be indexed safely: {section.id!r} type={type(section.id).__name__}"
        )
        add_check(doc, o, CheckStatus.PASS if count == 1 else CheckStatus.FAIL, section_identity_evidence)
        o = add_validation_obligation(doc, "section-has-safe-identity", section.id, "Backend-safe Section identities must be non-blank strings.", section_span_id)
        identity_evidence = (
            f"section={section.id}"
            if identity_is_safe
            else f"unsupported section identity={section.id!r} type={type(section.id).__name__}"
        )
        add_check(doc, o, CheckStatus.PASS if identity_is_safe else CheckStatus.FAIL, identity_evidence)
        o = add_validation_obligation(
            doc,
            "section-has-safe-fields",
            section.id,
            "Backend-safe Section kinds must be non-blank strings and ordinals must be non-negative non-boolean integers.",
            section.span.id,
        )
        unsafe_fields = []
        if not isinstance(section.kind, str):
            unsafe_fields.append(f"kind={section.kind!r} type={type(section.kind).__name__}")
        elif not section.kind.strip():
            unsafe_fields.append("kind is empty")
        if not isinstance(section.ordinal, int) or isinstance(section.ordinal, bool):
            unsafe_fields.append(f"ordinal={section.ordinal!r} type={type(section.ordinal).__name__}")
        elif section.ordinal < 0:
            unsafe_fields.append(f"ordinal={section.ordinal} is negative")
        add_check(
            doc,
            o,
            CheckStatus.FAIL if unsafe_fields else CheckStatus.PASS,
            "; ".join(unsafe_fields) if unsafe_fields else "kind and ordinal are backend-safe",
        )
        o = add_validation_obligation(
            doc,
            "section-has-safe-file-identity",
            section.id,
            "A backend-safe Section file link must be a non-blank string.",
            section.span.id,
        )
        file_identity_is_safe = isinstance(section.file_id, str) and bool(section.file_id.strip())
        file_identity_evidence = (
            f"file_id={section.file_id}"
            if file_identity_is_safe
            else f"unsupported file_id={section.file_id!r} type={type(section.file_id).__name__}"
        )
        add_check(
            doc,
            o,
            CheckStatus.PASS if file_identity_is_safe else CheckStatus.FAIL,
            file_identity_evidence,
        )
        if not file_identity_is_safe:
            continue
        o = add_validation_obligation(doc, "section-file-is-indexed", section.id, "Every indexed section must belong to an indexed PlainFile.", section.span.id)
        file_evidence = (
            f"ambiguous duplicate file={section.file_id} count={file_id_counts[section.file_id]}"
            if file_id_counts[section.file_id] > 1
            else f"file={section.file_id}"
        )
        add_check(doc, o, CheckStatus.PASS if section.file_id in known_files else CheckStatus.FAIL, file_evidence)
        o = add_validation_obligation(doc, "section-has-source-span", section.id, "Every indexed section must have an exact source span.", section.span.id)
        section_span_evidence = (
            f"ambiguous duplicate span={section.span.id} count={span_id_counts[section.span.id]}"
            if span_id_counts[section.span.id] > 1
            else f"span={section.span.id}"
        )
        add_check(doc, o, CheckStatus.PASS if section.span.id in known_spans else CheckStatus.FAIL, section_span_evidence)
        o = add_validation_obligation(doc, "section-span-file-matches-section-file", section.id, "A section source span must cite the same PlainFile as the section record.", section.span.id)
        span = spans_by_id.get(section.span.id)
        span_file_matches = span is not None and span.file_id == section.file_id
        if span_id_counts[section.span.id] > 1:
            evidence = f"ambiguous duplicate span={section.span.id} count={span_id_counts[section.span.id]}"
        else:
            evidence = f"section.file_id={section.file_id} span.file_id={span.file_id}" if span else f"missing span={section.span.id}"
        add_check(
            doc,
            o,
            CheckStatus.PASS if span_file_matches else CheckStatus.FAIL,
            evidence,
        )

    for index, item in enumerate(doc.items):
        record_target = (
            item.id
            if isinstance(item, PlainItem)
            and isinstance(item.id, str)
            and item.id.strip()
            else stable_id("malformed-item", index, repr(item))
        )
        record_obligation = add_validation_obligation(
            doc,
            "item-has-valid-record-type",
            record_target,
            "Every source-manifest item entry must be a PlainItem record.",
            None,
        )
        is_item = isinstance(item, PlainItem)
        add_check(
            doc,
            record_obligation,
            CheckStatus.PASS if is_item else CheckStatus.FAIL,
            "record type=PlainItem"
            if is_item
            else f"unsupported item record type={type(item).__name__}",
        )
        if not is_item:
            continue

        item_span_id = (
            item.span.id
            if isinstance(item.span, SourceSpan)
            and isinstance(item.span.id, str)
            and item.span.id.strip()
            else None
        )
        o = add_validation_obligation(
            doc,
            "item-has-safe-source-span",
            item.id,
            "A backend-safe PlainItem source span must be a SourceSpan with a non-blank string identity.",
            item_span_id,
        )
        span_is_safe = item_span_id is not None
        span_evidence = (
            f"span={item_span_id}"
            if span_is_safe
            else f"unsupported item span={item.span!r} type={type(item.span).__name__}"
        )
        add_check(
            doc,
            o,
            CheckStatus.PASS if span_is_safe else CheckStatus.FAIL,
            span_evidence,
        )
        if not span_is_safe:
            continue

        o = add_validation_obligation(doc, "item-identity-is-unique", item.id, "Every indexed item must have a unique identity.", item_span_id)
        identity_is_safe = isinstance(item.id, str) and bool(item.id.strip())
        count = item_id_counts[item.id] if identity_is_safe else 0
        item_identity_evidence = (
            f"ambiguous duplicate item={item.id} count={count}"
            if count > 1
            else f"item={item.id}"
            if count == 1
            else f"identity cannot be indexed safely: {item.id!r} type={type(item.id).__name__}"
        )
        add_check(doc, o, CheckStatus.PASS if count == 1 else CheckStatus.FAIL, item_identity_evidence)
        o = add_validation_obligation(doc, "item-has-safe-identity", item.id, "Backend-safe PlainItem identities must be non-blank strings.", item.span.id)
        identity_evidence = (
            f"item={item.id}"
            if identity_is_safe
            else f"unsupported item identity={item.id!r} type={type(item.id).__name__}"
        )
        add_check(doc, o, CheckStatus.PASS if identity_is_safe else CheckStatus.FAIL, identity_evidence)
        o = add_validation_obligation(
            doc,
            "item-has-safe-fields",
            item.id,
            "Backend-safe PlainItem ordinals and nesting depths must be non-negative non-boolean integers, and raw text must be non-blank text.",
            item.span.id,
        )
        unsafe_fields = []
        if not isinstance(item.ordinal, int) or isinstance(item.ordinal, bool):
            unsafe_fields.append(f"ordinal={item.ordinal!r} type={type(item.ordinal).__name__}")
        elif item.ordinal < 0:
            unsafe_fields.append(f"ordinal={item.ordinal} is negative")
        if not isinstance(item.level, int) or isinstance(item.level, bool):
            unsafe_fields.append(f"level={item.level!r} type={type(item.level).__name__}")
        elif item.level < 0:
            unsafe_fields.append(f"level={item.level} is negative")
        if not isinstance(item.raw_text, str):
            unsafe_fields.append(f"raw_text={item.raw_text!r} type={type(item.raw_text).__name__}")
        elif not item.raw_text.strip():
            unsafe_fields.append("raw_text is empty")
        add_check(
            doc,
            o,
            CheckStatus.FAIL if unsafe_fields else CheckStatus.PASS,
            "; ".join(unsafe_fields) if unsafe_fields else "ordinal, level, and raw_text are backend-safe",
        )
        o = add_validation_obligation(
            doc,
            "item-has-safe-link-identities",
            item.id,
            "Backend-safe PlainItem file and section links must be non-blank strings; an optional parent link must be absent or a non-blank string.",
            item.span.id,
        )
        unsafe_links = []
        for field_name, value in (("file_id", item.file_id), ("section_id", item.section_id)):
            if not isinstance(value, str):
                unsafe_links.append(f"{field_name}={value!r} type={type(value).__name__}")
            elif not value.strip():
                unsafe_links.append(f"{field_name} is empty")
        if item.parent_item_id is not None:
            if not isinstance(item.parent_item_id, str):
                unsafe_links.append(
                    f"parent_item_id={item.parent_item_id!r} type={type(item.parent_item_id).__name__}"
                )
            elif not item.parent_item_id.strip():
                unsafe_links.append("parent_item_id is empty")
        add_check(
            doc,
            o,
            CheckStatus.FAIL if unsafe_links else CheckStatus.PASS,
            "; ".join(unsafe_links) if unsafe_links else "file, section, and optional parent link identities are backend-safe",
        )
        links_are_safe = not unsafe_links
        if not links_are_safe:
            continue
        o = add_validation_obligation(doc, "item-file-is-indexed", item.id, "Every indexed item must belong to an indexed PlainFile.", item.span.id)
        file_evidence = (
            f"ambiguous duplicate file={item.file_id} count={file_id_counts[item.file_id]}"
            if file_id_counts[item.file_id] > 1
            else f"file={item.file_id}"
        )
        add_check(doc, o, CheckStatus.PASS if item.file_id in known_files else CheckStatus.FAIL, file_evidence)
        o = add_validation_obligation(doc, "item-has-section", item.id, "Every indexed item must belong to an indexed section.", item.span.id)
        if section_id_counts[item.section_id] > 1:
            section_evidence = f"ambiguous duplicate section={item.section_id} count={section_id_counts[item.section_id]}"
        else:
            section_evidence = f"section={item.section_id}"
        add_check(doc, o, CheckStatus.PASS if item.section_id in sections_by_id else CheckStatus.FAIL, section_evidence)
        o = add_validation_obligation(doc, "item-file-matches-section-file", item.id, "An item must cite the same PlainFile as its containing section.", item.span.id)
        section = sections_by_id.get(item.section_id)
        section_file_matches = section is not None and item.file_id == section.file_id
        if section_id_counts[item.section_id] > 1:
            section_match_evidence = f"ambiguous duplicate section={item.section_id} count={section_id_counts[item.section_id]}"
        else:
            section_match_evidence = f"item.file_id={item.file_id} section.file_id={section.file_id}" if section else f"missing section={item.section_id}"
        add_check(
            doc,
            o,
            CheckStatus.PASS if section_file_matches else CheckStatus.FAIL,
            section_match_evidence,
        )
        o = add_validation_obligation(doc, "item-has-source-span", item.id, "Every indexed item must have an exact source span.", item.span.id)
        item_span_evidence = (
            f"ambiguous duplicate span={item.span.id} count={span_id_counts[item.span.id]}"
            if span_id_counts[item.span.id] > 1
            else f"span={item.span.id}"
        )
        add_check(doc, o, CheckStatus.PASS if item.span.id in known_spans else CheckStatus.FAIL, item_span_evidence)
        o = add_validation_obligation(doc, "item-span-file-matches-item-file", item.id, "An item source span must cite the same PlainFile as the item record.", item.span.id)
        span = spans_by_id.get(item.span.id)
        span_file_matches = span is not None and span.file_id == item.file_id
        if span_id_counts[item.span.id] > 1:
            evidence = f"ambiguous duplicate span={item.span.id} count={span_id_counts[item.span.id]}"
        else:
            evidence = f"item.file_id={item.file_id} span.file_id={span.file_id}" if span else f"missing span={item.span.id}"
        add_check(
            doc,
            o,
            CheckStatus.PASS if span_file_matches else CheckStatus.FAIL,
            evidence,
        )
        if item.parent_item_id is not None:
            o = add_validation_obligation(doc, "item-parent-is-indexed", item.id, "A nested item must cite a unique indexed parent item.", item.span.id)
            parent_count = item_id_counts[item.parent_item_id]
            if parent_count > 1:
                parent_evidence = f"ambiguous duplicate item={item.parent_item_id} count={parent_count}"
            else:
                parent_evidence = f"parent_item={item.parent_item_id}"
            parent = items_by_id.get(item.parent_item_id)
            add_check(doc, o, CheckStatus.PASS if parent is not None else CheckStatus.FAIL, parent_evidence)

            o = add_validation_obligation(doc, "item-parent-is-not-self", item.id, "An item must not cite itself as its parent.", item.span.id)
            add_check(
                doc,
                o,
                CheckStatus.PASS if item.parent_item_id != item.id else CheckStatus.FAIL,
                f"item={item.id} parent_item={item.parent_item_id}",
            )

            o = add_validation_obligation(doc, "item-parent-context-matches", item.id, "A nested item and its parent must belong to the same PlainFile and section.", item.span.id)
            context_matches = parent is not None and parent.file_id == item.file_id and parent.section_id == item.section_id
            context_evidence = (
                f"item.file_id={item.file_id} item.section_id={item.section_id} "
                f"parent.file_id={parent.file_id} parent.section_id={parent.section_id}"
                if parent is not None
                else parent_evidence
            )
            add_check(doc, o, CheckStatus.PASS if context_matches else CheckStatus.FAIL, context_evidence)

    for index, obj in enumerate(doc.objects):
        record_target = obj.id if isinstance(obj, SpecObject) and isinstance(obj.id, str) and obj.id.strip() else stable_id("malformed-object", index, repr(obj))
        record_obligation = add_validation_obligation(doc, "object-has-valid-record-type", record_target, "Every semantic-object entry must be a SpecObject record.")
        is_object = isinstance(obj, SpecObject)
        add_check(doc, record_obligation, CheckStatus.PASS if is_object else CheckStatus.FAIL, "record type=SpecObject" if is_object else f"unsupported object record type={type(obj).__name__}")
        if not is_object:
            continue
        o = add_validation_obligation(doc, "object-identity-is-unique", obj.id, "Every SpecObject must have a unique identity before backend export.", obj.source_span_id)
        object_id_is_safe = isinstance(obj.id, str) and bool(obj.id.strip())
        object_id_count = object_id_counts[obj.id] if object_id_is_safe else 0
        object_identity_evidence = (
            f"ambiguous duplicate object={obj.id} count={object_id_count}"
            if object_id_count > 1
            else f"object={obj.id}"
            if object_id_count == 1
            else f"identity cannot be indexed safely: {obj.id!r} type={type(obj.id).__name__}"
        )
        add_check(doc, o, CheckStatus.PASS if object_id_count == 1 else CheckStatus.FAIL, object_identity_evidence)
        o = add_validation_obligation(doc, "object-has-safe-identity", obj.id, "Backend-safe SpecObject identities must be non-blank strings.", obj.source_span_id)
        object_id_evidence = (
            f"object={obj.id}"
            if object_id_is_safe
            else f"unsupported object identity={obj.id!r} type={type(obj.id).__name__}"
        )
        add_check(doc, o, CheckStatus.PASS if object_id_is_safe else CheckStatus.FAIL, object_id_evidence)
        o = add_validation_obligation(doc, "object-has-known-role", obj.id, "Backend gates depend on explicit object roles.", obj.source_span_id)
        role_is_known = isinstance(obj.role, Role)
        role_evidence = obj.role.value if role_is_known else f"unsupported object role={obj.role!r}"
        add_check(doc, o, CheckStatus.PASS if role_is_known else CheckStatus.FAIL, role_evidence)
        o = add_validation_obligation(doc, "object-has-known-semantic-level", obj.id, "Backend gates depend on explicit semantic levels.", obj.source_span_id)
        semantic_level_is_known = (
            isinstance(obj.semantic_level, SemanticLevel)
            and obj.semantic_level in known_levels
        )
        semantic_level_evidence = (
            obj.semantic_level.value
            if semantic_level_is_known
            else f"unsupported semantic level={obj.semantic_level!r}"
        )
        add_check(
            doc,
            o,
            CheckStatus.PASS if semantic_level_is_known else CheckStatus.FAIL,
            semantic_level_evidence,
        )
        o = add_validation_obligation(doc, "object-has-valid-facts-container", obj.id, "Every SpecObject facts container must be a list before validation or backend export.", obj.source_span_id)
        facts_container_is_valid = isinstance(obj.facts, list)
        facts_container_evidence = "facts container type=list" if facts_container_is_valid else f"unsupported facts container type={type(obj.facts).__name__}"
        add_check(doc, o, CheckStatus.PASS if facts_container_is_valid else CheckStatus.FAIL, facts_container_evidence)
        o = add_validation_obligation(
            doc,
            "object-has-safe-source-span-id",
            obj.id,
            "Backend-safe optional SpecObject provenance must be absent or a non-blank string identity.",
            obj.source_span_id if isinstance(obj.source_span_id, str) else None,
        )
        source_span_id_is_safe = (
            obj.source_span_id is None
            or (
                isinstance(obj.source_span_id, str)
                and bool(obj.source_span_id.strip())
            )
        )
        source_span_id_evidence = (
            "source_span=None"
            if obj.source_span_id is None
            else f"source_span={obj.source_span_id}"
            if source_span_id_is_safe
            else f"unsupported object source span identity={obj.source_span_id!r} type={type(obj.source_span_id).__name__}"
        )
        add_check(
            doc,
            o,
            CheckStatus.PASS if source_span_id_is_safe else CheckStatus.FAIL,
            source_span_id_evidence,
        )
        o = add_validation_obligation(doc, "object-has-source-or-generated-provenance", obj.id, "Objects must be source-derived or explicitly generated.", obj.source_span_id)
        ok = (
            isinstance(obj.source_span_id, str)
            and obj.source_span_id in known_spans
        ) or (isinstance(obj.facts, list) and any(
            isinstance(fact, tuple) and bool(fact) and fact[0] == "GeneratedFrom"
            for fact in obj.facts
        ))
        provenance_evidence = (
            obj.source_span_id
            if isinstance(obj.source_span_id, str) and obj.source_span_id
            else "missing"
            if obj.source_span_id is None
            else f"unsupported source span identity={obj.source_span_id!r} type={type(obj.source_span_id).__name__}"
        )
        add_check(doc, o, CheckStatus.PASS if ok else CheckStatus.FAIL, provenance_evidence)

    for index, obligation in enumerate(original_obligations):
        record_target = (
            obligation.id
            if isinstance(obligation, ValidationObligation)
            and isinstance(obligation.id, str)
            and obligation.id.strip()
            else stable_id("malformed-validation-obligation", index, repr(obligation))
        )
        record_check = add_validation_obligation(
            doc,
            "validation-obligation-has-valid-record-type",
            record_target,
            "Every validation-obligation entry must be a ValidationObligation record.",
        )
        is_obligation = isinstance(obligation, ValidationObligation)
        add_check(
            doc,
            record_check,
            CheckStatus.PASS if is_obligation else CheckStatus.FAIL,
            "record type=ValidationObligation"
            if is_obligation
            else f"unsupported validation obligation record type={type(obligation).__name__}",
        )
        if not is_obligation:
            continue
        o = add_validation_obligation(
            doc,
            "validation-obligation-identity-is-unique",
            obligation.id,
            "Every ValidationObligation must have a unique identity before backend export.",
            obligation.source_span_id,
        )
        identity_is_safe = isinstance(obligation.id, str) and bool(obligation.id.strip())
        count = obligation_id_counts[obligation.id] if identity_is_safe else 0
        evidence = (
            f"ambiguous duplicate validation obligation={obligation.id} count={count}"
            if count > 1
            else f"validation obligation={obligation.id}"
            if count == 1
            else f"identity cannot be indexed safely: {obligation.id!r} type={type(obligation.id).__name__}"
        )
        add_check(doc, o, CheckStatus.PASS if count == 1 else CheckStatus.FAIL, evidence)
        o = add_validation_obligation(
            doc,
            "validation-obligation-has-safe-identity",
            obligation.id,
            "Backend-safe ValidationObligation identities must be non-blank strings.",
            obligation.source_span_id,
        )
        identity_evidence = (
            f"validation obligation={obligation.id}"
            if identity_is_safe
            else f"unsupported validation obligation identity={obligation.id!r} type={type(obligation.id).__name__}"
        )
        add_check(doc, o, CheckStatus.PASS if identity_is_safe else CheckStatus.FAIL, identity_evidence)

    for index, check in enumerate(original_checks):
        record_target = (
            check.id
            if isinstance(check, CheckRecord)
            and isinstance(check.id, str)
            and check.id.strip()
            else stable_id("malformed-check-record", index, repr(check))
        )
        record_obligation = add_validation_obligation(
            doc,
            "check-has-valid-record-type",
            record_target,
            "Every check entry must be a CheckRecord.",
        )
        is_check = isinstance(check, CheckRecord)
        add_check(
            doc,
            record_obligation,
            CheckStatus.PASS if is_check else CheckStatus.FAIL,
            "record type=CheckRecord"
            if is_check
            else f"unsupported check record type={type(check).__name__}",
        )
        if not is_check:
            continue
        o = add_validation_obligation(
            doc,
            "check-identity-is-unique",
            check.id,
            "Every CheckRecord must have a unique identity before backend export.",
        )
        identity_is_safe = isinstance(check.id, str) and bool(check.id.strip())
        count = check_id_counts[check.id] if identity_is_safe else 0
        evidence = (
            f"ambiguous duplicate check={check.id} count={count}"
            if count > 1
            else f"check={check.id}"
            if count == 1
            else f"identity cannot be indexed safely: {check.id!r} type={type(check.id).__name__}"
        )
        add_check(doc, o, CheckStatus.PASS if count == 1 else CheckStatus.FAIL, evidence)
        o = add_validation_obligation(
            doc,
            "check-has-safe-identity",
            check.id,
            "Backend-safe CheckRecord identities must be non-blank strings.",
        )
        identity_evidence = (
            f"check={check.id}"
            if identity_is_safe
            else f"unsupported check identity={check.id!r} type={type(check.id).__name__}"
        )
        add_check(doc, o, CheckStatus.PASS if identity_is_safe else CheckStatus.FAIL, identity_evidence)

    _validate_petta_reified_profile_levels(doc)
    _validate_object_facts(doc)
    _validate_question_objects(doc)
    _validate_validation_obligations(doc)
    _validate_check_records(doc)
    _validate_edge_source_provenance(doc)

    if not doc.objects:
        document_target = next(
            (
                plain_file.id
                for plain_file in doc.files
                if isinstance(plain_file, PlainFile)
                and isinstance(plain_file.id, str)
                and plain_file.id.strip()
            ),
            "document",
        )
        o = add_validation_obligation(doc, "semantic-objects-present", document_target, "A compiler pass should create semantic objects after source indexing.")
        add_check(doc, o, CheckStatus.UNKNOWN, "source indexing only; semantic pass not yet run")
    return doc

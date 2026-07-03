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
                qid = stable_id("question", "unresolved-concept", name, definitions.get(name) or sorted(references.get(name, {span_id}))[0])
                question = next((obj for obj in doc.objects if obj.id == qid), None)
                block_fact = ("Blocks", qid, obligation.id)
                if question is not None and block_fact not in question.facts:
                    question.facts.append(block_fact)
    return doc


REQUIREMENT_SECTION_KINDS = {"Requirements", "FunctionalSpecifications", "ImplementationRequirements"}
ACCEPTANCE_SECTION_KINDS = {"AcceptanceTests", "Tests"}
REQUIREMENT_LABEL_RE = re.compile(r"\[(?:id|req|requirement-id):\s*([^\]]+)\]", re.IGNORECASE)
COVERAGE_CLAIM_RE = re.compile(r"\[(?:covers|covers-requirement):\s*([^\]]+)\]", re.IGNORECASE)
ML_EXPERIMENT_RE = re.compile(r"\b(train|model|predict|forecast|time[- ]?series|validation|test split)\b", re.IGNORECASE)
ML_METRIC_RE = re.compile(r"\b(metric|accuracy|auc|f1|precision|recall|mae|mse|rmse|mape|loss)\b", re.IGNORECASE)
ML_REGRESSION_METRIC_RE = re.compile(r"\b(mae|mse|rmse|mape|mean absolute error|mean squared error|root mean squared error)\b", re.IGNORECASE)
ML_CLASSIFICATION_METRIC_RE = re.compile(r"\b(accuracy|auc|f1|precision|recall)\b", re.IGNORECASE)
ML_CLASSIFICATION_TASK_RE = re.compile(r"\b(classif|class label|binary label|positive class|negative class|category|categories)\b", re.IGNORECASE)
ML_FORECAST_TASK_RE = re.compile(r"\b(forecast|predict|prediction|time[- ]?series|return|demand|price|value|quantity|amount)\b", re.IGNORECASE)
ML_HORIZON_RE = re.compile(r"\b(horizon|frequency|cadence|\d+\s*(?:minute|hour|day|week|month)s?|\d+\s*(?:m|h|d|w))\b", re.IGNORECASE)
ML_REPRO_RE = re.compile(r"\b(seed|random state|reproduc|version|commit|environment|dataset snapshot)\b", re.IGNORECASE)
ML_TRAIN_ONLY_PREPROCESS_RE = re.compile(r"\b(train(?:ing)?[- ]only|fit(?:ted)? on train|fit preprocessing on train)\b", re.IGNORECASE)
ML_PREPROCESS_BEFORE_SPLIT_RE = re.compile(r"\b(normaliz|standardiz|scal|preprocess)[^.\n;]*\bthen\b[^.\n;]*\bsplit\b", re.IGNORECASE)
ML_BASELINE_RE = re.compile(r"\b(baseline|benchmark|naive|persistence|last[- ]value|ablation|compare(?:d)? against)\b", re.IGNORECASE)
ML_UNCERTAINTY_RE = re.compile(r"\b(confidence intervals?|error bars?|uncertainty|standard deviation|std\.?|bootstrap|variance)\b", re.IGNORECASE)
ML_FUTURE_LABEL_LEAKAGE_RE = re.compile(
    r"\b(?:future|label|target)[^.;\n]{0,60}\b(?:features?|inputs?|predictors?|covariates?)\b|"
    r"\b(?:features?|inputs?|predictors?|covariates?)[^.;\n]{0,60}\b(?:future|label|target)\b",
    re.IGNORECASE,
)


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
    test_coverage_targets: dict[str, tuple[str, str, bool]] = {}
    item_by_id = {item.id: item for item in doc.items}
    last_requirement_item_id: str | None = None

    # Labels are document-scoped: explicit [covers:...] claims should resolve
    # even when acceptance-test sections appear before the requirement section.
    for item in doc.items:
        if section_kind_by_id.get(item.section_id) in REQUIREMENT_SECTION_KINDS:
            label_match = REQUIREMENT_LABEL_RE.search(item.raw_text)
            if label_match:
                label = _clean_requirement_label(label_match.group(1))
                requirement_label_to_item_ids.setdefault(label, []).append(item.id)

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
            test_coverage_targets[oid] = (item.span.id, item.raw_text, bool(target_item_ids))
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

    for test_id, (span_id, raw_text, has_target) in sorted(test_coverage_targets.items()):
        obligation = add_validation_obligation(
            doc,
            "acceptance-test-covers-requirement",
            test_id,
            "Every acceptance test should be linked to at least one requirement by nesting, proximity, or explicit coverage label.",
            span_id,
        )
        if has_target:
            add_check(doc, obligation, CheckStatus.PASS, "acceptance test has a requirement coverage target")
        else:
            add_check(doc, obligation, CheckStatus.UNKNOWN, "no requirement coverage target found")
            qid = stable_id("question", "orphan-acceptance-test", test_id)
            if qid not in existing_ids:
                doc.objects.append(
                    SpecObject(
                        qid,
                        Role.QUESTION_OBJECT,
                        SemanticLevel.TEMPLATE_PARSED,
                        span_id,
                        facts=[
                            ("OrphanAcceptanceTest", qid, test_id),
                            ("QuestionText", qid, f"Which requirement is covered by acceptance test '{raw_text}'?"),
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


def build_ml_methodology_validation(doc: SpecDocument) -> SpecDocument:
    """Add conservative ML/time-series methodology obligations.

    This pass does not infer model semantics. It only recognizes an ML-ish source
    by explicit words and then requires reviewable evidence for common Appendix
    N/P methodology hazards: metric declaration, horizon/frequency declaration,
    reproducibility evidence, train-only preprocessing fit scope, leakage-prone
    preprocessing order, explicit future/label leakage wording, baseline
    comparison, and uncertainty/error-bar reporting.
    """
    candidate_items = [item for item in doc.items if ML_EXPERIMENT_RE.search(item.raw_text)]
    if not candidate_items:
        return doc

    existing_ids = {obj.id for obj in doc.objects}
    first_span_id = candidate_items[0].span.id
    experiment_id = stable_id("ml-exp", doc.files[0].id if doc.files else "document")
    all_text = "\n".join(item.raw_text for item in doc.items)

    if experiment_id not in existing_ids:
        doc.objects.append(
            SpecObject(
                experiment_id,
                Role.VALIDATION_OBJECT,
                SemanticLevel.TEMPLATE_PARSED,
                first_span_id,
                facts=[("MLTimeSeriesExperiment", experiment_id), ("MethodologySignal", experiment_id, "ml-time-series-keywords")],
            )
        )
        existing_ids.add(experiment_id)

    def check_property(property: str, rationale: str, passing: bool, pass_evidence: str, unknown_evidence: str, question_text: str) -> None:
        obligation = add_validation_obligation(doc, property, experiment_id, rationale, first_span_id)
        if passing:
            add_check(doc, obligation, CheckStatus.PASS, pass_evidence)
            return
        add_check(doc, obligation, CheckStatus.UNKNOWN, unknown_evidence)
        qid = stable_id("question", "ml-methodology", property, experiment_id)
        if qid not in existing_ids:
            doc.objects.append(
                SpecObject(
                    qid,
                    Role.QUESTION_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    first_span_id,
                    facts=[
                        ("MissingMethodologyEvidence", qid, property),
                        ("QuestionText", qid, question_text),
                        ("Blocks", qid, obligation.id),
                    ],
                )
            )
            existing_ids.add(qid)

    metric_declared = bool(ML_METRIC_RE.search(all_text))
    check_property(
        "ml-evaluation-metric-declared",
        "ML/time-series experiments should declare the evaluation metric used for validation/test claims.",
        metric_declared,
        "metric-like term found in source text",
        "no evaluation metric term found",
        "Which evaluation metric will be used for validation and final test reporting?",
    )
    classification_metric = bool(ML_CLASSIFICATION_METRIC_RE.search(all_text))
    regression_metric = bool(ML_REGRESSION_METRIC_RE.search(all_text))
    classification_task = bool(ML_CLASSIFICATION_TASK_RE.search(all_text))
    forecast_task = bool(ML_FORECAST_TASK_RE.search(all_text))
    metric_task_appropriate = (
        metric_declared
        and (
            regression_metric
            or (classification_metric and classification_task)
            or (not classification_metric and not forecast_task)
        )
    )
    check_property(
        "ml-metric-task-appropriateness-reviewed",
        "Declared metrics should be reviewed for fit to the stated ML/time-series task before validation claims are trusted.",
        metric_task_appropriate,
        "declared metric appears compatible with the task wording at keyword level",
        "metric declaration is missing or classification-style metric appears on forecast/regression-like wording without task justification",
        "Is the declared metric appropriate for the prediction target and task type, or is a task-specific justification needed?",
    )
    check_property(
        "ml-horizon-or-frequency-declared",
        "Time-series prediction specs should declare a prediction horizon or data frequency before validation claims are trusted.",
        bool(ML_HORIZON_RE.search(all_text)),
        "horizon/frequency-like term found in source text",
        "no horizon or frequency term found",
        "What prediction horizon or data frequency anchors this time-series experiment?",
    )
    check_property(
        "ml-reproducibility-evidence-declared",
        "Methodology validation should preserve reproducibility evidence such as seeds, versions, commits, or dataset snapshots.",
        bool(ML_REPRO_RE.search(all_text)),
        "reproducibility-like term found in source text",
        "no reproducibility evidence term found",
        "What seed, code/data version, or environment record makes this experiment reproducible?",
    )

    train_only_preprocessing = bool(ML_TRAIN_ONLY_PREPROCESS_RE.search(all_text))
    preprocessing_before_split = bool(ML_PREPROCESS_BEFORE_SPLIT_RE.search(all_text))
    preprocessing_requires_review = preprocessing_before_split or ("normaliz" in all_text.lower() and "split" in all_text.lower())
    check_property(
        "ml-preprocessing-fit-scope-declared",
        "Preprocessing for time-series ML should state whether fitted transforms are learned on train-only data to avoid leakage.",
        train_only_preprocessing,
        "train-only preprocessing fit scope found in source text",
        "preprocessing/split wording lacks train-only fit-scope evidence" if preprocessing_requires_review else "no train-only preprocessing fit-scope evidence found",
        "Are normalization/preprocessing parameters fit on training data only, before validation/test evaluation?",
    )
    check_property(
        "ml-preprocessing-order-reviewed",
        "Specs that normalize/scale/preprocess before splitting data should be reviewed for train/test leakage before validation claims are trusted.",
        not preprocessing_before_split or train_only_preprocessing,
        "no explicit preprocess-then-split leakage pattern found, or train-only fit scope is declared",
        "preprocess-then-split wording may leak validation/test information into fitted transforms",
        "Does the preprocessing order avoid fitting transforms on validation/test or future data before the split?",
    )
    future_label_leakage = bool(ML_FUTURE_LABEL_LEAKAGE_RE.search(all_text))
    check_property(
        "ml-future-label-leakage-reviewed",
        "ML/time-series feature specifications should not use future values, labels, or targets as model inputs unless a review explains why this is not leakage.",
        not future_label_leakage,
        "no explicit future/label-as-feature leakage pattern found",
        "future/label/target wording appears in a feature/input context",
        "Do any features, inputs, predictors, or covariates include future values, labels, or targets unavailable at prediction time?",
    )
    check_property(
        "ml-baseline-comparison-declared",
        "ML/time-series validation should name a baseline, benchmark, or ablation comparator before performance claims are trusted.",
        bool(ML_BASELINE_RE.search(all_text)),
        "baseline/comparator-like term found in source text",
        "no baseline or comparator term found",
        "What baseline, benchmark, or ablation comparator will contextualize this model's reported performance?",
    )
    check_property(
        "ml-uncertainty-reporting-declared",
        "ML/time-series validation should declare uncertainty reporting such as confidence intervals, error bars, or bootstrap variance where possible.",
        bool(ML_UNCERTAINTY_RE.search(all_text)),
        "uncertainty/error-bar-like term found in source text",
        "no uncertainty or error-bar reporting term found",
        "Will final metrics include confidence intervals, error bars, bootstrap variance, or another uncertainty report?",
    )
    return doc


PASS_REGISTRY = [
    PassSpec("seed-raw-item-objects", "Wrap indexed Plain items as RawTextOnly source objects.", seed_raw_item_objects),
    PassSpec("build-concept-table", "Extract explicit concept definitions, references, external links, and unresolved-question records.", build_concept_table),
    PassSpec("build-requirement-test-coverage", "Create shallow requirement/test objects and Unknown coverage questions.", build_requirement_test_coverage),
    PassSpec("build-ml-methodology-validation", "Create conservative ML/time-series methodology obligations and questions.", build_ml_methodology_validation),
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

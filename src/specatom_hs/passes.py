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
            if at_line_start:
                if ch.isspace() and ch != "\n":
                    continue
                if ch == "-":
                    continue
                if ch == " ":
                    continue
                at_line_start = False
            if cursor == raw_index:
                return item.span.start_byte + offset
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
ML_TEMPORAL_SPLIT_RE = re.compile(r"\b(chronological|temporal|time[- ]ordered|walk[- ]forward|rolling[- ]origin|forward[- ]chaining|backtest|out[- ]of[- ]time)\b", re.IGNORECASE)
ML_RANDOM_SPLIT_RE = re.compile(r"\b(random(?:ly)? split|shuffle(?:d)? split|shuffle(?:d)? before split|stratified split|k[- ]fold|cross[- ]validation)\b", re.IGNORECASE)
ML_BASELINE_RE = re.compile(r"\b(baseline|benchmark|naive|persistence|last[- ]value|ablation|compare(?:d)? against)\b", re.IGNORECASE)
ML_NAMED_BASELINE_RE = re.compile(r"\b(benchmark|naive|persistence|last[- ]value|ablation|compare(?:d)? against\s+[^.;\n]+)\b", re.IGNORECASE)
ML_UNCERTAINTY_RE = re.compile(r"\b(confidence intervals?|error bars?|uncertainty|standard deviation|std\.?|bootstrap|variance)\b", re.IGNORECASE)
ML_NAMED_UNCERTAINTY_RE = re.compile(r"\b(confidence intervals?|error bars?|standard deviation|std\.?|bootstrap|variance)\b", re.IGNORECASE)
ML_FUTURE_LABEL_LEAKAGE_RE = re.compile(
    r"\b(?:future|label|target)[^.;\n]{0,60}\b(?:features?|inputs?|predictors?|covariates?)\b|"
    r"\b(?:features?|inputs?|predictors?|covariates?)[^.;\n]{0,60}\b(?:future|label|target)\b",
    re.IGNORECASE,
)
ML_FEATURE_INPUT_RE = re.compile(r"\b(features?|inputs?|predictors?|covariates?)\b", re.IGNORECASE)
ML_FEATURE_AVAILABILITY_RE = re.compile(
    r"\b(available at prediction time|available before prediction|known before prediction|known at prediction time|"
    r"as[- ]of|point[- ]in[- ]time|lagged|historical|prior to prediction|no future (?:data|values|features?))\b",
    re.IGNORECASE,
)
ML_FRESHNESS_SIGNAL_RE = re.compile(
    r"\b(real[- ]?time|live|stream(?:ing)?|online|current|latest|recent|fresh)\b",
    re.IGNORECASE,
)
ML_FRESHNESS_EVIDENCE_RE = re.compile(
    r"\b(freshness|staleness|max(?:imum)? age|data age|latency|as[- ]of timestamp|event time|"
    r"updated every|refreshed every|within \d+\s*(?:second|minute|hour|day)s?)\b",
    re.IGNORECASE,
)
SECURITY_PRIVACY_RE = re.compile(
    r"\b(secret|api[- ]?key|token|password|credential|pii|personal data|email address|phone number|"
    r"privacy|encrypt|auth(?:entication|orization)?|login|sign[- ]?in|api|endpoint|webhook|callback|access|permission|admin|role|delete|drop|erase|purge|"
    r"force[- ]?push|destructive)\b",
    re.IGNORECASE,
)
SECRET_SIGNAL_RE = re.compile(r"\b(secret|api[- ]?key|token|password|credential)\b", re.IGNORECASE)
SECRET_HANDLING_RE = re.compile(r"\b(secret manager|vault|environment variable|env var|redacted|not hard[- ]?coded|no plaintext|encrypted at rest)\b", re.IGNORECASE)
SECRET_LOGGING_RE = re.compile(r"\b(redacted from logs?|log redaction|not logged|never logged|no logs?|masked in logs?|scrubbed from logs?)\b", re.IGNORECASE)
SECRET_ROTATION_RE = re.compile(
    r"\b(secret rotation|rotate secrets?|key rotation|credential rotation|token rotation|password rotation|"
    r"secret expiry|credential expiry|token expiry|password expiry|revoke(?:d|s)? tokens?|credential revocation|compromise revocation)\b",
    re.IGNORECASE,
)
PII_SIGNAL_RE = re.compile(r"\b(pii|personal data|email address|phone number|user data|privacy)\b", re.IGNORECASE)
PII_HANDLING_RE = re.compile(r"\b(consent|minimi[sz]ation|retention|anonymi[sz]e|pseudonymi[sz]e|encrypt(?:ed|ion)?|delete on request|privacy review)\b", re.IGNORECASE)
PII_ENCRYPTION_SCOPE_RE = re.compile(
    r"\b(encrypt(?:ed|ion)? at rest|encrypt(?:ed|ion)? in transit|tls|https|transport encryption|"
    r"database encryption|field[- ]level encryption|key management|kms|key rotation|encryption keys?)\b",
    re.IGNORECASE,
)
PII_LAWFUL_BASIS_RE = re.compile(
    r"\b(consent|lawful basis|legal basis|contractual necessity|contract basis|legal obligation|legitimate interest|vital interest|public task)\b",
    re.IGNORECASE,
)
PII_RETENTION_DELETION_RE = re.compile(r"\b(retention(?: limit| period| policy)?|delete on request|deletion request|data deletion|right to erasure|purge after|expire after|minimi[sz]ation|data minimization)\b", re.IGNORECASE)
PII_PURPOSE_LIMITATION_RE = re.compile(
    r"\b(purpose limitation|specific purpose|limited purpose|use limitation|only used for|used only for|"
    r"not used for other purposes|secondary use review|no secondary use|compatible use)\b",
    re.IGNORECASE,
)
PII_DATA_SUBJECT_RIGHTS_RE = re.compile(
    r"\b(data subject rights?|subject access request|dsar|access request|correction request|rectification|"
    r"portability|right to object|opt[- ]out|privacy rights?)\b",
    re.IGNORECASE,
)
PII_RIGHTS_REQUEST_SIGNAL_RE = re.compile(
    r"\b(data subject rights?|subject access request|dsar|access request|correction request|rectification|"
    r"portability|right to object|opt[- ]out|privacy rights?|deletion request|delete on request|right to erasure)\b",
    re.IGNORECASE,
)
PII_RIGHTS_AUTHENTICATION_RE = re.compile(
    r"\b(identity verification|verify identity|verified identity|authenticated request|authenticated user|"
    r"account owner|authorized data subject|request authentication|proof of identity)\b",
    re.IGNORECASE,
)
PII_ACCESS_AUDIT_RE = re.compile(
    r"\b(access logs?|audit logs?|audited access|access audit|logging of access|access monitoring|"
    r"monitor(?:ed|ing) access|privacy access log)\b",
    re.IGNORECASE,
)
PII_INCIDENT_RESPONSE_RE = re.compile(
    r"\b(incident response|breach response|breach notification|data breach|security incident|"
    r"incident handling|incident runbook|notify(?:ing)? affected users?|regulator notification|"
    r"breach disclosure|incident escalation)\b",
    re.IGNORECASE,
)
DATA_CLASSIFICATION_RE = re.compile(
    r"\b(data classification|classified as|classification label|sensitivity label|confidential|restricted|public data|internal data|regulated data)\b",
    re.IGNORECASE,
)
PII_LOCATION_SIGNAL_RE = re.compile(
    r"\b(region|country|jurisdiction|residen(?:cy|ce)|location|cross[- ]border|international|eu|gdpr|ccpa|hipaa)\b",
    re.IGNORECASE,
)
PII_LOCATION_POLICY_RE = re.compile(
    r"\b(data residen(?:cy|ce)|regional storage|same[- ]region|allowed regions?|approved regions?|jurisdiction policy|"
    r"cross[- ]border transfer review|gdpr|ccpa|hipaa|standard contractual clauses|sccs)\b",
    re.IGNORECASE,
)
PII_THIRD_PARTY_SIGNAL_RE = re.compile(
    r"\b(third[- ]party|vendor|processor|subprocessor|partner|external service|share(?:d|s)? with|send(?:s)? to|export(?:s|ed)? to|upload(?:s|ed)? to)\b",
    re.IGNORECASE,
)
PII_THIRD_PARTY_POLICY_RE = re.compile(
    r"\b(data processing agreement|dpa|processor agreement|vendor review|third[- ]party review|subprocessor list|"
    r"approved vendor|data sharing agreement|purpose limitation|onward transfer|contractual controls?)\b",
    re.IGNORECASE,
)
ACCESS_SIGNAL_RE = re.compile(r"\b(auth(?:entication|orization)?|access|permission|admin|role|login|rbac)\b", re.IGNORECASE)
ACCESS_BOUNDARY_RE = re.compile(r"\b(role[- ]based|rbac|least privilege|permission check|authorize|authz|access control|admin[- ]only|deny by default)\b", re.IGNORECASE)
AUTH_SESSION_SIGNAL_RE = re.compile(r"\b(auth(?:entication)?|login|sign[- ]?in|session)\b", re.IGNORECASE)
AUTH_SESSION_MANAGEMENT_RE = re.compile(
    r"\b(mfa|multi[- ]factor|two[- ]factor|2fa|session timeout|session expiry|session expiration|idle timeout|"
    r"token expiry|token expiration|refresh token rotation|revoke sessions?|logout|reauth(?:enticate|entication))\b",
    re.IGNORECASE,
)
AUTH_ABUSE_SIGNAL_RE = re.compile(r"\b(auth(?:entication)?|login|sign[- ]?in|api|endpoint|password|token)\b", re.IGNORECASE)
AUTH_ABUSE_PROTECTION_RE = re.compile(
    r"\b(rate[- ]?limit(?:ing|s)?|throttl(?:e|ing)|brute[- ]force|credential stuffing|"
    r"account lock(?:out|ing)|login attempt limit|abuse detection|bot detection|captcha)\b",
    re.IGNORECASE,
)
API_AUTHORIZATION_SIGNAL_RE = re.compile(r"\b(api|endpoint|webhook|route|request)\b", re.IGNORECASE)
API_AUTHORIZATION_RE = re.compile(
    r"\b(authori[sz]e(?:d|s|ation)?|authz|permission checks?|scope checks?|scoped tokens?|"
    r"rbac|role[- ]based|access control|deny by default|policy enforcement)\b",
    re.IGNORECASE,
)
AUTH_TRANSPORT_PROTECTION_RE = re.compile(
    r"\b(tls|https|transport encryption|encrypted in transit|secure channel|mtls|mutual tls|certificate pinning)\b",
    re.IGNORECASE,
)
API_INPUT_SIGNAL_RE = re.compile(
    r"\b(api|endpoint|route|request|webhook)\b[^.;\n]{0,80}\b(input|payload|body|query|parameter|params|json|form|upload)\b|"
    r"\b(input|payload|body|query|parameter|params|json|form|upload)\b[^.;\n]{0,80}\b(api|endpoint|route|request|webhook)\b",
    re.IGNORECASE,
)
API_INPUT_VALIDATION_RE = re.compile(
    r"\b(input validation|validate(?:d|s)? input|payload validation|schema validation|json schema|"
    r"request schema|parameter validation|saniti[sz]e(?:d|s)?|allow[- ]?list|type check(?:s|ing)?|bounds check(?:s|ing)?)\b",
    re.IGNORECASE,
)
API_ERROR_SIGNAL_RE = re.compile(
    r"\b(api|endpoint|route|request|webhook)\b[^.;\n]{0,100}\b(error|exception|stack trace|traceback|debug|diagnostic|failure response|error response)\b|"
    r"\b(error|exception|stack trace|traceback|debug|diagnostic|failure response|error response)\b[^.;\n]{0,100}\b(api|endpoint|route|request|webhook)\b",
    re.IGNORECASE,
)
API_ERROR_SAFE_RESPONSE_RE = re.compile(
    r"\b(generic error|safe error|redacted errors?|saniti[sz]ed errors?|no stack traces?|hide stack traces?|"
    r"do not expose stack|not expose stack|no debug output|suppress debug|opaque error|error code|correlation id)\b",
    re.IGNORECASE,
)
WEBHOOK_AUTHENTICITY_SIGNAL_RE = re.compile(
    r"\b(webhook|callback|incoming request|external request|signed request)\b",
    re.IGNORECASE,
)
WEBHOOK_AUTHENTICITY_RE = re.compile(
    r"\b(hmac|signature verification|verify signatures?|signed webhook|webhook secret|request signature|"
    r"timestamp tolerance|timestamp window|replay protection|nonce|idempotency key)\b",
    re.IGNORECASE,
)
PRIVILEGE_ESCALATION_REVIEW_RE = re.compile(
    r"\b(least privilege|privilege escalation|self[- ]?grant|cannot grant (?:their|own)|separation of duties|two[- ]person|approval|audit(?:ed| log)?|admin[- ]only)\b",
    re.IGNORECASE,
)
DESTRUCTIVE_ACTION_RE = re.compile(r"\b(delete|drop|erase|purge|force[- ]?push|destructive|wipe)\b", re.IGNORECASE)
DESTRUCTIVE_SAFETY_RE = re.compile(r"\b(confirm(?:ation)?|dry[- ]run|backup|rollback|undo|soft delete|trash|audit log|approval)\b", re.IGNORECASE)

# --- Information-flow validation patterns ---
INFO_FLOW_SIGNAL_RE = re.compile(
    r"\b(input|output|consume|produce|read(?:s| from)?|write(?:s| to)?|receive(?:s| from)?|send(?:s| to)?|"
    r"depend(?:s|ency|encies)?(?:\s+on)?|source(?:s| from)?|sink|feed(?:s| into)?|flow(?:s| from| to)?|"
    r"upstream|downstream|pipeline|data flow|data dependency|ingest|emit|"
    r"circular|cycle|mutual(?:ly)? depend|feedback loop|recursive(?:ly)? depend|bidirectional)\b",
    re.IGNORECASE,
)
INPUT_DECLARATION_RE = re.compile(
    r"\b(input(?:s)?|consume(?:s)?|read(?:s)? from|receive(?:s)? from|ingest(?:s)?|"
    r"upstream(?:\s+input|\s+source|\s+data))\b[^.;\n]{0,120}",
    re.IGNORECASE,
)
OUTPUT_DECLARATION_RE = re.compile(
    r"\b(output(?:s)?|produce(?:s)?|write(?:s)? to|send(?:s)? to|sink(?:s)?|emit(?:s)?|"
    r"downstream(?:\s+output|\s+target|\s+data)?|feed(?:s)? into)\b[^.;\n]{0,120}",
    re.IGNORECASE,
)
DEPENDENCY_DIRECTION_RE = re.compile(
    r"\b(depend(?:s|ency|encies)?(?:\s+on)?|read(?:s| from)?|write(?:s| to)?|consume(?:s| from)?|"
    r"produce(?:s| for)?|receive(?:s| from)?|send(?:s| to)?|feed(?:s| into)?|"
    r"source(?:s| from)?|sink(?:s| to)?|upstream|downstream)\b",
    re.IGNORECASE,
)
TEMPORAL_AVAILABILITY_SIGNAL_RE = re.compile(
    r"\b(before|after|prior to|following|once|when|available|ready|complete(?:d)?|"
    r"finish(?:ed|es)?|then|subsequently|order|sequential|precedence)\b",
    re.IGNORECASE,
)
TEMPORAL_AVAILABILITY_EVIDENCE_RE = re.compile(
    r"\b(available before|ready before|completed before|finish(?:ed|es)? before|"
    r"point[- ]in[- ]time|as[- ]of|temporal order|causal order|execution order|"
    r"available at|ready at|available when|ready when|available once|"
    r"dependency order|topolog|ordering constraint|happens[- ]before)\b",
    re.IGNORECASE,
)
CIRCULAR_DEPENDENCY_SIGNAL_RE = re.compile(
    r"\b(circular|cycle|mutual(?:ly)? depend|feedback loop|recursive(?:ly)? depend|"
    r"mutually recursive|bidirectional)\b",
    re.IGNORECASE,
)
CIRCULAR_DEPENDENCY_EVIDENCE_RE = re.compile(
    r"\b(acyclic|no cycle|break(?:s| the)? cycle|no circular|terminates?|base case|"
    r"bounded recursion|depth limit|max depth|recursion limit)\b",
    re.IGNORECASE,
)

# Detect explicit component-level data-path edges like:
#   "The pipeline reads from the upstream source"
#   "The service consumes input from the message queue"
#   "Component A depends on component B"
# The source and target are simple noun phrases (1–2 alphabetic words).
# Stop words are filtered so conjunctions/articles are not treated as sources.
DATA_PATH_EDGE_RE = re.compile(
    r"(?:(?:The|the|A|a|An|an)\s+)?"
    r"(?P<source>\b[A-Za-z]+(?:\s+[A-Za-z]+)?\b)"
    r"\s+"
    r"(?P<verb>reads?\s+from|writes?\s+to|sends?\s+to|depends?\s+on"
    r"|consumes?\s+\w+\s+from|produces?\s+\w+\s+to)"
    r"\s+"
    r"(?:(?:the|a|an)\s+)?"
    r"(?P<target>\b[A-Za-z]+(?:\s+[A-Za-z]+)?\b)",
    re.IGNORECASE,
)
_EDGE_STOP_WORDS = frozenset({
    "and", "or", "but", "then", "if", "when", "while", "the", "a", "an",
    "is", "are", "was", "were", "be", "been", "being", "to", "from",
    "in", "on", "at", "by", "for", "with", "about", "as", "into",
    "through", "during", "before", "after", "above", "below", "up",
    "down", "of", "off", "over", "under", "that", "this", "these",
    "those", "it", "its",
})


def _normalize_direction(verb: str) -> str:
    """Normalize a matched verb phrase to a direction string.

    'reads from' -> 'reads-from', 'consumes input from' -> 'consumes-from', etc.
    """
    parts = verb.lower().split()
    return f"{parts[0]}-{parts[-1]}"


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


def build_security_privacy_validation(doc: SpecDocument) -> SpecDocument:
    """Add conservative security/privacy obligation scaffolding.

    This pass is intentionally keyword-level. It does not infer a threat model or
    approve operational behavior; when a spec mentions secrets, PII, access
    control, or destructive actions without matching safety evidence, it creates
    Unknown checks plus blocking questions.
    """
    candidate_items = [item for item in doc.items if SECURITY_PRIVACY_RE.search(item.raw_text)]
    if not candidate_items:
        return doc

    existing_ids = {obj.id for obj in doc.objects}
    first_span_id = candidate_items[0].span.id
    review_id = stable_id("secpriv", doc.files[0].id if doc.files else "document")
    all_text = "\n".join(item.raw_text for item in doc.items)

    if review_id not in existing_ids:
        doc.objects.append(
            SpecObject(
                review_id,
                Role.VALIDATION_OBJECT,
                SemanticLevel.TEMPLATE_PARSED,
                first_span_id,
                facts=[("SecurityPrivacyReview", review_id), ("SecurityPrivacySignal", review_id, "security-privacy-keywords")],
            )
        )
        existing_ids.add(review_id)

    def check_property(property: str, rationale: str, needed: bool, passing: bool, pass_evidence: str, unknown_evidence: str, question_text: str) -> None:
        obligation = add_validation_obligation(doc, property, review_id, rationale, first_span_id)
        if not needed:
            add_check(doc, obligation, CheckStatus.PASS, "no triggering signal found in source text")
            return
        if passing:
            add_check(doc, obligation, CheckStatus.PASS, pass_evidence)
            return
        add_check(doc, obligation, CheckStatus.UNKNOWN, unknown_evidence)
        qid = stable_id("question", "security-privacy", property, review_id)
        if qid not in existing_ids:
            doc.objects.append(
                SpecObject(
                    qid,
                    Role.QUESTION_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    first_span_id,
                    facts=[
                        ("MissingSecurityPrivacyEvidence", qid, property),
                        ("QuestionText", qid, question_text),
                        ("Blocks", qid, obligation.id),
                    ],
                )
            )
            existing_ids.add(qid)

    secret_signal = bool(SECRET_SIGNAL_RE.search(all_text))
    pii_signal = bool(PII_SIGNAL_RE.search(all_text))
    access_signal = bool(ACCESS_SIGNAL_RE.search(all_text))
    auth_session_signal = bool(AUTH_SESSION_SIGNAL_RE.search(all_text))
    auth_abuse_signal = bool(AUTH_ABUSE_SIGNAL_RE.search(all_text))
    api_authorization_signal = bool(API_AUTHORIZATION_SIGNAL_RE.search(all_text)) and (access_signal or auth_abuse_signal)
    webhook_authenticity_signal = bool(WEBHOOK_AUTHENTICITY_SIGNAL_RE.search(all_text))
    api_input_signal = bool(API_INPUT_SIGNAL_RE.search(all_text))
    api_error_signal = bool(API_ERROR_SIGNAL_RE.search(all_text))
    destructive_signal = bool(DESTRUCTIVE_ACTION_RE.search(all_text))

    check_property(
        "security-secrets-handling-reviewed",
        "Specs that mention secrets, tokens, passwords, or credentials should state how they are stored/redacted instead of hard-coded or exposed.",
        secret_signal,
        bool(SECRET_HANDLING_RE.search(all_text)),
        "secret-handling evidence found in source text",
        "secret/credential wording lacks storage, redaction, or no-hardcoding evidence",
        "How are secrets, tokens, passwords, or credentials stored, redacted, and kept out of source/plaintext?",
    )
    check_property(
        "security-secret-log-exposure-reviewed",
        "Specs that mention secrets, tokens, passwords, or credentials should state whether those values are redacted, masked, or excluded from logs.",
        secret_signal,
        bool(SECRET_LOGGING_RE.search(all_text)),
        "secret log-exposure evidence found in source text",
        "secret/credential wording lacks redaction, masking, or no-logging evidence",
        "How are secrets, tokens, passwords, or credentials kept out of logs and diagnostics?",
    )
    check_property(
        "security-credential-rotation-reviewed",
        "Specs that mention secrets, tokens, passwords, or credentials should state rotation, expiry, or revocation evidence before credential-lifecycle claims are trusted.",
        secret_signal,
        bool(SECRET_ROTATION_RE.search(all_text)),
        "secret/credential rotation, expiry, or revocation evidence found in source text",
        "secret/credential wording lacks rotation, expiry, or revocation evidence",
        "What rotation, expiry, or revocation rule governs secrets, tokens, passwords, or credentials?",
    )
    check_property(
        "privacy-pii-handling-reviewed",
        "Specs that mention PII or user personal data should preserve privacy evidence such as consent, minimization, retention, anonymization, or encryption.",
        pii_signal,
        bool(PII_HANDLING_RE.search(all_text)),
        "PII/privacy-handling evidence found in source text",
        "PII/privacy wording lacks consent, minimization, retention, anonymization, or encryption evidence",
        "What privacy controls govern PII/personal data collection, retention, access, deletion, and protection?",
    )
    check_property(
        "privacy-data-classification-declared",
        "Specs that mention PII or personal data should declare a data/sensitivity classification before downstream policy or access claims are trusted.",
        pii_signal,
        bool(DATA_CLASSIFICATION_RE.search(all_text)),
        "data-classification evidence found in source text",
        "PII/privacy wording lacks an explicit data or sensitivity classification",
        "What data classification or sensitivity label applies to the personal data in this spec?",
    )
    check_property(
        "privacy-encryption-scope-reviewed",
        "Specs that mention PII or personal data should state encryption scope, transport protection, or key-management evidence before downstream protection claims are trusted.",
        pii_signal,
        bool(PII_ENCRYPTION_SCOPE_RE.search(all_text)),
        "PII encryption-scope/key-management evidence found in source text",
        "PII/privacy wording lacks encryption-at-rest, transport-encryption, or key-management scope evidence",
        "What encryption scope, transport protection, or key-management policy protects the personal data?",
    )
    check_property(
        "privacy-lawful-basis-reviewed",
        "Specs that mention PII or personal data should state lawful-basis or consent evidence before downstream collection/use claims are trusted.",
        pii_signal,
        bool(PII_LAWFUL_BASIS_RE.search(all_text)),
        "PII lawful-basis/consent evidence found in source text",
        "PII/privacy wording lacks lawful-basis, legal-basis, consent, contract, legal-obligation, or legitimate-interest evidence",
        "What lawful basis, consent, contract basis, legal obligation, or legitimate interest authorizes this personal-data use?",
    )
    check_property(
        "privacy-retention-deletion-reviewed",
        "Specs that mention PII or personal data should state retention or deletion/minimization evidence before downstream privacy claims are trusted.",
        pii_signal,
        bool(PII_RETENTION_DELETION_RE.search(all_text)),
        "PII retention/deletion evidence found in source text",
        "PII/privacy wording lacks retention, deletion, erasure, expiry, or minimization evidence",
        "What retention period, deletion/erasure behavior, or minimization rule governs the personal data?",
    )
    check_property(
        "privacy-purpose-limitation-reviewed",
        "Specs that mention PII or personal data should state purpose-limitation evidence before downstream collection/use claims are trusted.",
        pii_signal,
        bool(PII_PURPOSE_LIMITATION_RE.search(all_text)),
        "PII purpose-limitation evidence found in source text",
        "PII/privacy wording lacks purpose-limitation, use-limitation, or secondary-use review evidence",
        "What specific purpose, use limitation, or secondary-use review governs the personal data?",
    )
    check_property(
        "privacy-data-subject-rights-reviewed",
        "Specs that mention PII or personal data should state data-subject rights handling before downstream privacy claims are trusted.",
        pii_signal,
        bool(PII_DATA_SUBJECT_RIGHTS_RE.search(all_text)),
        "PII data-subject rights evidence found in source text",
        "PII/privacy wording lacks data-subject access, correction, portability, opt-out, or rights-request evidence",
        "How can data subjects exercise access, correction/rectification, portability, objection, opt-out, or related privacy rights?",
    )
    rights_request_signal = bool(PII_RIGHTS_REQUEST_SIGNAL_RE.search(all_text))
    check_property(
        "privacy-rights-request-authentication-reviewed",
        "Specs that mention PII/personal data together with data-subject rights, access, deletion, opt-out, or erasure requests should state identity/authentication evidence before rights workflows are trusted.",
        pii_signal and rights_request_signal,
        bool(PII_RIGHTS_AUTHENTICATION_RE.search(all_text)),
        "PII rights-request authentication evidence found in source text",
        "PII/privacy rights or deletion request wording lacks identity verification or request-authentication evidence",
        "How is the requester authenticated or identity-verified before fulfilling personal-data access, deletion, correction, portability, or opt-out requests?",
    )
    check_property(
        "privacy-pii-access-audit-reviewed",
        "Specs that mention PII/personal data together with access/admin/role wording should state access audit, logging, or monitoring evidence before access-control privacy claims are trusted.",
        pii_signal and access_signal,
        bool(PII_ACCESS_AUDIT_RE.search(all_text)),
        "PII access audit/logging evidence found in source text",
        "PII/privacy access wording lacks access audit, logging, or monitoring evidence",
        "How is access to personal data logged, audited, or monitored for privacy review?",
    )
    check_property(
        "privacy-incident-response-reviewed",
        "Specs that mention PII or personal data should state incident-response or breach-notification evidence before downstream privacy claims are trusted.",
        pii_signal,
        bool(PII_INCIDENT_RESPONSE_RE.search(all_text)),
        "PII incident-response/breach-notification evidence found in source text",
        "PII/privacy wording lacks incident-response, breach-notification, or escalation evidence",
        "What incident-response, breach-notification, regulator-notification, or escalation process applies if personal data is exposed?",
    )
    location_signal = bool(PII_LOCATION_SIGNAL_RE.search(all_text))
    check_property(
        "privacy-data-residency-reviewed",
        "Specs that mention PII/personal data together with region, country, jurisdiction, residency, or cross-border wording should state a data-residency or transfer policy before downstream compliance claims are trusted.",
        pii_signal and location_signal,
        bool(PII_LOCATION_POLICY_RE.search(all_text)),
        "PII data-residency/transfer policy evidence found in source text",
        "PII/privacy wording mentions location, region, country, jurisdiction, or cross-border context without residency/transfer policy evidence",
        "What data-residency, regional storage, jurisdiction, or cross-border transfer policy governs the personal data?",
    )
    third_party_signal = bool(PII_THIRD_PARTY_SIGNAL_RE.search(all_text))
    check_property(
        "privacy-third-party-sharing-reviewed",
        "Specs that mention PII/personal data together with vendors, processors, partners, external services, exports, uploads, or sharing should state third-party data-sharing policy evidence before downstream privacy claims are trusted.",
        pii_signal and third_party_signal,
        bool(PII_THIRD_PARTY_POLICY_RE.search(all_text)),
        "PII third-party sharing/processor policy evidence found in source text",
        "PII/privacy wording mentions a third party, vendor, processor, partner, external service, export, upload, or sharing without data-sharing/processor policy evidence",
        "What vendor/processor review, DPA, subprocessor list, purpose limitation, or data-sharing agreement governs the personal data?",
    )
    check_property(
        "security-access-boundary-declared",
        "Specs that mention authentication, authorization, roles, admins, or permissions should declare an access-control boundary.",
        access_signal,
        bool(ACCESS_BOUNDARY_RE.search(all_text)),
        "access-boundary evidence found in source text",
        "access/auth/role wording lacks a declared permission or boundary rule",
        "Which roles or permissions may perform the protected action, and what is denied by default?",
    )
    check_property(
        "security-privilege-escalation-reviewed",
        "Specs that mention authentication, authorization, roles, admins, or permissions should review privilege-escalation controls before admin/access claims are trusted.",
        access_signal,
        bool(PRIVILEGE_ESCALATION_REVIEW_RE.search(all_text)),
        "privilege-escalation review evidence found in source text",
        "access/auth/role wording lacks least-privilege, approval, audit, or self-grant prevention evidence",
        "How are privilege escalation and self-granted/admin permissions prevented, approved, or audited?",
    )
    check_property(
        "security-session-management-reviewed",
        "Specs that mention authentication, login, sign-in, or sessions should state session-management evidence such as MFA, timeouts, expiry, revocation, logout, refresh-token rotation, or reauthentication.",
        auth_session_signal,
        bool(AUTH_SESSION_MANAGEMENT_RE.search(all_text)),
        "authentication/session-management evidence found in source text",
        "auth/login/session wording lacks MFA, timeout, expiry, revocation, logout, refresh-token rotation, or reauthentication evidence",
        "What MFA, session timeout/expiry, revocation/logout, refresh-token rotation, or reauthentication rule governs authenticated sessions?",
    )
    check_property(
        "security-auth-abuse-protection-reviewed",
        "Specs that mention authentication, login, API endpoints, passwords, or tokens should state abuse-protection evidence such as rate limiting, throttling, brute-force protection, lockouts, or abuse/bot detection.",
        auth_abuse_signal,
        bool(AUTH_ABUSE_PROTECTION_RE.search(all_text)),
        "authentication/API abuse-protection evidence found in source text",
        "auth/login/API/password/token wording lacks rate-limit, throttling, brute-force, lockout, or abuse-detection evidence",
        "What rate limit, throttling, brute-force protection, lockout, or abuse/bot-detection rule protects this authentication/API surface?",
    )
    check_property(
        "security-api-authorization-reviewed",
        "Specs that mention API endpoints/routes/requests together with authentication or access-control wording should state authorization/scope evidence before endpoint access claims are trusted.",
        api_authorization_signal,
        bool(API_AUTHORIZATION_RE.search(all_text)),
        "API authorization/scope evidence found in source text",
        "API endpoint/request wording lacks authorization, permission, scope, RBAC, or deny-by-default evidence",
        "What authorization, permission, token-scope, RBAC, or policy-enforcement rule protects each API endpoint or request?",
    )
    check_property(
        "security-auth-transport-protection-reviewed",
        "Specs that mention authentication, API endpoints, passwords, or tokens should state transport-protection evidence such as TLS, HTTPS, mTLS, or an encrypted secure channel.",
        auth_abuse_signal,
        bool(AUTH_TRANSPORT_PROTECTION_RE.search(all_text)),
        "authentication/API transport-protection evidence found in source text",
        "auth/login/API/password/token wording lacks TLS, HTTPS, mTLS, or secure-channel evidence",
        "What TLS, HTTPS, mTLS, certificate, or secure-channel rule protects credentials and authenticated API traffic in transit?",
    )
    check_property(
        "security-api-input-validation-reviewed",
        "Specs that mention API/webhook requests together with input, payload, body, query, parameter, JSON, form, or upload wording should state input validation evidence before accepting request data.",
        api_input_signal,
        bool(API_INPUT_VALIDATION_RE.search(all_text)),
        "API/request input-validation evidence found in source text",
        "API/webhook request input wording lacks validation, schema, sanitization, allow-list, type-check, or bounds-check evidence",
        "What schema, validation, sanitization, allow-list, type-check, or bounds-check rule constrains inbound API/webhook inputs?",
    )
    check_property(
        "security-webhook-request-authenticity-reviewed",
        "Specs that mention webhooks, callbacks, or incoming external requests should state request-authenticity and replay-protection evidence before accepting inbound events.",
        webhook_authenticity_signal,
        bool(WEBHOOK_AUTHENTICITY_RE.search(all_text)),
        "webhook/request authenticity evidence found in source text",
        "webhook/callback/external-request wording lacks signature, HMAC, nonce, timestamp-window, or replay-protection evidence",
        "What signature verification, HMAC/webhook secret, nonce, timestamp-window, or replay-protection rule authenticates inbound webhook/callback requests?",
    )
    check_property(
        "security-api-error-disclosure-reviewed",
        "Specs that mention API/webhook errors, exceptions, stack traces, tracebacks, debug output, or diagnostic failure responses should state safe error-disclosure evidence before exposing responses.",
        api_error_signal,
        bool(API_ERROR_SAFE_RESPONSE_RE.search(all_text)),
        "API/webhook safe error-disclosure evidence found in source text",
        "API/webhook error or diagnostic wording lacks generic/redacted/sanitized error-response evidence",
        "What generic, redacted, sanitized, opaque, or correlation-ID based error response prevents stack traces, debug details, secrets, or internals from leaking?",
    )
    check_property(
        "security-destructive-action-safety-reviewed",
        "Specs that mention destructive actions should state safety mechanisms such as confirmation, dry-run, backup, rollback, soft-delete, audit log, or approval.",
        destructive_signal,
        bool(DESTRUCTIVE_SAFETY_RE.search(all_text)),
        "destructive-action safety evidence found in source text",
        "destructive-action wording lacks confirmation, dry-run, backup, rollback, audit, or approval evidence",
        "What safety mechanism prevents accidental or unauthorized destructive action?",
    )
    return doc



def build_information_flow_validation(doc: SpecDocument) -> SpecDocument:
    """Add conservative information-flow and temporal-availability obligations.

    This pass is intentionally keyword-level. It detects data-flow wording
    (inputs, outputs, dependencies, sources, sinks, pipelines) and creates
    Unknown checks plus blocking questions when temporal availability or
    dependency-direction evidence is missing. It does not infer actual data
    paths, execute graph analysis, or approve operational behavior.
    """
    candidate_items = [item for item in doc.items if INFO_FLOW_SIGNAL_RE.search(item.raw_text)]
    if not candidate_items:
        return doc

    existing_ids = {obj.id for obj in doc.objects}
    first_span_id = candidate_items[0].span.id
    review_id = stable_id("infoflow", doc.files[0].id if doc.files else "document")
    all_text = "\n".join(item.raw_text for item in doc.items)
    item_by_id = {item.id: item for item in doc.items}
    file_text = {plain_file.id: plain_file.text for plain_file in doc.files}
    span_ids = {span.id for span in doc.spans}

    def raw_index_to_source_offset(item, raw_index: int) -> int:
        """Map an index in an item's normalized raw text back to source bytes."""
        segment = file_text[item.file_id][item.span.start_byte:item.span.end_byte]
        cursor = 0
        at_line_start = True
        for offset, ch in enumerate(segment):
            if at_line_start:
                if ch.isspace() and ch != "\n":
                    continue
                if ch == "-":
                    continue
                if ch == " ":
                    continue
                at_line_start = False
            if cursor == raw_index:
                return item.span.start_byte + offset
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

    def exact_match_span(item, match_start: int, match_end: int) -> str:
        """Create or reuse an exact SourceSpan for a regex match in item.raw_text."""
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

    if review_id not in existing_ids:
        doc.objects.append(
            SpecObject(
                review_id,
                Role.VALIDATION_OBJECT,
                SemanticLevel.TEMPLATE_PARSED,
                first_span_id,
                facts=[("InformationFlowReview", review_id), ("InformationFlowSignal", review_id, "information-flow-keywords")],
            )
        )
        existing_ids.add(review_id)

    def check_property(property: str, rationale: str, needed: bool, passing: bool, pass_evidence: str, unknown_evidence: str, question_text: str) -> None:
        obligation = add_validation_obligation(doc, property, review_id, rationale, first_span_id)
        if not needed:
            add_check(doc, obligation, CheckStatus.PASS, "no triggering signal found in source text")
            return
        if passing:
            add_check(doc, obligation, CheckStatus.PASS, pass_evidence)
            return
        add_check(doc, obligation, CheckStatus.UNKNOWN, unknown_evidence)
        qid = stable_id("question", "information-flow", property, review_id)
        if qid not in existing_ids:
            doc.objects.append(
                SpecObject(
                    qid,
                    Role.QUESTION_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    first_span_id,
                    facts=[
                        ("MissingInformationFlowEvidence", qid, property),
                        ("QuestionText", qid, question_text),
                        ("Blocks", qid, obligation.id),
                    ],
                )
            )
            existing_ids.add(qid)

    input_signal = bool(INPUT_DECLARATION_RE.search(all_text))
    output_signal = bool(OUTPUT_DECLARATION_RE.search(all_text))
    dependency_signal = bool(DEPENDENCY_DIRECTION_RE.search(all_text))
    temporal_signal = bool(TEMPORAL_AVAILABILITY_SIGNAL_RE.search(all_text))
    circular_signal = bool(CIRCULAR_DEPENDENCY_SIGNAL_RE.search(all_text))

    check_property(
        "information-flow-inputs-declared",
        "Specs that mention data flows, pipelines, or dependencies should explicitly declare what inputs are consumed or read.",
        input_signal or dependency_signal,
        input_signal,
        "input/consume/read/source wording found in source text",
        "data-flow or dependency wording lacks explicit input/consume/read/source declaration",
        "What specific inputs does this component or pipeline consume, read, or receive from upstream sources?",
    )
    check_property(
        "information-flow-outputs-declared",
        "Specs that mention data flows, pipelines, or dependencies should explicitly declare what outputs are produced or written.",
        output_signal or dependency_signal,
        output_signal,
        "output/produce/write/sink/emit wording found in source text",
        "data-flow or dependency wording lacks explicit output/produce/write/sink/emit declaration",
        "What specific outputs does this component or pipeline produce, write, or send to downstream consumers?",
    )
    check_property(
        "information-flow-dependency-direction-declared",
        "Specs that mention dependencies between components should state the direction of data flow (which component reads from or writes to which).",
        dependency_signal,
        bool(DEPENDENCY_DIRECTION_RE.search(all_text)),
        "dependency-direction wording (depends on, reads from, writes to, consumes from, produces for) found in source text",
        "dependency wording lacks explicit direction (depends on, reads from, writes to, consumes from, produces for)",
        "What is the direction of the data dependency between these components — which component reads from or writes to which?",
    )
    check_property(
        "information-flow-temporal-availability-reviewed",
        "Specs with data-flow or dependency wording should state temporal availability assumptions: inputs are available before outputs are needed, or execution order is declared.",
        dependency_signal or (input_signal and output_signal),
        bool(TEMPORAL_AVAILABILITY_EVIDENCE_RE.search(all_text)) or not temporal_signal,
        "temporal availability/ordering evidence found, or no temporal-ordering signal is present",
        "data-flow wording with temporal-ordering signal lacks explicit availability, ordering, or happens-before evidence",
        "Are all inputs available before outputs are needed? What execution order or happens-before constraint applies to this data flow?",
    )
    check_property(
        "information-flow-circular-dependency-reviewed",
        "Specs that mention circular dependencies, cycles, mutual dependencies, or feedback loops should state termination or acyclicity evidence.",
        circular_signal,
        bool(CIRCULAR_DEPENDENCY_EVIDENCE_RE.search(all_text)),
        "circular-dependency termination or acyclicity evidence found in source text",
        "circular/recursive dependency wording lacks termination, base-case, depth-limit, or acyclicity evidence",
        "What termination condition, base case, depth limit, or acyclicity proof prevents this circular or recursive dependency from causing deadlock or infinite recursion?",
    )

    # --- Component-level data-path edge extraction ---
    # Extract explicit edges like "pipeline reads from upstream source" and
    # create DataFlowEdge atoms. This is conservative: it does not infer edges
    # from vague wording like "data flows from one component to another".
    edges: list[tuple[str, str, str, str, str]] = []  # (source, target, direction, item_id, span_id)
    for item in candidate_items:
        for match in DATA_PATH_EDGE_RE.finditer(item.raw_text):
            source = match.group("source").strip().lower()
            target = match.group("target").strip().lower()
            if source in _EDGE_STOP_WORDS or target in _EDGE_STOP_WORDS:
                continue
            direction = _normalize_direction(match.group("verb"))
            edges.append((source, target, direction, item.id, exact_match_span(item, match.start(), match.end())))

    # Emit DataFlowEdge atoms for each extracted edge.
    # Each edge carries the exact source span of the matched edge phrase, not
    # merely the first candidate item or whole item, for precise provenance.
    for source, target, direction, item_id, edge_span_id in edges:
        edge_id = stable_id("edge", source, target, direction, item_id)
        if edge_id not in existing_ids:
            doc.objects.append(
                SpecObject(
                    edge_id,
                    Role.VALIDATION_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    edge_span_id,
                    facts=[
                        ("DataFlowEdge", edge_id, source, target, direction),
                    ],
                )
            )
            existing_ids.add(edge_id)

    # Data-path declaration check: Pass when at least one explicit component-level
    # edge is found; Unknown when only vague data-flow wording exists.
    data_path_obligation = add_validation_obligation(
        doc,
        "information-flow-data-path-declared",
        review_id,
        "Specs that mention data flows or dependencies should declare explicit component-level data paths, not just vague 'data flows' or 'pipeline' wording.",
        first_span_id,
    )
    if edges:
        edge_summary = "; ".join(f"{s} {d} {t}" for s, t, d, _item, _span in edges)
        add_check(doc, data_path_obligation, CheckStatus.PASS, f"explicit data-path edges found: {edge_summary}")
    else:
        add_check(doc, data_path_obligation, CheckStatus.UNKNOWN, "data-flow or dependency wording found but no explicit component-level data-path edges extracted")
        qid = stable_id("question", "information-flow", "information-flow-data-path-declared", review_id)
        if qid not in existing_ids:
            doc.objects.append(
                SpecObject(
                    qid,
                    Role.QUESTION_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    first_span_id,
                    facts=[
                        ("MissingInformationFlowEvidence", qid, "information-flow-data-path-declared"),
                        ("QuestionText", qid, "What are the explicit component-level data paths? Which component reads from or writes to which?"),
                        ("Blocks", qid, data_path_obligation.id),
                    ],
                )
            )
            existing_ids.add(qid)

    # --- Duplicate/parallel edge detection ---
    # Repeated declarations of the same normalized source→target edge may be
    # intentional emphasis, but can also indicate copy/paste ambiguity or
    # multiple unsynchronized versions of the same data path.  Keep this as a
    # conservative review obligation instead of deduplicating the evidence away.
    DUPLICATE_EDGE_ACK_RE = re.compile(
        r"\b(duplicate(?:d)?|repeated|parallel|same edge|same data path|"
        r"multiple declarations|intentionally repeated|canonical data path)\b",
        re.IGNORECASE,
    )
    edge_counts: dict[tuple[str, str, str], int] = {}
    for source, target, direction, _item_id, _span_id in edges:
        key = (source, target, direction)
        edge_counts[key] = edge_counts.get(key, 0) + 1
    duplicate_edges = sorted((source, target, direction, count) for (source, target, direction), count in edge_counts.items() if count > 1)

    duplicate_edge_obligation = add_validation_obligation(
        doc,
        "information-flow-duplicate-edge-reviewed",
        review_id,
        "Specs with repeated declarations of the same component-level data-path edge should state whether the duplication is intentional or should be consolidated.",
        first_span_id,
    )
    if not duplicate_edges:
        add_check(doc, duplicate_edge_obligation, CheckStatus.PASS, "no duplicate component-level data-path edges detected")
    elif DUPLICATE_EDGE_ACK_RE.search(all_text):
        summary = "; ".join(f"{s} {d} {t} ({n} declarations)" for s, t, d, n in duplicate_edges)
        add_check(doc, duplicate_edge_obligation, CheckStatus.PASS, f"duplicate data-path declarations acknowledged in source text: {summary}")
    else:
        summary = "; ".join(f"{s} {d} {t} ({n} declarations)" for s, t, d, n in duplicate_edges)
        add_check(doc, duplicate_edge_obligation, CheckStatus.UNKNOWN, f"duplicate data-path declarations detected but not acknowledged: {summary}")
        qid = stable_id("question", "information-flow", "information-flow-duplicate-edge-reviewed", review_id)
        if qid not in existing_ids:
            doc.objects.append(
                SpecObject(
                    qid,
                    Role.QUESTION_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    first_span_id,
                    facts=[
                        ("MissingInformationFlowEvidence", qid, "information-flow-duplicate-edge-reviewed"),
                        ("QuestionText", qid, f"The same component-level data-path edge is declared multiple times ({summary}). Is this intentional repetition, a parallel channel, or should the declarations be consolidated?"),
                        ("Blocks", qid, duplicate_edge_obligation.id),
                    ],
                )
            )
            existing_ids.add(qid)

    # --- Self-dependency detection ---
    # A direct edge from a component to itself is a degenerate one-node cycle.
    # Flag it separately from the broader graph cycle detector so reviewers get
    # a crisp question about whether the self-edge is intentional stateful
    # feedback, recursion, or simply a mistaken dependency declaration.
    SELF_DEPENDENCY_ACK_RE = re.compile(
        r"\b(self[- ]?dependency|self[- ]?loop|self[- ]?edge|recursive|recursion|feedback loop|fixed point|iteration)\b",
        re.IGNORECASE,
    )
    self_dependencies = sorted({source for source, target, _direction, _item_id, _span_id in edges if source == target})
    self_dependency_obligation = add_validation_obligation(
        doc,
        "information-flow-self-dependency-reviewed",
        review_id,
        "Specs with a component-level data-path edge from a component to itself should explicitly state whether the self-dependency is intentional and how it terminates or stabilizes.",
        first_span_id,
    )
    if not self_dependencies:
        add_check(doc, self_dependency_obligation, CheckStatus.PASS, "no self-dependency edges detected")
    elif SELF_DEPENDENCY_ACK_RE.search(all_text):
        summary = ", ".join(self_dependencies)
        add_check(doc, self_dependency_obligation, CheckStatus.PASS, f"self-dependency acknowledged in source text: {summary}")
    else:
        summary = ", ".join(self_dependencies)
        add_check(doc, self_dependency_obligation, CheckStatus.UNKNOWN, f"self-dependency edge(s) detected but not acknowledged: {summary}")
        qid = stable_id("question", "information-flow", "information-flow-self-dependency-reviewed", review_id)
        if qid not in existing_ids:
            doc.objects.append(
                SpecObject(
                    qid,
                    Role.QUESTION_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    first_span_id,
                    facts=[
                        ("MissingInformationFlowEvidence", qid, "information-flow-self-dependency-reviewed"),
                        ("QuestionText", qid, f"The following component(s) have data-path edges to themselves ({summary}). Is this intentional recursion/feedback/state update? What termination, fixed-point, or stability condition applies?"),
                        ("Blocks", qid, self_dependency_obligation.id),
                    ],
                )
            )
            existing_ids.add(qid)

    # --- Transitive dependency chain detection ---
    # Build adjacency list from extracted edges and detect transitive chains:
    # if A→B and B→C exist, then A transitively depends on C.  If the spec
    # text acknowledges transitivity (e.g. "transitive", "indirect", "through",
    # "via", "chained"), the obligation passes; otherwise it becomes Unknown.
    TRANSITIVE_ACK_RE = re.compile(
        r"\b(transitive(?:ly)?|indirect(?:ly)?|through|via|chained?|intermediary)\b",
        re.IGNORECASE,
    )
    adjacency: dict[str, set[str]] = {}
    for source, target, _direction, _item_id, _span_id in edges:
        adjacency.setdefault(source, set()).add(target)

    transitive_pairs: list[tuple[str, str]] = []
    for source in adjacency:
        # BFS/DFS to find nodes reachable in 2+ hops from `source`.
        visited: set[str] = set()
        frontier = set(adjacency[source])
        hops = 0
        while frontier and hops < 10:  # safety bound
            hops += 1
            next_frontier: set[str] = set()
            for node in frontier:
                if node in visited:
                    continue
                visited.add(node)
                for neighbour in adjacency.get(node, set()):
                    if neighbour not in visited and neighbour not in adjacency[source]:
                        transitive_pairs.append((source, neighbour))
                    next_frontier.add(neighbour)
            frontier = next_frontier

    # Deduplicate transitive pairs.
    transitive_pairs = list(dict.fromkeys(transitive_pairs))

    transitive_obligation = add_validation_obligation(
        doc,
        "information-flow-transitive-dependency-reviewed",
        review_id,
        "Specs with explicit data-path edges that imply transitive dependencies (A→B and B→C implies A→C) should acknowledge or review those transitive chains.",
        first_span_id,
    )
    if not transitive_pairs:
        add_check(doc, transitive_obligation, CheckStatus.PASS, "no transitive dependency chains detected from extracted edges")
    elif TRANSITIVE_ACK_RE.search(all_text):
        chain_summary = "; ".join(f"{s} → {t}" for s, t in transitive_pairs)
        add_check(doc, transitive_obligation, CheckStatus.PASS, f"transitive dependency chains acknowledged in source text: {chain_summary}")
    else:
        chain_summary = "; ".join(f"{s} → {t}" for s, t in transitive_pairs)
        add_check(doc, transitive_obligation, CheckStatus.UNKNOWN, f"transitive dependency chains detected but not acknowledged in source text: {chain_summary}")
        qid = stable_id("question", "information-flow", "information-flow-transitive-dependency-reviewed", review_id)
        if qid not in existing_ids:
            doc.objects.append(
                SpecObject(
                    qid,
                    Role.QUESTION_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    first_span_id,
                    facts=[
                        ("MissingInformationFlowEvidence", qid, "information-flow-transitive-dependency-reviewed"),
                        ("QuestionText", qid, f"The following transitive dependencies are implied by the declared data paths ({chain_summary}). Are these transitive chains intended and reviewed?"),
                        ("Blocks", qid, transitive_obligation.id),
                    ],
                )
            )
            existing_ids.add(qid)

    # --- Graph-based cycle detection from extracted DataFlowEdge atoms ---
    # Detect actual cycles in the directed graph (A→B and B→A, or A→B→C→A)
    # using DFS with white/gray/black coloring.  This is stronger than the
    # keyword-based circular-dependency check because it finds cycles that
    # the spec text may not mention at all.
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {node: WHITE for node in adjacency}
    cycles: list[list[str]] = []

    def _dfs_cycle(node: str, path: list[str]) -> None:
        color[node] = GRAY
        path.append(node)
        for neighbor in adjacency.get(node, set()):
            if color.get(neighbor, WHITE) == GRAY:
                # Found a back edge → cycle.  Extract the cycle path.
                cycle_start = path.index(neighbor)
                cycles.append(path[cycle_start:] + [neighbor])
            elif color.get(neighbor, WHITE) == WHITE:
                _dfs_cycle(neighbor, path)
        path.pop()
        color[node] = BLACK

    for node in list(adjacency):
        if color[node] == WHITE:
            _dfs_cycle(node, [])

    # Deduplicate cycles by their sorted node set.
    seen_cycle_keys: set[tuple[str, ...]] = set()
    unique_cycles: list[list[str]] = []
    for cycle in cycles:
        key = tuple(sorted(cycle))
        if key not in seen_cycle_keys:
            seen_cycle_keys.add(key)
            unique_cycles.append(cycle)

    cycle_obligation = add_validation_obligation(
        doc,
        "information-flow-cycle-detected",
        review_id,
        "Specs with explicit data-path edges that form a cycle (A→B→A or longer) should acknowledge or review the cycle and state termination/safety evidence.",
        first_span_id,
    )
    if not unique_cycles:
        add_check(doc, cycle_obligation, CheckStatus.PASS, "no cycles detected in extracted data-path graph")
    else:
        cycle_summaries = [" → ".join(cycle) for cycle in unique_cycles]
        summary = "; ".join(cycle_summaries)
        add_check(doc, cycle_obligation, CheckStatus.UNKNOWN, f"cycle(s) detected in extracted data-path graph: {summary}")
        qid = stable_id("question", "information-flow", "information-flow-cycle-detected", review_id)
        if qid not in existing_ids:
            doc.objects.append(
                SpecObject(
                    qid,
                    Role.QUESTION_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    first_span_id,
                    facts=[
                        ("MissingInformationFlowEvidence", qid, "information-flow-cycle-detected"),
                        ("QuestionText", qid, f"The following cycle(s) are detected in the declared data paths ({summary}). Are these cycles intended? What termination condition, deadlock prevention, or feedback-control mechanism ensures safe operation?"),
                        ("Blocks", qid, cycle_obligation.id),
                    ],
                )
            )
            existing_ids.add(qid)

    # --- Fan-out / fan-in concentration detection ---
    # When a component has many outgoing edges (high fan-out) it is a potential
    # bottleneck or single-point-of-failure.  When a component has many incoming
    # edges (high fan-in) it is a critical shared dependency.  Both situations
    # deserve explicit review; specs that don't acknowledge the concentration
    # produce Unknown blocking questions.
    FAN_THRESHOLD = 3  # minimum degree to trigger concentration review
    FAN_ACK_RE = re.compile(
        r"\b(fan[- ]?out|fan[- ]?in|bottleneck|single point of failure|spof|"
        r"critical (?:dependency|component|path)|shared dependency|"
        r"hotspot|hot[- ]?spot|concentration|coupled|tight(?:ly)? coupled)\b",
        re.IGNORECASE,
    )

    out_degree: dict[str, int] = {}
    in_degree: dict[str, int] = {}
    for source, target, _direction, _item_id, _span_id in edges:
        out_degree[source] = out_degree.get(source, 0) + 1
        in_degree[target] = in_degree.get(target, 0) + 1

    high_fan_out = sorted(node for node, deg in out_degree.items() if deg >= FAN_THRESHOLD)
    high_fan_in = sorted(node for node, deg in in_degree.items() if deg >= FAN_THRESHOLD)

    fan_out_obligation = add_validation_obligation(
        doc,
        "information-flow-fan-out-reviewed",
        review_id,
        "Components with high fan-out (many downstream dependents) are potential bottlenecks or single-points-of-failure and should be reviewed.",
        first_span_id,
    )
    if not high_fan_out:
        add_check(doc, fan_out_obligation, CheckStatus.PASS, f"no components with fan-out >= {FAN_THRESHOLD}")
    elif FAN_ACK_RE.search(all_text):
        summary = ", ".join(f"{node} ({out_degree[node]})" for node in high_fan_out)
        add_check(doc, fan_out_obligation, CheckStatus.PASS, f"high fan-out acknowledged in source text: {summary}")
    else:
        summary = ", ".join(f"{node} ({out_degree[node]})" for node in high_fan_out)
        add_check(doc, fan_out_obligation, CheckStatus.UNKNOWN, f"high fan-out detected but not acknowledged: {summary}")
        qid = stable_id("question", "information-flow", "information-flow-fan-out-reviewed", review_id)
        if qid not in existing_ids:
            doc.objects.append(
                SpecObject(
                    qid,
                    Role.QUESTION_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    first_span_id,
                    facts=[
                        ("MissingInformationFlowEvidence", qid, "information-flow-fan-out-reviewed"),
                        ("QuestionText", qid, f"The following components have high fan-out ({summary}). Are these bottlenecks or single-points-of-failure intended? What failover, scaling, or decoupling strategy mitigates the concentration?"),
                        ("Blocks", qid, fan_out_obligation.id),
                    ],
                )
            )
            existing_ids.add(qid)

    fan_in_obligation = add_validation_obligation(
        doc,
        "information-flow-fan-in-reviewed",
        review_id,
        "Components with high fan-in (many upstream dependencies) are critical shared dependencies and should be reviewed.",
        first_span_id,
    )
    if not high_fan_in:
        add_check(doc, fan_in_obligation, CheckStatus.PASS, f"no components with fan-in >= {FAN_THRESHOLD}")
    elif FAN_ACK_RE.search(all_text):
        summary = ", ".join(f"{node} ({in_degree[node]})" for node in high_fan_in)
        add_check(doc, fan_in_obligation, CheckStatus.PASS, f"high fan-in acknowledged in source text: {summary}")
    else:
        summary = ", ".join(f"{node} ({in_degree[node]})" for node in high_fan_in)
        add_check(doc, fan_in_obligation, CheckStatus.UNKNOWN, f"high fan-in detected but not acknowledged: {summary}")
        qid = stable_id("question", "information-flow", "information-flow-fan-in-reviewed", review_id)
        if qid not in existing_ids:
            doc.objects.append(
                SpecObject(
                    qid,
                    Role.QUESTION_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    first_span_id,
                    facts=[
                        ("MissingInformationFlowEvidence", qid, "information-flow-fan-in-reviewed"),
                        ("QuestionText", qid, f"The following components have high fan-in ({summary}). Are these critical shared dependencies intended? What redundancy, versioning, or isolation strategy mitigates the concentration?"),
                        ("Blocks", qid, fan_in_obligation.id),
                    ],
                )
            )
            existing_ids.add(qid)

    # --- Bottleneck node detection (high fan-in AND high fan-out) ---
    # A component that is both a high fan-in node (many upstream dependencies)
    # and a high fan-out node (many downstream dependents) is a critical
    # bottleneck: failure or slowdown affects many downstream consumers while
    # also depending on many upstream sources.  This cross-dimension check is
    # stronger than fan-out or fan-in alone and deserves explicit review.
    BOTTLENECK_ACK_RE = re.compile(
        r"\b(bottleneck|single point of failure|spof|"
        r"critical (?:dependency|component|path|node)|"
        r"hotspot|hot[- ]?spot|choke[- ]?point|overloaded|"
        r"capacity[- ]?constrained?|throughput[- ]?limit)\b",
        re.IGNORECASE,
    )
    bottleneck_nodes = sorted(
        node for node in high_fan_out if node in set(high_fan_in)
    )

    bottleneck_obligation = add_validation_obligation(
        doc,
        "information-flow-bottleneck-node-reviewed",
        review_id,
        "Components that are both high fan-in and high fan-out nodes are critical bottlenecks whose failure or slowdown affects many downstream consumers while depending on many upstream sources.",
        first_span_id,
    )
    if not bottleneck_nodes:
        add_check(doc, bottleneck_obligation, CheckStatus.PASS, "no bottleneck nodes (high fan-in AND high fan-out) detected")
    elif BOTTLENECK_ACK_RE.search(all_text):
        summary = ", ".join(f"{node} (in={in_degree[node]}, out={out_degree[node]})" for node in bottleneck_nodes)
        add_check(doc, bottleneck_obligation, CheckStatus.PASS, f"bottleneck nodes acknowledged in source text: {summary}")
    else:
        summary = ", ".join(f"{node} (in={in_degree[node]}, out={out_degree[node]})" for node in bottleneck_nodes)
        add_check(doc, bottleneck_obligation, CheckStatus.UNKNOWN, f"bottleneck nodes (high fan-in AND high fan-out) detected but not acknowledged: {summary}")
        qid = stable_id("question", "information-flow", "information-flow-bottleneck-node-reviewed", review_id)
        if qid not in existing_ids:
            doc.objects.append(
                SpecObject(
                    qid,
                    Role.QUESTION_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    first_span_id,
                    facts=[
                        ("MissingInformationFlowEvidence", qid, "information-flow-bottleneck-node-reviewed"),
                        ("QuestionText", qid, f"The following components are both high fan-in and high fan-out ({summary}). Are these bottlenecks intended? What capacity planning, load shedding, autoscaling, circuit breaking, or redundancy strategy mitigates the bottleneck risk?"),
                        ("Blocks", qid, bottleneck_obligation.id),
                    ],
                )
            )
            existing_ids.add(qid)

    # --- Source/sink identification and reachability analysis ---
    # Source nodes have no incoming edges; sink nodes have no outgoing edges.
    # All components should be reachable from at least one source and able to
    # reach at least one sink.  Unreachable nodes or dead-end nodes may indicate
    # missing dependencies or dead code.
    if edges:
        all_targets: set[str] = set()
        for tgts in adjacency.values():
            all_targets.update(tgts)
        all_nodes: set[str] = set(adjacency.keys()) | all_targets

        sources = sorted(adjacency.keys() - all_targets)
        sinks = sorted(n for n in all_nodes if not adjacency.get(n))

        source_sink_obligation = add_validation_obligation(
            doc,
            "information-flow-source-sink-identified",
            review_id,
            "Data-flow graphs should have identifiable source and sink nodes; missing sources or sinks may indicate missing dependencies or dead-end components.",
            first_span_id,
        )
        if sources and sinks:
            add_check(doc, source_sink_obligation, CheckStatus.PASS, f"sources: {', '.join(sources)}; sinks: {', '.join(sinks)}")
        else:
            evidence_parts = []
            if not sources:
                evidence_parts.append("no source nodes (all components have incoming edges)")
            if not sinks:
                evidence_parts.append("no sink nodes (all components have outgoing edges)")
            add_check(doc, source_sink_obligation, CheckStatus.UNKNOWN, "; ".join(evidence_parts))
            qid = stable_id("question", "information-flow", "information-flow-source-sink-identified", review_id)
            if qid not in existing_ids:
                doc.objects.append(
                    SpecObject(
                        qid,
                        Role.QUESTION_OBJECT,
                        SemanticLevel.TEMPLATE_PARSED,
                        first_span_id,
                        facts=[
                            ("MissingInformationFlowEvidence", qid, "information-flow-source-sink-identified"),
                            ("QuestionText", qid, "The data-flow graph has no identifiable source or sink nodes. Are there missing dependencies or circular flows that should be broken?"),
                            ("Blocks", qid, source_sink_obligation.id),
                        ],
                    )
                )
                existing_ids.add(qid)

        # Reachability: BFS from all sources; check every node is reachable.
        visited_from_sources: set[str] = set()
        if sources:
            queue = list(sources)
            visited_from_sources = set(sources)
            while queue:
                node = queue.pop(0)
                for neighbor in adjacency.get(node, set()):
                    if neighbor not in visited_from_sources:
                        visited_from_sources.add(neighbor)
                        queue.append(neighbor)
        unreachable = sorted(all_nodes - visited_from_sources)

        reachability_obligation = add_validation_obligation(
            doc,
            "information-flow-reachability-reviewed",
            review_id,
            "All components in the data-flow graph should be reachable from at least one source node; unreachable components may indicate missing dependencies.",
            first_span_id,
        )
        if not unreachable:
            add_check(doc, reachability_obligation, CheckStatus.PASS, "all components reachable from source nodes")
        else:
            summary = ", ".join(unreachable)
            add_check(doc, reachability_obligation, CheckStatus.UNKNOWN, f"unreachable components: {summary}")
            qid = stable_id("question", "information-flow", "information-flow-reachability-reviewed", review_id)
            if qid not in existing_ids:
                doc.objects.append(
                    SpecObject(
                        qid,
                        Role.QUESTION_OBJECT,
                        SemanticLevel.TEMPLATE_PARSED,
                        first_span_id,
                        facts=[
                            ("MissingInformationFlowEvidence", qid, "information-flow-reachability-reviewed"),
                            ("QuestionText", qid, f"Components {summary} are not reachable from any source node. Are there missing dependencies or undocumented inputs?"),
                            ("Blocks", qid, reachability_obligation.id),
                        ],
                    )
                )
                existing_ids.add(qid)

        # Sink reachability: reverse BFS from sinks; check every node can reach at least one sink.
        reverse_adjacency: dict[str, set[str]] = {node: set() for node in all_nodes}
        for source, targets in adjacency.items():
            for target in targets:
                reverse_adjacency.setdefault(target, set()).add(source)
                reverse_adjacency.setdefault(source, set())

        visited_to_sinks: set[str] = set()
        if sinks:
            queue = list(sinks)
            visited_to_sinks = set(sinks)
            while queue:
                node = queue.pop(0)
                for predecessor in reverse_adjacency.get(node, set()):
                    if predecessor not in visited_to_sinks:
                        visited_to_sinks.add(predecessor)
                        queue.append(predecessor)
        no_sink_path = sorted(all_nodes - visited_to_sinks)

        sink_reachability_obligation = add_validation_obligation(
            doc,
            "information-flow-sink-reachability-reviewed",
            review_id,
            "All components in the data-flow graph should be able to reach at least one sink node; components with no sink path may indicate trapped cycles, dead-end processing, or missing outputs.",
            first_span_id,
        )
        if not no_sink_path:
            add_check(doc, sink_reachability_obligation, CheckStatus.PASS, "all components can reach at least one sink node")
        else:
            summary = ", ".join(no_sink_path)
            add_check(doc, sink_reachability_obligation, CheckStatus.UNKNOWN, f"components with no path to a sink: {summary}")
            qid = stable_id("question", "information-flow", "information-flow-sink-reachability-reviewed", review_id)
            if qid not in existing_ids:
                doc.objects.append(
                    SpecObject(
                        qid,
                        Role.QUESTION_OBJECT,
                        SemanticLevel.TEMPLATE_PARSED,
                        first_span_id,
                        facts=[
                            ("MissingInformationFlowEvidence", qid, "information-flow-sink-reachability-reviewed"),
                            ("QuestionText", qid, f"Components {summary} cannot reach any sink node. Are these trapped cycles/dead ends intentional, or are output/dependency declarations missing?"),
                            ("Blocks", qid, sink_reachability_obligation.id),
                        ],
                    )
                )
                existing_ids.add(qid)

        # --- Isolated component detection ---
        # Components mentioned with broader data-flow verbs (receives from, feeds
        # into, flows to, provides to, gets from, pulls from, pushes to) that are
        # NOT part of the explicit DATA_PATH_EDGE_RE verb set should still appear
        # in at least one DataFlowEdge.  A component mentioned with these broader
        # verbs but not connected to any explicit edge may indicate an
        # underspecified dependency or missing declaration.
        ISOLATED_COMPONENT_RE = re.compile(
            r"(?:(?:The|the|A|a|An|an)\s+)?"
            r"(?P<component>\b[A-Za-z]+(?:\s+[A-Za-z]+)?\b)"
            r"\s+(?:receives?\s+\w+\s+from|sends?\s+\w+\s+to"
            r"|feeds?\s+into|flows?\s+(?:from|to|into)"
            r"|provides?\s+\w+\s+to|gets?\s+\w+\s+from"
            r"|pulls?\s+\w+\s+from|pushes?\s+\w+\s+to)\b",
            re.IGNORECASE,
        )
        mentioned_components: set[str] = set()
        for item in candidate_items:
            for match in ISOLATED_COMPONENT_RE.finditer(item.raw_text):
                comp = match.group("component").strip().lower()
                if comp not in _EDGE_STOP_WORDS and len(comp) > 1:
                    mentioned_components.add(comp)

        connected_nodes = all_nodes
        isolated = sorted(mentioned_components - connected_nodes)

        isolated_obligation = add_validation_obligation(
            doc,
            "information-flow-isolated-component-reviewed",
            review_id,
            "Components mentioned in data-flow context should be connected to at least one declared data-path edge; isolated components may indicate underspecified dependencies.",
            first_span_id,
        )
        if not isolated:
            add_check(doc, isolated_obligation, CheckStatus.PASS, "all data-flow-mentioned components are connected to at least one edge")
        else:
            summary = ", ".join(isolated)
            add_check(doc, isolated_obligation, CheckStatus.UNKNOWN, f"components mentioned in data-flow context but not connected to any edge: {summary}")
            qid = stable_id("question", "information-flow", "information-flow-isolated-component-reviewed", review_id)
            if qid not in existing_ids:
                doc.objects.append(
                    SpecObject(
                        qid,
                        Role.QUESTION_OBJECT,
                        SemanticLevel.TEMPLATE_PARSED,
                        first_span_id,
                        facts=[
                            ("MissingInformationFlowEvidence", qid, "information-flow-isolated-component-reviewed"),
                            ("QuestionText", qid, f"Components {summary} are mentioned in data-flow context but not connected to any declared data-path edge. Are there missing dependency declarations or undocumented connections?"),
                            ("Blocks", qid, isolated_obligation.id),
                        ],
                    )
                )
                existing_ids.add(qid)

        # --- Connected components detection ---
        # The reachability check above only checks directed reachability from
        # source nodes.  Two independent subgraphs each with their own source
        # would pass reachability but the graph is still disconnected.  This
        # check uses undirected BFS to find connected components; multiple
        # components may indicate missing dependency declarations between
        # subsystems or intentionally independent modules that deserve review.
        CONNECTED_COMPONENTS_ACK_RE = re.compile(
            r"\b(independent(?:ly)?|separate|standalone|decoupled|isolated|"
            r"autonomous|self[- ]?contained|disjoint|unrelated|"
            r"separate (?:module|subsystem|service|component))\b",
            re.IGNORECASE,
        )

        # Build undirected adjacency from the directed edges.
        undirected_adj: dict[str, set[str]] = {}
        for src in adjacency:
            for tgt in adjacency[src]:
                undirected_adj.setdefault(src, set()).add(tgt)
                undirected_adj.setdefault(tgt, set()).add(src)
        for node in all_nodes:
            undirected_adj.setdefault(node, set())

        visited_cc: set[str] = set()
        components: list[set[str]] = []
        for node in all_nodes:
            if node in visited_cc:
                continue
            comp: set[str] = set()
            queue = [node]
            visited_cc.add(node)
            while queue:
                cur = queue.pop(0)
                comp.add(cur)
                for neighbor in undirected_adj.get(cur, set()):
                    if neighbor not in visited_cc:
                        visited_cc.add(neighbor)
                        queue.append(neighbor)
            components.append(comp)

        connected_components_obligation = add_validation_obligation(
            doc,
            "information-flow-connected-components-reviewed",
            review_id,
            "Data-flow graphs with multiple disconnected components may indicate missing dependency declarations between subsystems or intentionally independent modules that deserve review.",
            first_span_id,
        )
        if len(components) <= 1:
            add_check(doc, connected_components_obligation, CheckStatus.PASS, "data-flow graph is fully connected (single component)")
        elif CONNECTED_COMPONENTS_ACK_RE.search(all_text):
            comp_summaries = [", ".join(sorted(comp)) for comp in components]
            add_check(doc, connected_components_obligation, CheckStatus.PASS, f"multiple disconnected components acknowledged in source text: {' | '.join(comp_summaries)}")
        else:
            comp_summaries = [", ".join(sorted(comp)) for comp in components]
            add_check(doc, connected_components_obligation, CheckStatus.UNKNOWN, f"{len(components)} disconnected components detected: {' | '.join(comp_summaries)}")
            qid = stable_id("question", "information-flow", "information-flow-connected-components-reviewed", review_id)
            if qid not in existing_ids:
                doc.objects.append(
                    SpecObject(
                        qid,
                        Role.QUESTION_OBJECT,
                        SemanticLevel.TEMPLATE_PARSED,
                        first_span_id,
                        facts=[
                            ("MissingInformationFlowEvidence", qid, "information-flow-connected-components-reviewed"),
                            ("QuestionText", qid, f"The data-flow graph has {len(components)} disconnected components ({' | '.join(comp_summaries)}). Are these intentionally independent subsystems, or are there missing dependency declarations between them?"),
                            ("Blocks", qid, connected_components_obligation.id),
                        ],
                    )
                )
                existing_ids.add(qid)

        # --- Redundant path detection ---
        # When multiple distinct paths exist from node A to node B in the
        # DataFlowEdge graph, this may indicate intentional redundancy (fault
        # tolerance, backup paths) or accidental duplication.  If the spec text
        # acknowledges redundancy ("redundant", "backup", "fallback",
        # "failover", "fault tolerance", "high availability", "duplicate"),
        # the obligation passes; otherwise it becomes Unknown.
        REDUNDANCY_ACK_RE = re.compile(
            r"\b(redundant(?:ly)?|backup|fallback|failover|fault tolerance|"
            r"high availability|duplicate(?:d)?|resilien(?:t|ce)|replicated?)\b",
            re.IGNORECASE,
        )

        def _find_all_paths(adj: dict[str, set[str]], start: str, goal: str, max_depth: int = 6) -> list[list[str]]:
            """Find all simple paths from start to goal (max_depth hops)."""
            paths: list[list[str]] = []
            stack: list[tuple[str, list[str]]] = [(start, [start])]
            while stack:
                node, path = stack.pop()
                if len(path) - 1 >= max_depth:
                    continue
                for neighbour in adj.get(node, set()):
                    if neighbour == goal:
                        paths.append(path + [neighbour])
                    elif neighbour not in path:  # simple path: no revisits
                        stack.append((neighbour, path + [neighbour]))
            return paths

        redundant_pairs: list[tuple[str, str, int]] = []  # (source, target, path_count)
        checked_pairs: set[tuple[str, str]] = set()
        for src in adjacency:
            for dst in adjacency.get(src, set()):
                # Check if there's also an indirect path from src to dst
                # (i.e., a path of length >= 3 that goes through other nodes).
                indirect_paths = [
                    p for p in _find_all_paths(adjacency, src, dst, max_depth=6)
                    if len(p) >= 3  # direct edge is [src, dst] (len 2); indirect is >= 3 (src, mid, ..., dst)
                ]
                pair_key = (src, dst)
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)
                if indirect_paths:
                    redundant_pairs.append((src, dst, len(indirect_paths)))

        redundant_obligation = add_validation_obligation(
            doc,
            "information-flow-redundant-path-reviewed",
            review_id,
            "When multiple distinct paths connect the same pair of components in the data-flow graph, the spec should acknowledge whether this is intentional redundancy (fault tolerance, backup) or needs review for accidental duplication.",
            first_span_id,
        )
        if not redundant_pairs:
            add_check(doc, redundant_obligation, CheckStatus.PASS, "no redundant paths found in the data-flow graph")
        elif bool(REDUNDANCY_ACK_RE.search(all_text)):
            pair_summary = "; ".join(f"{s}→{t} ({n} indirect paths)" for s, t, n in redundant_pairs)
            add_check(doc, redundant_obligation, CheckStatus.PASS, f"redundant paths acknowledged in spec text: {pair_summary}")
        else:
            pair_summary = "; ".join(f"{s}→{t} ({n} indirect paths)" for s, t, n in redundant_pairs)
            add_check(doc, redundant_obligation, CheckStatus.UNKNOWN, f"redundant paths found without acknowledgment: {pair_summary}")
            qid = stable_id("question", "information-flow", "information-flow-redundant-path-reviewed", review_id)
            if qid not in existing_ids:
                doc.objects.append(
                    SpecObject(
                        qid,
                        Role.QUESTION_OBJECT,
                        SemanticLevel.TEMPLATE_PARSED,
                        first_span_id,
                        facts=[
                            ("MissingInformationFlowEvidence", qid, "information-flow-redundant-path-reviewed"),
                            ("QuestionText", qid, f"Multiple distinct paths exist between components {pair_summary}. Is this intentional redundancy for fault tolerance, or accidental duplication that should be reviewed?"),
                            ("Blocks", qid, redundant_obligation.id),
                        ],
                    )
                )
                existing_ids.add(qid)

        # --- Temporal ordering impossibility detection ---
        # Extract explicit temporal ordering statements like "A before B",
        # "A after B", "A then B", "A precedes B", "A follows B" and build a
        # temporal ordering graph.  A cycle in this graph means the spec claims
        # an impossible temporal ordering (e.g. "A before B" and "B before A").
        # Note: we scan ALL items, not just candidate_items, because temporal
        # ordering statements may appear without explicit data-flow keywords.
        TEMPORAL_ORDER_RE = re.compile(
            r"(?:(?:The|the|A|a|An|an)\s+)?"
            r"(?P<source>\b[A-Za-z]+(?:\s+[A-Za-z]+)?\b)"
            r"\s+(?P<verb>happens?\s+before|comes?\s+before|occurs?\s+before|"
            r"precedes?|runs?\s+before|executes?\s+before|"
            r"happens?\s+after|comes?\s+after|occurs?\s+after|"
            r"follows?|runs?\s+after|executes?\s+after|"
            r"then)"
            r"\s+(?:(?:the|a|an)\s+)?"
            r"(?P<target>\b[A-Za-z]+(?:\s+[A-Za-z]+)?\b)",
            re.IGNORECASE,
        )
        temporal_edges: list[tuple[str, str, str, str, str]] = []  # (before, after, verb, item_id, span_id)
        for item in doc.items:
            for match in TEMPORAL_ORDER_RE.finditer(item.raw_text):
                src = match.group("source").strip().lower()
                tgt = match.group("target").strip().lower()
                if src in _EDGE_STOP_WORDS or tgt in _EDGE_STOP_WORDS:
                    continue
                verb = match.group("verb").lower().strip()
                # Normalize: "A before B" means A → B (A precedes B)
                # "A after B" / "A follows B" means B → A (B precedes A)
                if "after" in verb or "follows" in verb:
                    before, after = tgt, src
                else:
                    before, after = src, tgt
                temporal_edges.append((before, after, verb, item.id, exact_match_span(item, match.start(), match.end())))

        # Build temporal adjacency and detect cycles via DFS.
        temporal_adj: dict[str, set[str]] = {}
        for before, after, _verb, _item_id, _span_id in temporal_edges:
            temporal_adj.setdefault(before, set()).add(after)

        WHITE_T, GRAY_T, BLACK_T = 0, 1, 2
        t_color: dict[str, int] = {node: WHITE_T for node in temporal_adj}
        temporal_cycles: list[list[str]] = []

        def _dfs_temporal_cycle(node: str, path: list[str]) -> None:
            t_color[node] = GRAY_T
            path.append(node)
            for neighbor in temporal_adj.get(node, set()):
                if t_color.get(neighbor, WHITE_T) == GRAY_T:
                    cycle_start = path.index(neighbor)
                    temporal_cycles.append(path[cycle_start:] + [neighbor])
                elif t_color.get(neighbor, WHITE_T) == WHITE_T:
                    _dfs_temporal_cycle(neighbor, path)
            path.pop()
            t_color[node] = BLACK_T

        for node in list(temporal_adj):
            if t_color[node] == WHITE_T:
                _dfs_temporal_cycle(node, [])

        # Deduplicate temporal cycles.
        seen_t_keys: set[tuple[str, ...]] = set()
        unique_t_cycles: list[list[str]] = []
        for cycle in temporal_cycles:
            key = tuple(sorted(cycle))
            if key not in seen_t_keys:
                seen_t_keys.add(key)
                unique_t_cycles.append(cycle)

        # Emit TemporalOrderEdge atoms for each extracted temporal edge.
        # Each temporal edge cites the exact matched ordering phrase so temporal
        # contradictions can be reviewed against the precise source text, not
        # only the containing Plain item.
        for before, after, verb, item_id, edge_span_id in temporal_edges:
            edge_id = stable_id("temporal-edge", before, after, "precedes", item_id)
            if edge_id not in existing_ids:
                doc.objects.append(
                    SpecObject(
                        edge_id,
                        Role.VALIDATION_OBJECT,
                        SemanticLevel.TEMPLATE_PARSED,
                        edge_span_id,
                        facts=[
                            ("TemporalOrderEdge", edge_id, before, after),
                        ],
                    )
                )
                existing_ids.add(edge_id)

        temporal_obligation = add_validation_obligation(
            doc,
            "information-flow-temporal-impossibility-reviewed",
            review_id,
            "Specs that declare explicit temporal ordering between components should not contain impossible cycles (A before B and B before A).",
            first_span_id,
        )
        if not temporal_edges:
            add_check(doc, temporal_obligation, CheckStatus.PASS, "no explicit temporal ordering statements found")
        elif not unique_t_cycles:
            edge_summary = "; ".join(f"{b} before {a}" for b, a, _, _, _ in temporal_edges)
            add_check(doc, temporal_obligation, CheckStatus.PASS, f"temporal ordering is consistent (no impossible cycles): {edge_summary}")
        else:
            cycle_summaries = [" → ".join(cycle) for cycle in unique_t_cycles]
            summary = "; ".join(cycle_summaries)
            add_check(doc, temporal_obligation, CheckStatus.FAIL, f"impossible temporal cycle(s) detected: {summary}")
            qid = stable_id("question", "information-flow", "information-flow-temporal-impossibility-reviewed", review_id)
            if qid not in existing_ids:
                doc.objects.append(
                    SpecObject(
                        qid,
                        Role.QUESTION_OBJECT,
                        SemanticLevel.TEMPLATE_PARSED,
                        first_span_id,
                        facts=[
                            ("MissingInformationFlowEvidence", qid, "information-flow-temporal-impossibility-reviewed"),
                            ("QuestionText", qid, f"The spec declares temporal ordering that creates an impossible cycle ({summary}). Which ordering constraint is incorrect, or what concurrency/parallelism resolves the apparent contradiction?"),
                            ("Blocks", qid, temporal_obligation.id),
                        ],
                    )
                )
                existing_ids.add(qid)

        # --- Cross-layer consistency: DataFlowEdge vs TemporalOrderEdge ---
        # If data flows A→B (A sends/writes/depends-on B), the data-flow
        # ordering implies A should happen before or no-later-than B.  If the
        # spec also declares "B before A" explicitly, that contradicts the
        # data-flow direction.  We flag these cross-layer inconsistencies.
        if edges and temporal_edges:
            # Build a set of (before, after) pairs from temporal edges.
            temporal_pairs: set[tuple[str, str]] = set()
            for before, after, _verb, _item_id, _span_id in temporal_edges:
                temporal_pairs.add((before, after))

            contradictions: list[tuple[str, str, str, str]] = []  # (data_src, data_tgt, temp_before, temp_after)
            for source, target, direction, _item_id, _span_id in edges:
                s = source.lower().strip()
                t = target.lower().strip()
                # Data flows source → target (source sends/writes/depends-on target).
                # Temporal contradiction: temporal says target before source.
                if (t, s) in temporal_pairs:
                    contradictions.append((source, target, t, s))

            cross_obligation = add_validation_obligation(
                doc,
                "information-flow-data-temporal-consistency-reviewed",
                review_id,
                "When data flows from A to B but temporal ordering states B before A, the spec contains a cross-layer inconsistency that should be resolved.",
                first_span_id,
            )
            if not contradictions:
                add_check(doc, cross_obligation, CheckStatus.PASS, "data-flow direction and temporal ordering are consistent")
            else:
                contra_summary = "; ".join(
                    f"data flows {ds}→{dt} but temporal says {tb} before {ta}"
                    for ds, dt, tb, ta in contradictions
                )
                add_check(doc, cross_obligation, CheckStatus.FAIL, f"cross-layer contradiction(s): {contra_summary}")
                qid = stable_id("question", "information-flow", "information-flow-data-temporal-consistency-reviewed", review_id)
                if qid not in existing_ids:
                    doc.objects.append(
                        SpecObject(
                            qid,
                            Role.QUESTION_OBJECT,
                            SemanticLevel.TEMPLATE_PARSED,
                            first_span_id,
                            facts=[
                                ("MissingInformationFlowEvidence", qid, "information-flow-data-temporal-consistency-reviewed"),
                                ("QuestionText", qid, f"The spec contains cross-layer ordering contradictions ({contra_summary}). Is the data-flow direction or the temporal ordering statement incorrect, or does concurrency/parallel execution resolve the apparent contradiction?"),
                                ("Blocks", qid, cross_obligation.id),
                            ],
                        )
                    )
                    existing_ids.add(qid)

        # --- Dependency depth / critical path length detection ---
        # When the DataFlowEdge graph is acyclic, compute the longest path
        # (critical path).  Deep dependency chains (>= DEPTH_THRESHOLD edges)
        # may indicate latency, fragility, or excessive coupling concerns that
        # deserve explicit review.  If the spec text acknowledges deep chains
        # ("deep", "multi-layer", "multi-hop", "long chain", "critical path",
        # "layered", "pipeline depth"), the obligation passes; otherwise it
        # becomes Unknown with a blocking question.
        if not unique_cycles:
            DEPTH_THRESHOLD = 4  # minimum edges to trigger depth review
            DEPTH_ACK_RE = re.compile(
                r"\b(deep(?:ly)?|multi[- ]?layer|multi[- ]?hop|long[- ]?chain|"
                r"critical[- ]?path|layered|pipeline[- ]?depth|"
                r"chain[- ]?of[- ]?command|nest(?:ed|ing))\b",
                re.IGNORECASE,
            )

            # Compute longest path via topological sort + DP.
            # Only meaningful when the graph is acyclic.
            in_degree_dp: dict[str, int] = {node: 0 for node in all_nodes}
            for src in adjacency:
                for tgt in adjacency[src]:
                    in_degree_dp[tgt] = in_degree_dp.get(tgt, 0) + 1

            # Kahn's algorithm for topological order.
            from collections import deque
            topo_queue: deque[str] = deque(
                node for node in all_nodes if in_degree_dp.get(node, 0) == 0
            )
            topo_order: list[str] = []
            while topo_queue:
                node = topo_queue.popleft()
                topo_order.append(node)
                for neighbor in adjacency.get(node, set()):
                    in_degree_dp[neighbor] -= 1
                    if in_degree_dp[neighbor] == 0:
                        topo_queue.append(neighbor)

            # Longest path DP: dist[node] = max(dist[pred]) + 1 for each edge pred→node.
            dist: dict[str, int] = {node: 0 for node in all_nodes}
            predecessor: dict[str, str | None] = {node: None for node in all_nodes}
            for node in topo_order:
                for neighbor in adjacency.get(node, set()):
                    if dist[node] + 1 > dist[neighbor]:
                        dist[neighbor] = dist[node] + 1
                        predecessor[neighbor] = node

            max_depth = max(dist.values()) if dist else 0

            # Reconstruct the longest path for evidence.
            def _reconstruct_path(end: str) -> list[str]:
                path = [end]
                cur = predecessor[end]
                while cur is not None:
                    path.append(cur)
                    cur = predecessor[cur]
                return list(reversed(path))

            depth_obligation = add_validation_obligation(
                doc,
                "information-flow-dependency-depth-reviewed",
                review_id,
                "Specs with deep dependency chains (long critical paths) should acknowledge the depth and review it for latency, fragility, or coupling concerns.",
                first_span_id,
            )
            if max_depth < DEPTH_THRESHOLD:
                add_check(doc, depth_obligation, CheckStatus.PASS, f"maximum dependency depth is {max_depth} (below threshold of {DEPTH_THRESHOLD})")
            elif DEPTH_ACK_RE.search(all_text):
                deepest = max(dist, key=lambda n: dist[n])
                longest_path = _reconstruct_path(deepest)
                path_str = " → ".join(longest_path)
                add_check(doc, depth_obligation, CheckStatus.PASS, f"deep dependency chain ({max_depth} edges: {path_str}) acknowledged in source text")
            else:
                deepest = max(dist, key=lambda n: dist[n])
                longest_path = _reconstruct_path(deepest)
                path_str = " → ".join(longest_path)
                add_check(doc, depth_obligation, CheckStatus.UNKNOWN, f"deep dependency chain ({max_depth} edges: {path_str}) not acknowledged in source text")
                qid = stable_id("question", "information-flow", "information-flow-dependency-depth-reviewed", review_id)
                if qid not in existing_ids:
                    doc.objects.append(
                        SpecObject(
                            qid,
                            Role.QUESTION_OBJECT,
                            SemanticLevel.TEMPLATE_PARSED,
                            first_span_id,
                            facts=[
                                ("MissingInformationFlowEvidence", qid, "information-flow-dependency-depth-reviewed"),
                                ("QuestionText", qid, f"The dependency chain {path_str} has {max_depth} edges. Is this depth intended? What latency, fragility, or coupling review addresses the long critical path?"),
                                ("Blocks", qid, depth_obligation.id),
                            ],
                        )
                    )
                    existing_ids.add(qid)

        # --- Bidirectional edge review ---
        # When A→B and B→A both exist in the DataFlowEdge graph, the pair
        # has edges in both directions.  This may be intentional (request-
        # response, feedback loop, bidirectional channel) but deserves review
        # because it can also indicate ambiguity or a specification inconsistency.
        BIDIRECTIONAL_ACK_RE = re.compile(
            r"\b(bidirectional|two[- ]?way|request[- ]?response|feedback[- ]?loop|"
            r"mutual|round[- ]?trip|ping[- ]?pong|dialogue|bi[- ]?directional)\b",
            re.IGNORECASE,
        )
        bidirectional_pairs: list[tuple[str, str]] = []
        checked_bidir: set[tuple[str, str]] = set()
        for src in adjacency:
            for tgt in adjacency.get(src, set()):
                if (tgt, src) in checked_bidir or (src, tgt) in checked_bidir:
                    continue
                if tgt in adjacency and src in adjacency.get(tgt, set()):
                    bidirectional_pairs.append((src, tgt))
                    checked_bidir.add((src, tgt))

        bidir_obligation = add_validation_obligation(
            doc,
            "information-flow-bidirectional-edge-reviewed",
            review_id,
            "When two components have data-flow edges in both directions, the spec should acknowledge whether this is intentional (e.g. request-response, feedback loop) or needs review for ambiguity.",
            first_span_id,
        )
        if not bidirectional_pairs:
            add_check(doc, bidir_obligation, CheckStatus.PASS, "no bidirectional edges found in the data-flow graph")
        elif bool(BIDIRECTIONAL_ACK_RE.search(all_text)):
            pair_summary = "; ".join(f"{s} ↔ {t}" for s, t in bidirectional_pairs)
            add_check(doc, bidir_obligation, CheckStatus.PASS, f"bidirectional edges acknowledged in spec text: {pair_summary}")
        else:
            pair_summary = "; ".join(f"{s} ↔ {t}" for s, t in bidirectional_pairs)
            add_check(doc, bidir_obligation, CheckStatus.UNKNOWN, f"bidirectional edges found without acknowledgment: {pair_summary}")
            qid = stable_id("question", "information-flow", "information-flow-bidirectional-edge-reviewed", review_id)
            if qid not in existing_ids:
                doc.objects.append(
                    SpecObject(
                        qid,
                        Role.QUESTION_OBJECT,
                        SemanticLevel.TEMPLATE_PARSED,
                        first_span_id,
                        facts=[
                            ("MissingInformationFlowEvidence", qid, "information-flow-bidirectional-edge-reviewed"),
                            ("QuestionText", qid, f"Components have data-flow edges in both directions ({pair_summary}). Is this intentional (e.g. request-response, feedback loop) or should the spec clarify the directionality?"),
                            ("Blocks", qid, bidir_obligation.id),
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
    preprocessing order, explicit future/label leakage wording, temporal split
    order, feature freshness/staleness review, baseline comparison, named
    comparator review, uncertainty/error-bar reporting, and named uncertainty
    method review.
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
    feature_inputs_declared = bool(ML_FEATURE_INPUT_RE.search(all_text))
    feature_availability_declared = bool(ML_FEATURE_AVAILABILITY_RE.search(all_text))
    check_property(
        "ml-feature-availability-reviewed",
        "ML/time-series input features should state whether they are available at prediction time, using point-in-time, lagged, historical, or equivalent evidence.",
        not feature_inputs_declared or (feature_availability_declared and not future_label_leakage),
        "feature availability is reviewed or no explicit feature/input list is present",
        "feature/input wording lacks point-in-time availability evidence" if not future_label_leakage else "feature/input wording also triggers future/label leakage review",
        "Which declared features, inputs, predictors, or covariates are available at prediction time, and are they point-in-time/lagged as needed?",
    )
    freshness_signal = bool(ML_FRESHNESS_SIGNAL_RE.search(all_text))
    freshness_evidence = bool(ML_FRESHNESS_EVIDENCE_RE.search(all_text))
    check_property(
        "ml-feature-freshness-reviewed",
        "ML/time-series specs that mention real-time, live, current, latest, recent, or fresh inputs should state a freshness, latency, staleness, data-age, update-cadence, or as-of timestamp assumption.",
        not (feature_inputs_declared and freshness_signal) or freshness_evidence,
        "feature freshness/staleness evidence found, or no real-time/current feature signal is present",
        "real-time/current feature wording lacks freshness, staleness, latency, data-age, update-cadence, or as-of timestamp evidence",
        "What freshness, staleness, latency, data-age, update-cadence, or as-of timestamp assumption applies to these time-dependent features?",
    )
    temporal_split_declared = bool(ML_TEMPORAL_SPLIT_RE.search(all_text))
    random_split_declared = bool(ML_RANDOM_SPLIT_RE.search(all_text))
    check_property(
        "ml-temporal-split-order-reviewed",
        "Time-series validation should preserve temporal ordering for train/validation/test splits or explicitly justify any random/shuffled cross-validation scheme.",
        temporal_split_declared or not random_split_declared,
        "temporal split/order evidence found, or no explicit random/shuffled split wording found",
        "random/shuffled split wording appears without chronological, walk-forward, or out-of-time split evidence",
        "Does the train/validation/test split preserve temporal order, or is a random/shuffled split justified for this time-series task?",
    )
    baseline_declared = bool(ML_BASELINE_RE.search(all_text))
    named_baseline_declared = bool(ML_NAMED_BASELINE_RE.search(all_text))
    check_property(
        "ml-baseline-comparison-declared",
        "ML/time-series validation should name a baseline, benchmark, or ablation comparator before performance claims are trusted.",
        baseline_declared,
        "baseline/comparator-like term found in source text",
        "no baseline or comparator term found",
        "What baseline, benchmark, or ablation comparator will contextualize this model's reported performance?",
    )
    check_property(
        "ml-baseline-comparator-named",
        "A generic baseline mention should identify the comparator family or reference system before performance claims are trusted.",
        named_baseline_declared,
        "specific comparator-like term found in source text",
        "baseline mentioned without a named comparator family such as naive, persistence, benchmark, or ablation" if baseline_declared else "no baseline comparator term found",
        "Which concrete comparator family or reference system is the baseline?",
    )
    uncertainty_declared = bool(ML_UNCERTAINTY_RE.search(all_text))
    named_uncertainty_declared = bool(ML_NAMED_UNCERTAINTY_RE.search(all_text))
    check_property(
        "ml-uncertainty-reporting-declared",
        "ML/time-series validation should declare uncertainty reporting such as confidence intervals, error bars, or bootstrap variance where possible.",
        uncertainty_declared,
        "uncertainty/error-bar-like term found in source text",
        "no uncertainty or error-bar reporting term found",
        "Will final metrics include confidence intervals, error bars, bootstrap variance, or another uncertainty report?",
    )
    check_property(
        "ml-uncertainty-method-named",
        "A generic uncertainty mention should identify the reporting method before validation claims are trusted.",
        named_uncertainty_declared,
        "specific uncertainty reporting method found in source text",
        "uncertainty mentioned without a named method such as confidence intervals, error bars, bootstrap, standard deviation, or variance" if uncertainty_declared else "no uncertainty reporting method found",
        "Which uncertainty reporting method will accompany the final metric?",
    )
    return doc


PASS_REGISTRY = [
    PassSpec("seed-raw-item-objects", "Wrap indexed Plain items as RawTextOnly source objects.", seed_raw_item_objects),
    PassSpec("build-concept-table", "Extract explicit concept definitions, references, external links, and unresolved-question records.", build_concept_table),
    PassSpec("build-requirement-test-coverage", "Create shallow requirement/test objects and Unknown coverage questions.", build_requirement_test_coverage),
    PassSpec("build-security-privacy-validation", "Create conservative security/privacy obligations and questions.", build_security_privacy_validation),
    PassSpec("build-information-flow-validation", "Create conservative information-flow and temporal-availability obligations and questions.", build_information_flow_validation),
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

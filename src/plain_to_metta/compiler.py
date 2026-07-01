from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .ids import slugify, stable_id
from .model import Graph, PlainFile, PlainItem, Section
from .parser import parse_plain, read_plain_file

CONCEPT_RE = re.compile(r":([A-Za-z][A-Za-z0-9 _-]*):")
ABLE_RE = re.compile(r":(?P<actor>[^:]+):\s+should\s+be\s+able\s+to\s+(?P<verb>[A-Za-z][A-Za-z0-9_-]*)\s+:?(?P<patient>[A-Za-z][A-Za-z0-9 _-]*):?", re.I)
ONLY_VALID_RE = re.compile(r"Only\s+valid\s+:?(?P<concept>[A-Za-z][A-Za-z0-9 _-]*):?\s+items\s+can\s+be\s+(?P<verb>[A-Za-z][A-Za-z0-9_-]*)", re.I)
ATTR_RE = re.compile(r"(?P<name>[^-]+)-(?P<desc>.*?)(?P<required>\brequired\b|\boptional\b)", re.I)
GIVEN_WHEN_THEN_RE = re.compile(r"Given\s+(?P<given>.*?),\s*when\s+(?P<when>.*?),\s*then\s+(?P<then>.*)\.?$", re.I)


def compile_paths(paths: Iterable[str | Path], project_id: str = "plain-metta-specatom") -> dict:
    graph = Graph()
    files = [read_plain_file(path, i + 1) for i, path in enumerate(paths)]
    all_sections: list[Section] = []
    all_items: list[PlainItem] = []
    concept_ids: dict[str, str] = {}
    defined_concepts: set[str] = set()
    item_to_obl: dict[str, str] = {}
    last_requirement_item: PlainItem | None = None

    graph.fact("CompilerRun", stable_id("run", project_id, *(f.digest for f in files), length=8))

    for file in files:
        graph.fact("PlainFile", file.id, file.path, file.digest)
        sections, items, spans = parse_plain(file)
        graph.spans.update(spans)
        all_sections.extend(sections)
        all_items.extend(items)
        for span in spans.values():
            graph.fact("SourceSpan", span.id, span.file_id, span.start_byte, span.end_byte, span.start_line, span.end_line)
        for section in sections:
            graph.fact("Section", section.id, section.file_id, section.kind, section.ordinal)
            graph.fact("DerivedFrom", section.id, section.span_id)
        for item in items:
            graph.fact("PlainItem", item.id, item.section_id, item.parent_item_id or "none", item.ordinal, item.raw_text)
            graph.fact("DerivedFrom", item.id, item.span_id)

    section_by_id = {s.id: s for s in all_sections}

    # Concept table and definition pass.
    for item in all_items:
        section = section_by_id[item.section_id]
        concepts = extract_concepts(item.raw_text)
        if section.kind == "Definitions" and concepts:
            defined_concepts.add(concepts[0])
        for concept in concepts:
            cid = concept_ids.setdefault(concept, f"c-{slugify(concept)}")
            graph.spec_object(cid, "ConceptObject", item.span_id, "RawTextOnly")
            graph.fact("LexicalConcept", cid, concept)
            graph.fact("SymbolName", cid, concept)
            graph.fact("References", item.id, cid)
            if section.kind == "Definitions" and concept == concepts[0]:
                graph.fact("DefinedConcept", cid)

    # Requirement, action, attributes, and test extraction.
    for item in all_items:
        section = section_by_id[item.section_id]
        if section.kind in {"FunctionalSpecifications", "ImplementationRequirements"}:
            req_id = stable_id("req", item.id, length=10)
            prop_id = stable_id("prop", item.id, length=10)
            claim_id = stable_id("claim", item.id, length=10)
            obl_id = stable_id("obl", item.id, length=10)
            graph.spec_object(req_id, "RequirementObject", item.span_id, "RawTextOnly")
            graph.fact("Requirement", req_id)
            graph.fact("RequirementKind", req_id, "Functional" if section.kind == "FunctionalSpecifications" else "Implementation")
            graph.fact("NormativeForce", req_id, "Should" if "should" in item.raw_text.lower() else "Unspecified")
            graph.fact("Polarity", req_id, "Negative" if re.search(r"\bmust\s+not\b|\bshould\s+not\b", item.raw_text, re.I) else "Positive")
            graph.spec_object(prop_id, "PropositionObject", item.span_id, "RawTextOnly")
            graph.fact("Proposition", prop_id)
            graph.fact("RawProposition", prop_id, item.raw_text)
            graph.fact("Claim", claim_id)
            graph.fact("ClaimAbout", claim_id, req_id)
            graph.fact("RealizesClaim", prop_id, claim_id)
            graph.fact("ClaimText", claim_id, item.raw_text)
            graph.fact("Obligation", obl_id, req_id, prop_id)
            graph.spec_object(obl_id, "ObligationObject", item.span_id, "RawTextOnly")
            graph.assertion("C:plain-source", claim_id, 1.0, 0.0)
            item_to_obl[item.id] = obl_id
            last_requirement_item = item
            extract_action_templates(graph, item, concept_ids, obl_id)
            extract_ml_timeseries_templates(graph, item)
        elif section.kind == "Definitions":
            extract_attributes(graph, item, concept_ids)
        elif section.kind == "AcceptanceTests":
            parent_req = find_parent_requirement(item, all_items, item_to_obl) or last_requirement_item
            extract_test(graph, item, parent_req, item_to_obl)

    # Questions for referenced concepts lacking definitions.
    for concept, cid in sorted(concept_ids.items()):
        if concept not in defined_concepts and concept.lower() not in {"system"}:
            qid = stable_id("q", "missing-definition", cid, length=10)
            graph.fact("Question", qid)
            graph.fact("QuestionKind", qid, "MissingDefinition")
            graph.fact("QuestionText", qid, f"What is the intended definition of {concept}?")
            graph.fact("QuestionAbout", qid, cid)
            graph.questions.append({"id": qid, "kind": "MissingDefinition", "about": cid, "text": f"What is the intended definition of {concept}?"})

    validate_graph(graph)
    return to_document(graph, files)


def extract_concepts(text: str) -> list[str]:
    seen = []
    for match in CONCEPT_RE.finditer(text):
        concept = " ".join(match.group(1).split())
        if concept not in seen:
            seen.append(concept)
    return seen


def extract_action_templates(graph: Graph, item: PlainItem, concept_ids: dict[str, str], obl_id: str) -> None:
    match = ABLE_RE.search(item.raw_text)
    if not match:
        return
    actor_name = match.group("actor").strip()
    verb = match.group("verb").strip().lower()
    patient_name = match.group("patient").strip()
    actor_id = concept_ids.setdefault(actor_name, f"c-{slugify(actor_name)}")
    patient_id = concept_ids.setdefault(patient_name, f"c-{slugify(patient_name)}")
    act_id = stable_id("act", item.id, actor_id, verb, patient_id, length=10)
    graph.spec_object(act_id, "ActionObject", item.span_id, "ActionSchemaParsed")
    graph.fact("ActionSchema", act_id)
    graph.fact("Actor", act_id, actor_id)
    graph.fact("Verb", act_id, verb)
    graph.fact("Patient", act_id, patient_id)
    graph.fact("RelatesTo", act_id, obl_id)
    graph.assertion("C:compiler-extraction", act_id, 0.72, 0.08)
    valid = ONLY_VALID_RE.search(item.raw_text)
    if valid:
        predicate = f"valid-{slugify(valid.group('concept'))}"
        graph.fact("Precondition", act_id, predicate)
        graph.fact("UndefinedPredicate", predicate)
        qid = stable_id("q", "undefined-predicate", predicate, length=10)
        graph.fact("Question", qid)
        graph.fact("QuestionKind", qid, "MissingDefinition")
        graph.fact("QuestionText", qid, f"What makes a {valid.group('concept').strip()} valid?")
        graph.fact("QuestionAbout", qid, predicate)


def extract_ml_timeseries_templates(graph: Graph, item: PlainItem) -> None:
    text = item.raw_text.lower()
    if "experiment trains" in text and "predict" in text:
        exp_id = stable_id("exp", item.id, "ml", length=10)
        graph.spec_object(exp_id, "ValidationObject", item.span_id, "TemplateParsed")
        graph.fact("MLExperiment", exp_id)
        if "returnlabel" in text or "time" in text:
            graph.fact("TimeSeriesExperiment", exp_id)
            graph.fact("MLTimeSeriesExperiment", exp_id)
            for prop in [
                "no-future-pollution",
                "train-only-preprocessing-fit",
                "no-test-influence-on-model-selection",
                "temporal-split-ordering",
                "target-availability-discipline",
            ]:
                graph.fact("RequiresValidation", exp_id, prop)
    if "normalized" in text and "split" in text:
        step_id = stable_id("step", item.id, "normalize", length=10)
        graph.spec_object(step_id, "ProcessStepObject", item.span_id, "TemplateParsed")
        graph.fact("ProcessStep", step_id)
        graph.fact("PreprocessingStep", step_id)
        chk_id = stable_id("chk", step_id, "train-only-preprocessing-fit", length=10)
        qid = stable_id("q", step_id, "normalization-scope", length=10)
        claim_id = stable_id("claim", step_id, "valid-performance", length=10)
        graph.fact("Check", chk_id)
        graph.fact("CheckTargets", chk_id, step_id)
        graph.fact("CheckProperty", chk_id, "train-only-preprocessing-fit")
        graph.fact("CheckMode", chk_id, "Crisp")
        graph.fact("CheckStatus", chk_id, "Unknown")
        graph.fact("Question", qid)
        graph.fact("QuestionText", qid, "Were normalization parameters fit only on the training split?")
        graph.fact("QuestionAbout", qid, step_id)
        graph.fact("Blocks", qid, claim_id)
        graph.assertion("C:static-validator", claim_id, 0.20, 0.45)


def extract_attributes(graph: Graph, item: PlainItem, concept_ids: dict[str, str]) -> None:
    if not item.parent_item_id:
        return
    match = ATTR_RE.search(item.raw_text)
    if not match:
        return
    slot_name = slugify(match.group("name"), "attribute")
    requiredness = "Required" if match.group("required").lower() == "required" else "Optional"
    # Attribute parent concept is inferred from parent definition item references; conservative source-level relation only.
    slot_id = stable_id("slot", item.id, slot_name, length=10)
    graph.spec_object(slot_id, "ConceptObject", item.span_id, "TemplateParsed")
    graph.fact("AttributeSlot", slot_id)
    graph.fact("SymbolName", slot_id, slot_name)
    parent_concepts = extract_concepts(item.raw_text)
    for concept in parent_concepts:
        cid = concept_ids.setdefault(concept, f"c-{slugify(concept)}")
        graph.fact("Attribute", cid, slot_id, requiredness, "RawText", item.raw_text)
        break


def find_parent_requirement(item: PlainItem, all_items: list[PlainItem], item_to_obl: dict[str, str]) -> PlainItem | None:
    by_id = {i.id: i for i in all_items}
    cur = item.parent_item_id
    while cur:
        if cur in item_to_obl:
            return by_id[cur]
        cur = by_id[cur].parent_item_id if cur in by_id else None
    return None


def extract_test(graph: Graph, item: PlainItem, parent_req: PlainItem | None, item_to_obl: dict[str, str]) -> None:
    test_id = stable_id("test", item.id, length=10)
    graph.spec_object(test_id, "ValidationObject", item.span_id, "TemplateParsed")
    graph.fact("TestCase", test_id)
    graph.fact("TestKind", test_id, "Acceptance")
    match = GIVEN_WHEN_THEN_RE.search(item.raw_text)
    if match:
        obs_id = stable_id("obs", item.id, match.group("then"), length=10)
        graph.fact("TestStimulus", test_id, match.group("when").strip())
        graph.fact("ExpectedObservation", test_id, obs_id)
        graph.fact("RawProposition", obs_id, match.group("then").strip())
    if parent_req and parent_req.id in item_to_obl:
        graph.fact("Covers", test_id, item_to_obl[parent_req.id])
    else:
        graph.fact("Question", stable_id("q", "test-coverage", test_id, length=10))


def validate_graph(graph: Graph) -> None:
    primary_roles: dict[str, list[str]] = {}
    derived_or_generated: set[str] = set()
    obligations = []
    propositions = set()
    assertions_missing_tv = []

    for fact in graph.facts:
        if fact[0] == "PrimaryRole":
            primary_roles.setdefault(fact[1], []).append(fact[2])
        elif fact[0] in {"DerivedFrom", "GeneratedFrom"}:
            derived_or_generated.add(fact[1])
        elif fact[0] == "Obligation":
            obligations.append(fact)
        elif fact[0] == "Proposition":
            propositions.add(fact[1])
        elif fact[0] == "Assert":
            if len(fact) != 4 or not isinstance(fact[3], dict) or fact[3].get("type") != "pbit":
                assertions_missing_tv.append(fact)

    checks = [
        ("no-role-collapse", all(len(v) == 1 for v in primary_roles.values())),
        ("all-objects-have-source-or-generator", all(obj in derived_or_generated for obj in graph.spec_objects)),
        ("all-obligations-have-propositions", all(len(o) >= 4 and o[3] in propositions for o in obligations)),
        ("assertions-have-context-and-tv", not assertions_missing_tv),
    ]
    for prop, ok in checks:
        check_id = stable_id("chk", prop, length=10)
        graph.fact("ValidationProperty", prop)
        graph.fact("Check", check_id)
        graph.fact("CheckProperty", check_id, prop)
        graph.fact("CheckMode", check_id, "Crisp")
        graph.fact("CheckStatus", check_id, "Pass" if ok else "Fail")
        if not ok:
            diag_id = stable_id("diag", prop, length=10)
            graph.fact("Diagnostic", diag_id)
            graph.fact("CheckFail", check_id, diag_id)
            graph.diagnostics.append({"id": diag_id, "property": prop, "status": "Fail"})


def to_document(graph: Graph, files: list[PlainFile]) -> dict:
    objects = list(graph.spec_objects.values())
    for obj in objects:
        oid = obj["id"]
        obj["facts"] = [f for f in graph.facts if len(f) > 1 and f[1] == oid]
        obj["assertions"] = [f for f in graph.facts if f[0] == "Assert" and f[2] == oid]
    return {
        "schema": "SpecAtom-HS-MVP",
        "schema_version": "0.3-subset",
        "files": [{"id": f.id, "path": f.path, "digest": f.digest} for f in files],
        "spans": [span.__dict__ for span in graph.spans.values()],
        "facts": graph.facts,
        "objects": objects,
        "questions": graph.questions,
        "diagnostics": graph.diagnostics,
    }

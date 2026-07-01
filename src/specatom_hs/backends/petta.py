"""Conservative PeTTa/MeTTa backend profile gates.

This module emits reified fact stubs only. Executable skeleton generation is
refused unless all input objects already have a backend-safe semantic level.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable

from ..schema import SemanticLevel, SpecDocument, SpecObject
from ..validators import FACT_SCHEMAS

SUPPORTED_REIFIED_LEVELS = {
    SemanticLevel.TEMPLATE_PARSED,
    SemanticLevel.ACTION_SCHEMA_PARSED,
    SemanticLevel.PREDICATE_PARSED,
    SemanticLevel.FORMALLY_TYPED,
    SemanticLevel.BACKEND_LOWERED,
    SemanticLevel.VERIFIED,
}
EXECUTABLE_SAFE_LEVELS = {SemanticLevel.BACKEND_LOWERED, SemanticLevel.VERIFIED}
SUPPORTED_REIFIED_FACTS = frozenset(FACT_SCHEMAS)


@dataclass(frozen=True)
class BackendRefusal:
    target: str
    reason: str
    object_id: str | None = None
    semantic_level: str | None = None


def _atom(parts: Iterable[object]) -> str:
    def enc(part: object) -> str:
        if isinstance(part, (int, float)):
            return str(part)
        s = str(part)
        if not s or any(ch.isspace() for ch in s) or any(ch in s for ch in '()"'):
            return json.dumps(s)
        return s
    return "(" + " ".join(enc(p) for p in parts) + ")"


def reified_atom_for_object(obj: SpecObject) -> str | BackendRefusal:
    """Emit a basic reified atom only for PeTTa-supported semantic levels."""
    if obj.semantic_level not in SUPPORTED_REIFIED_LEVELS:
        return BackendRefusal("petta_reified_v0", "unsupported-semantic-level-for-reified-emission", obj.id, obj.semantic_level.value)
    return _atom(["spec-object", obj.id, obj.role.value, obj.semantic_level.value])


def _profile_fact_refusal(obj: SpecObject, fact: tuple) -> BackendRefusal | None:
    if not fact:
        return BackendRefusal("petta_reified_v0", "empty-fact-tuple", obj.id, obj.semantic_level.value)
    predicate = str(fact[0])
    schema = FACT_SCHEMAS.get(predicate)
    if predicate not in SUPPORTED_REIFIED_FACTS or schema is None:
        return BackendRefusal("petta_reified_v0", f"unsupported-fact-predicate:{predicate}", obj.id, obj.semantic_level.value)
    if len(fact) != schema.arity:
        return BackendRefusal("petta_reified_v0", f"unsupported-fact-arity:{predicate}:expected-{schema.arity}:got-{len(fact)}", obj.id, obj.semantic_level.value)
    return None


def emit_reified_atoms(doc: SpecDocument) -> tuple[list[str], list[BackendRefusal]]:
    atoms = [_atom(["target-profile", "petta_reified_v0"])]
    refusals: list[BackendRefusal] = []
    for plain_file in doc.files:
        atoms.append(_atom(["plain-file", plain_file.id, plain_file.path, plain_file.digest]))
    for span in doc.spans:
        atoms.append(_atom(["source-span", span.id, span.file_id, span.start_byte, span.end_byte, span.start_line, span.end_line]))
    for section in doc.sections:
        atoms.append(_atom(["section", section.id, section.file_id, section.kind, section.ordinal]))
        atoms.append(_atom(["derived-from", section.id, section.span.id]))
    for item in doc.items:
        atoms.append(_atom(["plain-item", item.id, item.section_id, item.parent_item_id or "none", item.ordinal, item.raw_text]))
        atoms.append(_atom(["derived-from", item.id, item.span.id]))
    for obj in doc.objects:
        emitted = reified_atom_for_object(obj)
        if isinstance(emitted, BackendRefusal):
            refusals.append(emitted)
        else:
            atoms.append(emitted)
            if obj.source_span_id:
                atoms.append(_atom(["derived-from", obj.id, obj.source_span_id]))
            for fact in obj.facts:
                refusal = _profile_fact_refusal(obj, fact)
                if refusal:
                    refusals.append(refusal)
                else:
                    atoms.append(_atom(fact))
    for obligation in doc.validation_obligations:
        atoms.append(_atom(["validation-obligation", obligation.id, obligation.property, obligation.target_id]))
        atoms.append(_atom(["validation-rationale", obligation.id, obligation.rationale]))
        if obligation.source_span_id:
            atoms.append(_atom(["derived-from", obligation.id, obligation.source_span_id]))
    for check in doc.checks:
        atoms.append(_atom(["check", check.id, check.property, check.target_id, check.status.value]))
        atoms.append(_atom(["check-obligation", check.id, check.obligation_id]))
        atoms.append(_atom(["check-evidence", check.id, check.evidence]))
    return atoms, refusals


def refuse_executable_skeleton(objects: Iterable[SpecObject]) -> list[BackendRefusal]:
    """Return refusal records for every object unsafe for executable skeletons."""
    refusals: list[BackendRefusal] = []
    for obj in objects:
        if obj.semantic_level == SemanticLevel.RAW_TEXT_ONLY:
            refusals.append(BackendRefusal("petta_executable_skeleton_v0", "raw-text-only-skeleton-forbidden", obj.id, obj.semantic_level.value))
        elif obj.semantic_level not in EXECUTABLE_SAFE_LEVELS:
            refusals.append(BackendRefusal("petta_executable_skeleton_v0", "unsupported-semantic-level-for-executable-skeleton", obj.id, obj.semantic_level.value))
    return refusals

"""Conservative PeTTa/MeTTa backend profile gates.

This module emits reified fact stubs only. Executable skeleton generation is
refused unless all input objects already have a backend-safe semantic level.
"""

from __future__ import annotations

import heapq
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..schema import (
    CheckRecord,
    CheckStatus,
    PlainFile,
    PlainItem,
    Role,
    Section,
    SemanticLevel,
    SourceSpan,
    SpecDocument,
    SpecObject,
    ValidationObligation,
)
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


def _semantic_level_value(obj: SpecObject) -> str | None:
    """Return diagnostic text without trusting runtime schema annotations."""
    level = obj.semantic_level
    if isinstance(level, SemanticLevel):
        return level.value
    return None if level is None else str(level)


def _source_provenance_refusal_reason(source_span_id: object) -> str | None:
    """Return a stable reason when an object's source-span identity is invalid."""
    if source_span_id is None or source_span_id == "":
        return "missing-source-provenance"
    if not isinstance(source_span_id, str):
        return f"unsupported-source-span-id-type:{type(source_span_id).__name__}"
    if not source_span_id.strip():
        return "missing-source-provenance"
    return None


def _optional_source_provenance_refusal_reason(source_span_id: object) -> str | None:
    """Validate an optional source-span ID without treating absence as malformed."""
    if source_span_id is None or source_span_id == "":
        return None
    return _source_provenance_refusal_reason(source_span_id)


def _source_span_record_refusal_reason(span: SourceSpan) -> str | None:
    """Return the first reason a source span is unsafe to reify."""
    if not isinstance(span.id, str) or not span.id.strip():
        return "invalid-source-span-id"
    if not isinstance(span.file_id, str) or not span.file_id.strip():
        return "invalid-source-span-file-id"
    byte_fields = (span.start_byte, span.end_byte)
    if any(not isinstance(value, int) or isinstance(value, bool) for value in byte_fields):
        return "invalid-source-span-byte-bound-type"
    if span.start_byte < 0 or span.end_byte < span.start_byte:
        return "invalid-source-span-byte-bounds"
    line_fields = (span.start_line, span.end_line)
    if any(not isinstance(value, int) or isinstance(value, bool) for value in line_fields):
        return "invalid-source-span-line-bound-type"
    if span.start_line < 1 or span.end_line < span.start_line:
        return "invalid-source-span-line-bounds"
    return None


def admitted_source_span_ids(doc: SpecDocument) -> set[str]:
    """Return source-span identities that the reified manifest can emit."""
    duplicate_file_ids = _duplicate_record_ids(doc.files, PlainFile)
    emitted_file_ids = {
        plain_file.id
        for plain_file in doc.files
        if isinstance(plain_file, PlainFile)
        and _plain_file_record_refusal_reason(plain_file) is None
        and plain_file.id not in duplicate_file_ids
    }
    duplicate_span_ids = _duplicate_record_ids(doc.spans, SourceSpan)
    return {
        span.id
        for span in doc.spans
        if isinstance(span, SourceSpan)
        and _source_span_record_refusal_reason(span) is None
        and span.id not in duplicate_span_ids
        and span.file_id in emitted_file_ids
    }


def _plain_file_record_refusal_reason(plain_file: PlainFile) -> str | None:
    """Return the first reason a source file is unsafe to reify."""
    if not isinstance(plain_file.id, str) or not plain_file.id.strip():
        return "invalid-plain-file-id"
    if not isinstance(plain_file.path, str) or not plain_file.path.strip():
        return "invalid-plain-file-path"
    if not isinstance(plain_file.digest, str) or not plain_file.digest.strip():
        return "invalid-plain-file-digest"
    return None


def _section_record_refusal_reason(section: Section) -> str | None:
    """Return the first reason a section is unsafe to reify."""
    if not isinstance(section.id, str) or not section.id.strip():
        return "invalid-section-id"
    if not isinstance(section.file_id, str) or not section.file_id.strip():
        return "invalid-section-file-id"
    if not isinstance(section.kind, str) or not section.kind.strip():
        return "invalid-section-kind"
    if not isinstance(section.ordinal, int) or isinstance(section.ordinal, bool):
        return "invalid-section-ordinal-type"
    if section.ordinal < 0:
        return "invalid-section-ordinal"
    if not isinstance(section.span, SourceSpan):
        return "invalid-section-span-record"
    if not isinstance(section.span.id, str) or not section.span.id.strip():
        return "invalid-section-span-id"
    return None


def _plain_item_record_refusal_reason(item: PlainItem) -> str | None:
    """Return the first reason a Plain item is unsafe to reify."""
    if not isinstance(item.id, str) or not item.id.strip():
        return "invalid-plain-item-id"
    if not isinstance(item.file_id, str) or not item.file_id.strip():
        return "invalid-plain-item-file-id"
    if not isinstance(item.section_id, str) or not item.section_id.strip():
        return "invalid-plain-item-section-id"
    if item.parent_item_id is not None and (
        not isinstance(item.parent_item_id, str) or not item.parent_item_id.strip()
    ):
        return "invalid-plain-item-parent-id"
    if not isinstance(item.ordinal, int) or isinstance(item.ordinal, bool):
        return "invalid-plain-item-ordinal-type"
    if item.ordinal < 0:
        return "invalid-plain-item-ordinal"
    if not isinstance(item.level, int) or isinstance(item.level, bool):
        return "invalid-plain-item-level-type"
    if item.level < 0:
        return "invalid-plain-item-level"
    if not isinstance(item.raw_text, str) or not item.raw_text.strip():
        return "invalid-plain-item-raw-text"
    if not isinstance(item.span, SourceSpan):
        return "invalid-plain-item-span-record"
    if not isinstance(item.span.id, str) or not item.span.id.strip():
        return "invalid-plain-item-span-id"
    return None


def _duplicate_record_ids(records: Iterable[object], record_type: type) -> set[str]:
    """Return safe string IDs that occur more than once for one record type."""
    counts: dict[str, int] = {}
    for record in records:
        if not isinstance(record, record_type):
            continue
        record_id = record.id
        if isinstance(record_id, str) and record_id.strip():
            counts[record_id] = counts.get(record_id, 0) + 1
    return {record_id for record_id, count in counts.items() if count > 1}


def _validation_obligation_identity_refusal_reason(obligation_id: object) -> str | None:
    """Return a stable reason when a validation obligation has no safe ID."""
    if not isinstance(obligation_id, str):
        return f"unsupported-validation-obligation-id-type:{type(obligation_id).__name__}"
    if not obligation_id.strip():
        return "missing-validation-obligation-id"
    return None


def _validation_obligation_property_refusal_reason(property_name: object) -> str | None:
    """Return a stable reason when an obligation property is not a safe symbol."""
    if not isinstance(property_name, str):
        return f"unsupported-validation-obligation-property-type:{type(property_name).__name__}"
    if not property_name.strip():
        return "missing-validation-obligation-property"
    return None


def _validation_obligation_target_identity_refusal_reason(target_id: object) -> str | None:
    """Return a stable reason when an obligation cannot safely name its target."""
    if not isinstance(target_id, str):
        return f"unsupported-validation-obligation-target-id-type:{type(target_id).__name__}"
    if not target_id.strip():
        return "missing-validation-obligation-target-id"
    return None


def _validation_obligation_rationale_refusal_reason(rationale: object) -> str | None:
    """Return a stable reason when an obligation has no reviewable rationale."""
    if not isinstance(rationale, str):
        return f"unsupported-validation-obligation-rationale-type:{type(rationale).__name__}"
    if not rationale.strip():
        return "missing-validation-obligation-rationale"
    return None


def _check_identity_refusal_reason(check_id: object) -> str | None:
    """Return a stable reason when a validation check has no safe ID."""
    if not isinstance(check_id, str):
        return f"unsupported-check-id-type:{type(check_id).__name__}"
    if not check_id.strip():
        return "missing-check-id"
    return None


def _check_obligation_identity_refusal_reason(obligation_id: object) -> str | None:
    """Return a stable reason when a check cannot safely name its obligation."""
    if not isinstance(obligation_id, str):
        return f"unsupported-check-obligation-id-type:{type(obligation_id).__name__}"
    if not obligation_id.strip():
        return "missing-check-obligation-id"
    return None


def _check_status_refusal_reason(status: object) -> str | None:
    """Return a stable reason when a check status is not schema-declared."""
    if not isinstance(status, CheckStatus):
        return f"unsupported-check-status-type:{type(status).__name__}"
    return None


def _check_property_refusal_reason(property_name: object) -> str | None:
    """Return a stable reason when a check property is not a safe symbol."""
    if not isinstance(property_name, str):
        return f"unsupported-check-property-type:{type(property_name).__name__}"
    if not property_name.strip():
        return "missing-check-property"
    return None


def _check_target_identity_refusal_reason(target_id: object) -> str | None:
    """Return a stable reason when a check cannot safely name its target."""
    if not isinstance(target_id, str):
        return f"unsupported-check-target-id-type:{type(target_id).__name__}"
    if not target_id.strip():
        return "missing-check-target-id"
    return None


def _check_evidence_refusal_reason(evidence: object) -> str | None:
    """Return a stable reason when check evidence is not reviewable text."""
    if not isinstance(evidence, str):
        return f"unsupported-check-evidence-type:{type(evidence).__name__}"
    if not evidence.strip():
        return "missing-check-evidence"
    return None


def _atom(parts: Iterable[object]) -> str:
    def enc(part: object) -> str:
        if isinstance(part, (int, float)):
            return str(part)
        s = str(part)
        # Semicolons start comments in MeTTa source.  Leaving one bare can
        # silently truncate a generated atom, so treat it as syntax just like
        # parentheses and quotes.
        if (
            not s
            or any(ch.isspace() for ch in s)
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in s)
            or any(ch in s for ch in '();"')
        ):
            return json.dumps(s)
        return s
    return "(" + " ".join(enc(p) for p in parts) + ")"


def reified_atom_for_object(obj: SpecObject) -> str | BackendRefusal:
    """Emit a basic reified atom only for PeTTa-supported semantic levels."""
    if not isinstance(obj.id, str):
        return BackendRefusal(
            "petta_reified_v0",
            f"unsupported-object-id-type-for-reified-emission:{type(obj.id).__name__}",
            str(obj.id),
            _semantic_level_value(obj),
        )
    if not obj.id.strip():
        return BackendRefusal(
            "petta_reified_v0",
            "missing-object-id-for-reified-emission",
            obj.id,
            _semantic_level_value(obj),
        )
    if not isinstance(obj.role, Role):
        return BackendRefusal(
            "petta_reified_v0",
            f"unsupported-object-role-type-for-reified-emission:{type(obj.role).__name__}",
            obj.id,
            _semantic_level_value(obj),
        )
    if not isinstance(obj.semantic_level, SemanticLevel):
        return BackendRefusal(
            "petta_reified_v0",
            f"unsupported-semantic-level-type-for-reified-emission:{type(obj.semantic_level).__name__}",
            obj.id,
            _semantic_level_value(obj),
        )
    if obj.semantic_level not in SUPPORTED_REIFIED_LEVELS:
        return BackendRefusal("petta_reified_v0", "unsupported-semantic-level-for-reified-emission", obj.id, _semantic_level_value(obj))
    if not isinstance(obj.facts, list):
        return BackendRefusal(
            "petta_reified_v0",
            f"unsupported-object-facts-container-type:{type(obj.facts).__name__}",
            obj.id,
            _semantic_level_value(obj),
        )
    return _atom(["spec-object", obj.id, obj.role.value, _semantic_level_value(obj)])


def _profile_fact_refusal(obj: SpecObject, fact: object) -> BackendRefusal | None:
    if not isinstance(fact, tuple):
        return BackendRefusal(
            "petta_reified_v0",
            f"unsupported-fact-record-type:{type(fact).__name__}",
            obj.id,
            _semantic_level_value(obj),
        )
    if not fact:
        return BackendRefusal("petta_reified_v0", "empty-fact-tuple", obj.id, _semantic_level_value(obj))
    if not isinstance(fact[0], str):
        return BackendRefusal(
            "petta_reified_v0",
            f"unsupported-fact-predicate-type:{type(fact[0]).__name__}",
            obj.id,
            _semantic_level_value(obj),
        )
    predicate = fact[0]
    schema = FACT_SCHEMAS.get(predicate)
    if predicate not in SUPPORTED_REIFIED_FACTS or schema is None:
        return BackendRefusal("petta_reified_v0", f"unsupported-fact-predicate:{predicate}", obj.id, _semantic_level_value(obj))
    if len(fact) != schema.arity:
        return BackendRefusal("petta_reified_v0", f"unsupported-fact-arity:{predicate}:expected-{schema.arity}:got-{len(fact)}", obj.id, _semantic_level_value(obj))
    if schema.subject_pos is not None:
        subject = fact[schema.subject_pos]
        if not isinstance(subject, str):
            return BackendRefusal(
                "petta_reified_v0",
                f"unsupported-fact-subject-type:{predicate}:position-{schema.subject_pos}:{type(subject).__name__}",
                obj.id,
                _semantic_level_value(obj),
            )
        if subject != obj.id:
            return BackendRefusal("petta_reified_v0", f"fact-subject-mismatch:{predicate}:expected-{obj.id}:got-{subject}", obj.id, _semantic_level_value(obj))
    for position, value in enumerate(fact[1:], start=1):
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            return BackendRefusal("petta_reified_v0", f"unsupported-fact-argument-type:{predicate}:position-{position}:{type(value).__name__}", obj.id, _semantic_level_value(obj))
        if position in schema.object_refs:
            if value is not None and not isinstance(value, str):
                return BackendRefusal("petta_reified_v0", f"unsupported-object-reference-type:{predicate}:position-{position}:{type(value).__name__}", obj.id, _semantic_level_value(obj))
            if value is None or not str(value).strip():
                return BackendRefusal("petta_reified_v0", f"empty-object-reference:{predicate}:position-{position}", obj.id, _semantic_level_value(obj))
            continue
        if value is None or not str(value).strip():
            return BackendRefusal("petta_reified_v0", f"empty-fact-argument:{predicate}:position-{position}", obj.id, _semantic_level_value(obj))
        if isinstance(value, float) and not math.isfinite(value):
            return BackendRefusal("petta_reified_v0", f"non-finite-fact-argument:{predicate}:position-{position}", obj.id, _semantic_level_value(obj))
    return None


def _compute_information_flow_summary(doc: SpecDocument) -> dict[str, int]:
    """Compute quick graph stats from DataFlowEdge and TemporalOrderEdge facts."""
    data_edges: list[tuple[str, str, str]] = []  # (source, target, direction)
    temporal_edges: list[tuple[str, str]] = []  # (source, target)

    for obj in doc.objects:
        if not isinstance(obj, SpecObject):
            continue
        if not isinstance(obj.facts, list):
            continue
        for fact in obj.facts:
            if not isinstance(fact, tuple) or len(fact) < 2:
                continue
            predicate = str(fact[0])
            if predicate == "DataFlowEdge" and len(fact) == 5:
                # (DataFlowEdge, edge_id, source, target, direction)
                data_edges.append((str(fact[2]), str(fact[3]), str(fact[4])))
            elif predicate == "TemporalOrderEdge" and len(fact) == 4:
                # (TemporalOrderEdge, edge_id, before, after)
                temporal_edges.append((str(fact[2]), str(fact[3])))

    nodes: set[str] = set()
    for src, tgt, _ in data_edges:
        nodes.add(src)
        nodes.add(tgt)
    for src, tgt in temporal_edges:
        nodes.add(src)
        nodes.add(tgt)

    # Adjacency for cycle/component detection
    adj: dict[str, set[str]] = {n: set() for n in nodes}
    for src, tgt, _ in data_edges:
        adj.setdefault(src, set()).add(tgt)
        adj.setdefault(tgt, set())

    # Undirected adjacency for connected components
    undirected: dict[str, set[str]] = {n: set() for n in nodes}
    for src, tgt, _ in data_edges:
        undirected.setdefault(src, set()).add(tgt)
        undirected.setdefault(tgt, set()).add(src)

    # Source/sink from directed graph
    all_targets = {tgt for _, tgt, _ in data_edges}
    all_sources = {src for src, _, _ in data_edges}
    source_nodes = {n for n in nodes if n not in all_targets} if nodes else set()
    sink_nodes = {n for n in nodes if n not in all_sources} if nodes else set()

    # Cycle detection (DFS white/gray/black)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}
    cycle_count = 0

    def _dfs_cycle(start: str) -> None:
        nonlocal cycle_count
        stack: list[tuple[str, int]] = [(start, 0)]
        color[start] = GRAY
        while stack:
            node, idx = stack[-1]
            neighbors = sorted(adj.get(node, set()))
            if idx < len(neighbors):
                stack[-1] = (node, idx + 1)
                nb = neighbors[idx]
                if color.get(nb, WHITE) == GRAY:
                    cycle_count += 1
                elif color.get(nb, WHITE) == WHITE:
                    color[nb] = GRAY
                    stack.append((nb, 0))
            else:
                stack.pop()
                color[node] = BLACK

    for n in sorted(nodes):
        if color.get(n, WHITE) == WHITE:
            _dfs_cycle(n)

    # Connected components (undirected BFS)
    visited: set[str] = set()
    component_count = 0
    for n in sorted(nodes):
        if n in visited:
            continue
        component_count += 1
        queue = [n]
        visited.add(n)
        while queue:
            current = queue.pop(0)
            for nb in sorted(undirected.get(current, set())):
                if nb not in visited:
                    visited.add(nb)
                    queue.append(nb)

    # Max depth (longest path in DAG if acyclic)
    max_depth = 0
    if cycle_count == 0 and nodes:
        in_degree = {n: 0 for n in nodes}
        for src, tgt, _ in data_edges:
            in_degree[tgt] = in_degree.get(tgt, 0) + 1
        topo_order: list[str] = [n for n in sorted(nodes) if in_degree.get(n, 0) == 0]
        depth = {n: 0 for n in nodes}
        queue = list(topo_order)
        while queue:
            current = queue.pop(0)
            for nb in sorted(adj.get(current, set())):
                depth[nb] = max(depth.get(nb, 0), depth.get(current, 0) + 1)
                max_depth = max(max_depth, depth[nb])
                in_degree[nb] -= 1
                if in_degree[nb] == 0:
                    queue.append(nb)

    # Bottleneck nodes (high fan-in AND high fan-out, >=3 each)
    in_count: dict[str, int] = {}
    out_count: dict[str, int] = {}
    for src, tgt, _ in data_edges:
        out_count[src] = out_count.get(src, 0) + 1
        in_count[tgt] = in_count.get(tgt, 0) + 1
    bottleneck_count = sum(1 for n in nodes if in_count.get(n, 0) >= 3 and out_count.get(n, 0) >= 3)

    return {
        "node_count": len(nodes),
        "edge_count": len(data_edges),
        "temporal_edge_count": len(temporal_edges),
        "source_count": len(source_nodes),
        "sink_count": len(sink_nodes),
        "cycle_count": cycle_count,
        "component_count": component_count,
        "max_depth": max_depth,
        "bottleneck_count": bottleneck_count,
    }


def emit_reified_atoms(doc: SpecDocument) -> tuple[list[str], list[BackendRefusal]]:
    atoms = [_atom(["target-profile", "petta_reified_v0"])]
    refusals: list[BackendRefusal] = []
    duplicate_file_ids = _duplicate_record_ids(doc.files, PlainFile)
    emitted_files: list[PlainFile] = []
    for plain_file in doc.files:
        if not isinstance(plain_file, PlainFile):
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    f"unsupported-plain-file-record-type:{type(plain_file).__name__}",
                )
            )
            continue
        file_refusal = _plain_file_record_refusal_reason(plain_file)
        if file_refusal:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    file_refusal,
                    None if plain_file.id is None else str(plain_file.id),
                )
            )
            continue
        if plain_file.id in duplicate_file_ids:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "duplicate-plain-file-id",
                    plain_file.id,
                )
            )
            continue
        atoms.append(_atom(["plain-file", plain_file.id, plain_file.path, plain_file.digest]))
        emitted_files.append(plain_file)
    duplicate_span_ids = _duplicate_record_ids(doc.spans, SourceSpan)
    emitted_file_ids = {plain_file.id for plain_file in emitted_files}
    emitted_spans: dict[str, SourceSpan] = {}
    for span in doc.spans:
        if not isinstance(span, SourceSpan):
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    f"unsupported-source-span-record-type:{type(span).__name__}",
                )
            )
            continue
        span_refusal = _source_span_record_refusal_reason(span)
        if span_refusal:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    span_refusal,
                    None if span.id is None else str(span.id),
                )
            )
            continue
        if span.id in duplicate_span_ids:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "duplicate-source-span-id",
                    span.id,
                )
            )
            continue
        if span.file_id not in emitted_file_ids:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "source-span-file-not-emitted",
                    span.id,
                )
            )
            continue
        atoms.append(_atom(["source-span", span.id, span.file_id, span.start_byte, span.end_byte, span.start_line, span.end_line]))
        emitted_spans[span.id] = span
    duplicate_section_ids = _duplicate_record_ids(doc.sections, Section)
    emitted_sections: dict[str, Section] = {}
    for section in doc.sections:
        if not isinstance(section, Section):
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    f"unsupported-section-record-type:{type(section).__name__}",
                )
            )
            continue
        section_refusal = _section_record_refusal_reason(section)
        if section_refusal:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    section_refusal,
                    None if section.id is None else str(section.id),
                )
            )
            continue
        if section.id in duplicate_section_ids:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "duplicate-section-id",
                    section.id,
                )
            )
            continue
        if section.file_id not in emitted_file_ids:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "section-file-not-emitted",
                    section.id,
                )
            )
            continue
        if section.span.id not in emitted_spans:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "section-span-not-emitted",
                    section.id,
                )
            )
            continue
        if emitted_spans[section.span.id].file_id != section.file_id:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "section-span-file-mismatch",
                    section.id,
                )
            )
            continue
        atoms.append(_atom(["section", section.id, section.file_id, section.kind, section.ordinal]))
        atoms.append(_atom(["derived-from", section.id, section.span.id]))
        emitted_sections[section.id] = section
    duplicate_item_ids = _duplicate_record_ids(doc.items, PlainItem)
    candidate_items: list[PlainItem] = []
    for item in doc.items:
        if not isinstance(item, PlainItem):
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    f"unsupported-plain-item-record-type:{type(item).__name__}",
                )
            )
            continue
        item_refusal = _plain_item_record_refusal_reason(item)
        if item_refusal:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    item_refusal,
                    None if item.id is None else str(item.id),
                )
            )
            continue
        if item.id in duplicate_item_ids:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "duplicate-plain-item-id",
                    item.id,
                )
            )
            continue
        if item.file_id not in emitted_file_ids:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "plain-item-file-not-emitted",
                    item.id,
                )
            )
            continue
        if item.section_id not in emitted_sections:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "plain-item-section-not-emitted",
                    item.id,
                )
            )
            continue
        if item.span.id not in emitted_spans:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "plain-item-span-not-emitted",
                    item.id,
                )
            )
            continue
        if emitted_sections[item.section_id].file_id != item.file_id:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "plain-item-section-file-mismatch",
                    item.id,
                )
            )
            continue
        if emitted_spans[item.span.id].file_id != item.file_id:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "plain-item-span-file-mismatch",
                    item.id,
                )
            )
            continue
        candidate_items.append(item)

    emitted_items = {item.id: item for item in candidate_items}
    while True:
        parent_refusals: list[tuple[PlainItem, str]] = []
        for item in candidate_items:
            if item.id not in emitted_items or item.parent_item_id is None:
                continue
            if item.parent_item_id == item.id:
                parent_refusals.append((item, "plain-item-self-parent"))
                continue
            parent = emitted_items.get(item.parent_item_id)
            if parent is None:
                parent_refusals.append((item, "plain-item-parent-not-emitted"))
            elif parent.file_id != item.file_id:
                parent_refusals.append((item, "plain-item-parent-file-mismatch"))
            elif parent.section_id != item.section_id:
                parent_refusals.append((item, "plain-item-parent-section-mismatch"))
        if not parent_refusals:
            break
        for item, reason in parent_refusals:
            if emitted_items.pop(item.id, None) is not None:
                refusals.append(
                    BackendRefusal("petta_reified_v0", reason, item.id)
                )

    for item in candidate_items:
        if item.id not in emitted_items:
            continue
        atoms.append(_atom(["plain-item", item.id, item.section_id, item.parent_item_id or "none", item.ordinal, item.raw_text]))
        atoms.append(_atom(["derived-from", item.id, item.span.id]))
    object_id_counts: dict[str, int] = {}
    for obj in doc.objects:
        if not isinstance(obj, SpecObject):
            continue
        if isinstance(obj.id, str) and obj.id.strip():
            object_id_counts[obj.id] = object_id_counts.get(obj.id, 0) + 1
    duplicate_object_ids = {
        object_id for object_id, count in object_id_counts.items() if count > 1
    }
    emitted_objects: list[SpecObject] = []
    for obj in doc.objects:
        if not isinstance(obj, SpecObject):
            refusals.append(BackendRefusal("petta_reified_v0", f"unsupported-spec-object-record-type:{type(obj).__name__}"))
            continue
        if isinstance(obj.id, str) and obj.id in duplicate_object_ids:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "duplicate-object-id-for-reified-emission",
                    obj.id,
                    _semantic_level_value(obj),
                )
            )
            continue
        emitted = reified_atom_for_object(obj)
        if isinstance(emitted, BackendRefusal):
            refusals.append(emitted)
        else:
            atoms.append(emitted)
            emitted_objects.append(obj)
            provenance_refusal = _optional_source_provenance_refusal_reason(
                obj.source_span_id
            )
            if provenance_refusal:
                refusals.append(
                    BackendRefusal(
                        "petta_reified_v0",
                        f"{provenance_refusal}-for-reified-emission",
                        obj.id,
                        _semantic_level_value(obj),
                    )
                )
            elif (
                doc.spans
                and obj.source_span_id
                and obj.source_span_id not in emitted_spans
            ):
                refusals.append(
                    BackendRefusal(
                        "petta_reified_v0",
                        "object-source-span-not-emitted",
                        obj.id,
                        _semantic_level_value(obj),
                    )
                )
            elif obj.source_span_id:
                atoms.append(_atom(["derived-from", obj.id, obj.source_span_id]))
            for fact in obj.facts:
                refusal = _profile_fact_refusal(obj, fact)
                if refusal:
                    refusals.append(refusal)
                else:
                    atoms.append(_atom(fact))
    valid_obligations: list[ValidationObligation] = []
    for obligation in doc.validation_obligations:
        if not isinstance(obligation, ValidationObligation):
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    f"unsupported-validation-obligation-record-type:{type(obligation).__name__}",
                )
            )
            continue
        valid_obligations.append(obligation)
    obligation_id_counts: dict[str, int] = {}
    for obligation in valid_obligations:
        if isinstance(obligation.id, str) and obligation.id.strip():
            obligation_id_counts[obligation.id] = obligation_id_counts.get(obligation.id, 0) + 1
    duplicate_obligation_ids = {
        obligation_id
        for obligation_id, count in obligation_id_counts.items()
        if count > 1
    }
    emitted_obligations: dict[str, ValidationObligation] = {}
    for obligation in valid_obligations:
        identity_refusal = _validation_obligation_identity_refusal_reason(obligation.id)
        if identity_refusal:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    identity_refusal,
                    None if obligation.id is None else str(obligation.id),
                )
            )
            continue
        if obligation.id in duplicate_obligation_ids:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "duplicate-validation-obligation-id",
                    obligation.id,
                )
            )
            continue
        property_refusal = _validation_obligation_property_refusal_reason(
            obligation.property
        )
        if property_refusal:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    property_refusal,
                    obligation.id,
                )
            )
            continue
        target_identity_refusal = _validation_obligation_target_identity_refusal_reason(
            obligation.target_id
        )
        if target_identity_refusal:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    target_identity_refusal,
                    obligation.id,
                )
            )
            continue
        rationale_refusal = _validation_obligation_rationale_refusal_reason(
            obligation.rationale
        )
        if rationale_refusal:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    rationale_refusal,
                    obligation.id,
                )
            )
            continue
        atoms.append(_atom(["validation-obligation", obligation.id, obligation.property, obligation.target_id]))
        atoms.append(_atom(["validation-rationale", obligation.id, obligation.rationale]))
        emitted_obligations[obligation.id] = obligation
        provenance_refusal = _optional_source_provenance_refusal_reason(
            obligation.source_span_id
        )
        if provenance_refusal:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    f"{provenance_refusal}-for-validation-obligation",
                    obligation.id,
                )
            )
        elif (
            doc.spans
            and obligation.source_span_id
            and obligation.source_span_id not in emitted_spans
        ):
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "validation-obligation-source-span-not-emitted",
                    obligation.id,
                )
            )
        elif obligation.source_span_id:
            atoms.append(_atom(["derived-from", obligation.id, obligation.source_span_id]))
    valid_checks: list[CheckRecord] = []
    for check in doc.checks:
        if not isinstance(check, CheckRecord):
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    f"unsupported-check-record-type:{type(check).__name__}",
                )
            )
            continue
        valid_checks.append(check)
    check_id_counts: dict[str, int] = {}
    for check in valid_checks:
        if isinstance(check.id, str) and check.id.strip():
            check_id_counts[check.id] = check_id_counts.get(check.id, 0) + 1
    duplicate_check_ids = {
        check_id for check_id, count in check_id_counts.items() if count > 1
    }
    emitted_checks = []
    for check in valid_checks:
        identity_refusal = _check_identity_refusal_reason(check.id)
        if identity_refusal:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    identity_refusal,
                    None if check.id is None else str(check.id),
                )
            )
            continue
        if check.id in duplicate_check_ids:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "duplicate-check-id",
                    check.id,
                )
            )
            continue
        obligation_identity_refusal = _check_obligation_identity_refusal_reason(
            check.obligation_id
        )
        if obligation_identity_refusal:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    obligation_identity_refusal,
                    check.id,
                )
            )
            continue
        if check.obligation_id not in emitted_obligations:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    f"check-obligation-not-emitted:{check.obligation_id}",
                    check.id,
                )
            )
            continue
        property_refusal = _check_property_refusal_reason(check.property)
        if property_refusal:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    property_refusal,
                    check.id,
                )
            )
            continue
        target_identity_refusal = _check_target_identity_refusal_reason(
            check.target_id
        )
        if target_identity_refusal:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    target_identity_refusal,
                    check.id,
                )
            )
            continue
        emitted_obligation = emitted_obligations[check.obligation_id]
        if check.property != emitted_obligation.property:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "check-property-mismatch-with-obligation",
                    check.id,
                )
            )
            continue
        if check.target_id != emitted_obligation.target_id:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    "check-target-mismatch-with-obligation",
                    check.id,
                )
            )
            continue
        status_refusal = _check_status_refusal_reason(check.status)
        if status_refusal:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    status_refusal,
                    check.id,
                )
            )
            continue
        evidence_refusal = _check_evidence_refusal_reason(check.evidence)
        if evidence_refusal:
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    evidence_refusal,
                    check.id,
                )
            )
            continue
        status_value = check.status.value
        atoms.append(_atom(["check", check.id, check.property, check.target_id, status_value]))
        atoms.append(_atom(["check-obligation", check.id, check.obligation_id]))
        atoms.append(_atom(["check-evidence", check.id, check.evidence]))
        emitted_checks.append(check)

    # Count only records actually emitted so the summary cannot assert the
    # presence of refused checks.
    pass_count = sum(1 for c in emitted_checks if hasattr(c.status, "value") and c.status.value == "Pass")
    fail_count = sum(1 for c in emitted_checks if hasattr(c.status, "value") and c.status.value == "Fail")
    unknown_count = sum(1 for c in emitted_checks if hasattr(c.status, "value") and c.status.value == "Unknown")
    question_count = sum(
        1 for obj in emitted_objects if obj.role == Role.QUESTION_OBJECT
    )
    summary_id = emitted_files[0].id if emitted_files else "document"
    atoms.append(_atom(["document-validation-summary", summary_id, pass_count, fail_count, unknown_count, question_count]))

    # Information-flow graph summary: quick stats from DataFlowEdge/TemporalOrderEdge atoms.
    graph_summary = _compute_information_flow_summary(doc)
    atoms.append(_atom(["information-flow-graph-summary", summary_id,
                         graph_summary["node_count"], graph_summary["edge_count"],
                         graph_summary["temporal_edge_count"], graph_summary["source_count"],
                         graph_summary["sink_count"], graph_summary["cycle_count"],
                         graph_summary["component_count"], graph_summary["max_depth"],
                         graph_summary["bottleneck_count"]]))

    return atoms, refusals


def emit_reified_atoms_grouped(doc: SpecDocument) -> tuple[list[str], list[BackendRefusal]]:
    """Emit PeTTa reified atoms with comment separators for easier inspection.

    The underlying atom/refusal generation is delegated to ``emit_reified_atoms``
    so the existing backend behavior remains the source of truth.
    """
    atoms, refusals = emit_reified_atoms(doc)

    grouped: list[str] = []

    def add_section(title: str, selected: list[str]) -> None:
        grouped.append(f";;; {title}")
        grouped.extend(selected)

    source_prefixes = ("(target-profile", "(plain-file", "(source-span")
    section_prefixes = ("(section", "(plain-item", "(derived-from")
    object_prefixes = tuple(
        prefix
        for prefix in {atom.split(" ", 1)[0] for atom in atoms}
        if prefix not in {"(target-profile", "(plain-file", "(source-span", "(section", "(plain-item", "(derived-from", "(validation-obligation", "(validation-rationale", "(check", "(check-obligation", "(check-evidence", "(document-validation-summary", "(information-flow-graph-summary"}
    )
    validation_prefixes = ("(validation-obligation", "(validation-rationale", "(check", "(check-obligation", "(check-evidence", "(document-validation-summary", "(information-flow-graph-summary")

    add_section("Source Files", [atom for atom in atoms if atom.startswith(source_prefixes)])
    add_section("Sections", [atom for atom in atoms if atom.startswith(section_prefixes)])
    add_section("Objects", [atom for atom in atoms if atom.startswith(object_prefixes)])
    add_section("Validation", [atom for atom in atoms if atom.startswith(validation_prefixes)])
    add_section("Refusals", [f"; refused: {refusal.reason} {refusal.object_id or ''}".rstrip() for refusal in refusals])

    return grouped, refusals


def emit_metta_file(doc: SpecDocument, path: str) -> None:
    """Write grouped PeTTa/MeTTa atoms to ``path``."""
    atoms, _ = emit_reified_atoms_grouped(doc)
    Path(path).write_text("\n".join(atoms) + "\n", encoding="utf-8")


def refuse_executable_skeleton(objects: Iterable[SpecObject]) -> list[BackendRefusal]:
    """Return refusal records for every object unsafe for executable skeletons.

    A backend-safe semantic-level label is necessary but not sufficient: facts must
    also satisfy the frozen reified profile before executable lowering is allowed.
    """
    object_list = list(objects)
    declared_objects: dict[str, SpecObject] = {}
    duplicate_object_ids: set[str] = set()
    for obj in object_list:
        if not isinstance(obj.id, str):
            continue
        if obj.id in declared_objects:
            duplicate_object_ids.add(obj.id)
        else:
            declared_objects[obj.id] = obj
    declared_object_ids = set(declared_objects)
    refusals: list[BackendRefusal] = []
    for obj in object_list:
        if not isinstance(obj.id, str):
            refusals.append(
                BackendRefusal(
                    "petta_executable_skeleton_v0",
                    f"unsupported-object-id-type-for-executable-skeleton:{type(obj.id).__name__}",
                    str(obj.id),
                    _semantic_level_value(obj),
                )
            )
            continue
        if not obj.id or not obj.id.strip():
            refusals.append(BackendRefusal("petta_executable_skeleton_v0", "missing-object-id-for-executable-skeleton", obj.id, _semantic_level_value(obj)))
            continue
        if not isinstance(obj.role, Role):
            refusals.append(
                BackendRefusal(
                    "petta_executable_skeleton_v0",
                    f"unsupported-object-role-type-for-executable-skeleton:{type(obj.role).__name__}",
                    obj.id,
                    _semantic_level_value(obj),
                )
            )
            continue
        if not isinstance(obj.semantic_level, SemanticLevel):
            refusals.append(
                BackendRefusal(
                    "petta_executable_skeleton_v0",
                    f"unsupported-semantic-level-type-for-executable-skeleton:{type(obj.semantic_level).__name__}",
                    obj.id,
                    _semantic_level_value(obj),
                )
            )
            continue
        if obj.id in duplicate_object_ids:
            refusals.append(BackendRefusal("petta_executable_skeleton_v0", "duplicate-object-id-for-executable-skeleton", obj.id, _semantic_level_value(obj)))
            continue
        if obj.semantic_level == SemanticLevel.RAW_TEXT_ONLY:
            refusals.append(BackendRefusal("petta_executable_skeleton_v0", "raw-text-only-skeleton-forbidden", obj.id, _semantic_level_value(obj)))
            continue
        if obj.semantic_level not in EXECUTABLE_SAFE_LEVELS:
            refusals.append(BackendRefusal("petta_executable_skeleton_v0", "unsupported-semantic-level-for-executable-skeleton", obj.id, _semantic_level_value(obj)))
            continue
        provenance_refusal = _source_provenance_refusal_reason(obj.source_span_id)
        if provenance_refusal is not None:
            reason = (
                "missing-source-provenance-for-executable-skeleton"
                if provenance_refusal == "missing-source-provenance"
                else f"{provenance_refusal}-for-executable-skeleton"
            )
            refusals.append(BackendRefusal("petta_executable_skeleton_v0", reason, obj.id, _semantic_level_value(obj)))
            continue
        if not obj.facts:
            refusals.append(BackendRefusal("petta_executable_skeleton_v0", "missing-profile-facts-for-executable-skeleton", obj.id, _semantic_level_value(obj)))
            continue
        # Refusal records are diagnostics, so their order must not depend on the
        # insertion order used to construct otherwise-equivalent fact lists.
        for fact in sorted(
            obj.facts,
            key=lambda candidate: (
                type(candidate).__name__,
                tuple(str(part) for part in candidate)
                if isinstance(candidate, tuple)
                else (str(candidate),),
            ),
        ):
            if not isinstance(fact, tuple):
                profile_refusal = _profile_fact_refusal(obj, fact)
                refusals.append(
                    BackendRefusal(
                        "petta_executable_skeleton_v0",
                        f"unsafe-profile-fact:{profile_refusal.reason}",
                        obj.id,
                        _semantic_level_value(obj),
                    )
                )
                continue
            predicate = str(fact[0]) if fact else ""
            schema = FACT_SCHEMAS.get(predicate)
            if schema is not None and len(fact) == schema.arity:
                empty_reference = next(
                    (position for position in schema.object_refs if fact[position] is None or not str(fact[position]).strip()),
                    None,
                )
                if empty_reference is not None:
                    refusals.append(
                        BackendRefusal(
                            "petta_executable_skeleton_v0",
                            f"unsafe-profile-fact:empty-object-reference:{predicate}",
                            obj.id,
                            _semantic_level_value(obj),
                        )
                    )
                    continue
            profile_refusal = _profile_fact_refusal(obj, fact)
            if profile_refusal is not None:
                refusals.append(
                    BackendRefusal(
                        "petta_executable_skeleton_v0",
                        f"unsafe-profile-fact:{profile_refusal.reason}",
                        obj.id,
                        _semantic_level_value(obj),
                    )
                )
                continue
            schema = FACT_SCHEMAS[str(fact[0])]
            for position in schema.object_refs:
                referenced_id = str(fact[position])
                if not referenced_id.strip():
                    refusals.append(
                        BackendRefusal(
                            "petta_executable_skeleton_v0",
                            f"unsafe-profile-fact:empty-object-reference:{fact[0]}",
                            obj.id,
                            _semantic_level_value(obj),
                        )
                    )
                    continue
                if referenced_id not in declared_object_ids:
                    refusals.append(
                        BackendRefusal(
                            "petta_executable_skeleton_v0",
                            f"unsafe-profile-fact:dangling-object-reference:{fact[0]}:{referenced_id}",
                            obj.id,
                            _semantic_level_value(obj),
                        )
                    )
                    continue
                if referenced_id in duplicate_object_ids:
                    refusals.append(
                        BackendRefusal(
                            "petta_executable_skeleton_v0",
                            f"unsafe-profile-fact:ambiguous-object-reference:{fact[0]}:{referenced_id}",
                            obj.id,
                            _semantic_level_value(obj),
                        )
                    )
                    continue
                referenced_object = declared_objects[referenced_id]
                if referenced_object.semantic_level not in EXECUTABLE_SAFE_LEVELS:
                    refusals.append(
                        BackendRefusal(
                            "petta_executable_skeleton_v0",
                            f"unsafe-profile-fact:unsafe-object-reference-semantic-level:{fact[0]}:{referenced_id}:{_semantic_level_value(referenced_object)}",
                            obj.id,
                            _semantic_level_value(obj),
                        )
                    )
                    continue
                referenced_provenance_refusal = _source_provenance_refusal_reason(
                    referenced_object.source_span_id
                )
                if referenced_provenance_refusal is not None:
                    provenance_detail = (
                        "missing-source-provenance"
                        if referenced_provenance_refusal == "missing-source-provenance"
                        else referenced_provenance_refusal
                    )
                    refusals.append(
                        BackendRefusal(
                            "petta_executable_skeleton_v0",
                            f"unsafe-profile-fact:unsafe-object-reference-{provenance_detail}:{fact[0]}:{referenced_id}",
                            obj.id,
                            _semantic_level_value(obj),
                        )
                    )
                    continue
                if not referenced_object.facts:
                    refusals.append(
                        BackendRefusal(
                            "petta_executable_skeleton_v0",
                            f"unsafe-profile-fact:unsafe-object-reference-missing-profile-facts:{fact[0]}:{referenced_id}",
                            obj.id,
                            _semantic_level_value(obj),
                        )
                    )
                    continue
                referenced_fact_refusal = min(
                    (
                        profile_refusal
                        for referenced_fact in referenced_object.facts
                        if (profile_refusal := _profile_fact_refusal(referenced_object, referenced_fact)) is not None
                        and not profile_refusal.reason.startswith("empty-object-reference:")
                    ),
                    key=lambda refusal: refusal.reason,
                    default=None,
                )
                if referenced_fact_refusal is not None:
                    refusals.append(
                        BackendRefusal(
                            "petta_executable_skeleton_v0",
                            f"unsafe-profile-fact:unsafe-object-reference-profile:{fact[0]}:{referenced_id}:{referenced_fact_refusal.reason}",
                            obj.id,
                            _semantic_level_value(obj),
                        )
                    )
                    continue
                nested_unsafe_reference = min(
                    (
                        (str(referenced_fact[0]), str(referenced_fact[position]))
                        for referenced_fact in referenced_object.facts
                        for position in FACT_SCHEMAS[str(referenced_fact[0])].object_refs
                        if str(referenced_fact[position]) not in declared_object_ids
                    ),
                    default=None,
                )
                if nested_unsafe_reference is not None:
                    nested_predicate, nested_id = nested_unsafe_reference
                    refusals.append(
                        BackendRefusal(
                            "petta_executable_skeleton_v0",
                            f"unsafe-profile-fact:unsafe-object-reference-transitive-dangling:{fact[0]}:{referenced_id}:{nested_predicate}:{nested_id}",
                            obj.id,
                            _semantic_level_value(obj),
                        )
                    )
                    continue
                nested_unsafe_target = min(
                    (
                        (str(referenced_fact[0]), nested_id, _semantic_level_value(declared_objects[nested_id]))
                        for referenced_fact in referenced_object.facts
                        for position in FACT_SCHEMAS[str(referenced_fact[0])].object_refs
                        if (nested_id := str(referenced_fact[position])) in declared_object_ids
                        and nested_id not in duplicate_object_ids
                        and declared_objects[nested_id].semantic_level not in EXECUTABLE_SAFE_LEVELS
                    ),
                    default=None,
                )
                if nested_unsafe_target is not None:
                    nested_predicate, nested_id, nested_level = nested_unsafe_target
                    refusals.append(
                        BackendRefusal(
                            "petta_executable_skeleton_v0",
                            f"unsafe-profile-fact:unsafe-object-reference-transitive-semantic-level:{fact[0]}:{referenced_id}:{nested_predicate}:{nested_id}:{nested_level}",
                            obj.id,
                            _semantic_level_value(obj),
                        )
                    )
                    continue

                # Immediate target checks are not enough for longer chains such as
                # coverage -> requirement -> generated artifact -> RawTextOnly.
                # Walk only profile-valid, unambiguous references and conservatively
                # refuse the originating fact when any deeper target is unsafe.
                pending_paths = [((referenced_id,), referenced_id)]
                deep_unsafe_target = None
                while pending_paths and deep_unsafe_target is None:
                    path, current_id = heapq.heappop(pending_paths)
                    if not current_id.strip():
                        deep_unsafe_target = (path, "MissingObjectId")
                        break
                    if current_id in path[:-1]:
                        deep_unsafe_target = (path, "ReferenceCycle")
                        break
                    if current_id in duplicate_object_ids:
                        deep_unsafe_target = (path, "AmbiguousReference")
                        break
                    if current_id not in declared_object_ids:
                        if len(path) > 1:
                            deep_unsafe_target = (path, "DanglingReference")
                        continue
                    current = declared_objects[current_id]
                    if len(path) > 1:
                        if current.semantic_level not in EXECUTABLE_SAFE_LEVELS:
                            deep_unsafe_target = (path, _semantic_level_value(current))
                            break
                        current_provenance_refusal = _source_provenance_refusal_reason(
                            current.source_span_id
                        )
                        if current_provenance_refusal is not None:
                            deep_unsafe_target = (
                                path,
                                "MissingSourceProvenance"
                                if current_provenance_refusal == "missing-source-provenance"
                                else "UnsupportedSourceProvenanceType:"
                                + type(current.source_span_id).__name__,
                            )
                            break
                        if not current.facts:
                            deep_unsafe_target = (path, "MissingProfileFacts")
                            break
                        current_fact_refusal = min(
                            (
                                refusal
                                for current_fact in current.facts
                                if (refusal := _profile_fact_refusal(current, current_fact)) is not None
                            ),
                            key=lambda refusal: refusal.reason,
                            default=None,
                        )
                        if current_fact_refusal is not None:
                            deep_unsafe_target = (path, f"UnsafeProfile:{current_fact_refusal.reason}")
                            break
                    current_references = sorted(
                        (
                            (str(current_fact[0]), str(current_fact[current_position]))
                            for current_fact in current.facts
                            for current_position in FACT_SCHEMAS[str(current_fact[0])].object_refs
                        ),
                        key=lambda reference: (reference[1], reference[0]),
                    )
                    for current_predicate, target_id in current_references:
                        target_path = path + (target_id,)
                        heapq.heappush(pending_paths, (target_path, target_id))
                if deep_unsafe_target is not None:
                    unsafe_path, unsafe_level = deep_unsafe_target
                    refusals.append(
                        BackendRefusal(
                            "petta_executable_skeleton_v0",
                            f"unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:{fact[0]}:{'->'.join(unsafe_path)}:{unsafe_level}",
                            obj.id,
                            _semantic_level_value(obj),
                        )
                    )
    return refusals

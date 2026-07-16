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

from ..schema import SemanticLevel, SpecDocument, SpecObject, Role
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


def _validation_obligation_identity_refusal_reason(obligation_id: object) -> str | None:
    """Return a stable reason when a validation obligation has no safe ID."""
    if not isinstance(obligation_id, str):
        return f"unsupported-validation-obligation-id-type:{type(obligation_id).__name__}"
    if not obligation_id.strip():
        return "missing-validation-obligation-id"
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
            provenance_refusal = _source_provenance_refusal_reason(obj.source_span_id)
            if provenance_refusal and provenance_refusal.startswith("unsupported-"):
                refusals.append(
                    BackendRefusal(
                        "petta_reified_v0",
                        f"{provenance_refusal}-for-reified-emission",
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
    for obligation in doc.validation_obligations:
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
        atoms.append(_atom(["validation-obligation", obligation.id, obligation.property, obligation.target_id]))
        atoms.append(_atom(["validation-rationale", obligation.id, obligation.rationale]))
        provenance_refusal = _source_provenance_refusal_reason(obligation.source_span_id)
        if provenance_refusal and provenance_refusal.startswith("unsupported-"):
            refusals.append(
                BackendRefusal(
                    "petta_reified_v0",
                    f"{provenance_refusal}-for-validation-obligation",
                    obligation.id,
                )
            )
        elif obligation.source_span_id:
            atoms.append(_atom(["derived-from", obligation.id, obligation.source_span_id]))
    emitted_checks = []
    for check in doc.checks:
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
        status_value = check.status.value if hasattr(check.status, "value") else str(check.status)
        atoms.append(_atom(["check", check.id, check.property, check.target_id, status_value]))
        atoms.append(_atom(["check-obligation", check.id, check.obligation_id]))
        atoms.append(_atom(["check-evidence", check.id, check.evidence]))
        emitted_checks.append(check)

    # Count only records actually emitted so the summary cannot assert the
    # presence of refused checks.
    pass_count = sum(1 for c in emitted_checks if hasattr(c.status, "value") and c.status.value == "Pass")
    fail_count = sum(1 for c in emitted_checks if hasattr(c.status, "value") and c.status.value == "Fail")
    unknown_count = sum(1 for c in emitted_checks if hasattr(c.status, "value") and c.status.value == "Unknown")
    question_count = sum(1 for obj in doc.objects if obj.role == Role.QUESTION_OBJECT)
    atoms.append(_atom(["document-validation-summary", doc.files[0].id if doc.files else "document", pass_count, fail_count, unknown_count, question_count]))

    # Information-flow graph summary: quick stats from DataFlowEdge/TemporalOrderEdge atoms.
    graph_summary = _compute_information_flow_summary(doc)
    atoms.append(_atom(["information-flow-graph-summary", doc.files[0].id if doc.files else "document",
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

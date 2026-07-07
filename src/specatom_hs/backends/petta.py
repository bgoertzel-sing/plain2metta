"""Conservative PeTTa/MeTTa backend profile gates.

This module emits reified fact stubs only. Executable skeleton generation is
refused unless all input objects already have a backend-safe semantic level.
"""

from __future__ import annotations

import json
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
    if schema.subject_pos is not None and str(fact[schema.subject_pos]) != obj.id:
        return BackendRefusal("petta_reified_v0", f"fact-subject-mismatch:{predicate}:expected-{obj.id}:got-{fact[schema.subject_pos]}", obj.id, obj.semantic_level.value)
    return None


def _compute_information_flow_summary(doc: SpecDocument) -> dict[str, int]:
    """Compute quick graph stats from DataFlowEdge and TemporalOrderEdge facts."""
    data_edges: list[tuple[str, str, str]] = []  # (source, target, direction)
    temporal_edges: list[tuple[str, str]] = []  # (source, target)

    for obj in doc.objects:
        for fact in obj.facts:
            if not fact or len(fact) < 2:
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
        status_value = check.status.value if hasattr(check.status, "value") else str(check.status)
        atoms.append(_atom(["check", check.id, check.property, check.target_id, status_value]))
        atoms.append(_atom(["check-obligation", check.id, check.obligation_id]))
        atoms.append(_atom(["check-evidence", check.id, check.evidence]))

    # Document validation summary: counts by status for quick downstream triage.
    pass_count = sum(1 for c in doc.checks if hasattr(c.status, "value") and c.status.value == "Pass")
    fail_count = sum(1 for c in doc.checks if hasattr(c.status, "value") and c.status.value == "Fail")
    unknown_count = sum(1 for c in doc.checks if hasattr(c.status, "value") and c.status.value == "Unknown")
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
    """Return refusal records for every object unsafe for executable skeletons."""
    refusals: list[BackendRefusal] = []
    for obj in objects:
        if obj.semantic_level == SemanticLevel.RAW_TEXT_ONLY:
            refusals.append(BackendRefusal("petta_executable_skeleton_v0", "raw-text-only-skeleton-forbidden", obj.id, obj.semantic_level.value))
        elif obj.semantic_level not in EXECUTABLE_SAFE_LEVELS:
            refusals.append(BackendRefusal("petta_executable_skeleton_v0", "unsupported-semantic-level-for-executable-skeleton", obj.id, obj.semantic_level.value))
    return refusals

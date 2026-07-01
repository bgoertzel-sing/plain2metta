from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceSpan:
    id: str
    file_id: str
    start_byte: int
    end_byte: int
    start_line: int
    end_line: int


@dataclass(frozen=True)
class PlainFile:
    id: str
    path: str
    digest: str
    text: str
    line_starts: tuple[int, ...]


@dataclass
class Section:
    id: str
    file_id: str
    kind: str
    ordinal: int
    span_id: str
    title: str


@dataclass
class PlainItem:
    id: str
    section_id: str
    parent_item_id: str | None
    ordinal: int
    raw_text: str
    span_id: str
    level: int = 0
    children: list[str] = field(default_factory=list)


@dataclass
class Graph:
    facts: list[list[Any]] = field(default_factory=list)
    spec_objects: dict[str, dict[str, Any]] = field(default_factory=dict)
    spans: dict[str, SourceSpan] = field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    questions: list[dict[str, Any]] = field(default_factory=list)

    def fact(self, *parts: Any) -> None:
        fact = list(parts)
        if fact not in self.facts:
            self.facts.append(fact)

    def spec_object(self, object_id: str, primary_role: str, source_span: str | None, semantic_level: str = "RawTextOnly") -> None:
        obj = self.spec_objects.setdefault(
            object_id,
            {
                "id": object_id,
                "kind": "SpecObject",
                "primary_role": primary_role,
                "source": {"span": source_span} if source_span else None,
                "semantic_level": semantic_level,
                "facts": [],
                "assertions": [],
            },
        )
        obj["primary_role"] = primary_role
        obj["semantic_level"] = semantic_level
        if source_span:
            obj["source"] = {"span": source_span}
        self.fact("SpecObject", object_id)
        self.fact("PrimaryRole", object_id, primary_role)
        self.fact("SemanticLevel", object_id, semantic_level)
        if source_span:
            self.fact("DerivedFrom", object_id, source_span)

    def assertion(self, context: str, claim: str, pos: float, neg: float) -> None:
        self.fact("Context", context)
        self.fact("Assert", context, claim, {"type": "pbit", "pos": pos, "neg": neg})

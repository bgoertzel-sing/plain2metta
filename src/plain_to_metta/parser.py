from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .ids import slugify, stable_id
from .model import PlainFile, PlainItem, Section, SourceSpan

HEADER_RE = re.compile(r"^(?P<indent>\s*)\*\*\*(?P<title>.+?)\*\*\*\s*$")
BULLET_RE = re.compile(r"^(?P<indent>\s*)-\s+(?P<text>.*)$")


def _line_starts(text: str) -> tuple[int, ...]:
    starts = [0]
    for idx, ch in enumerate(text):
        if ch == "\n":
            starts.append(idx + 1)
    return tuple(starts)


def _line_for_offset(line_starts: tuple[int, ...], offset: int) -> int:
    # Small files in MVP; linear keeps implementation obvious.
    line = 1
    for i, start in enumerate(line_starts, start=1):
        if start > offset:
            break
        line = i
    return line


def read_plain_file(path: str | Path, file_ordinal: int = 1) -> PlainFile:
    p = Path(path)
    data = p.read_bytes()
    text = data.decode("utf-8")
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    file_id = stable_id("pf", str(p), digest, file_ordinal, length=8)
    return PlainFile(file_id, str(p), digest, text, _line_starts(text))


def source_span(file: PlainFile, prefix: str, start: int, end: int) -> SourceSpan:
    return SourceSpan(
        stable_id(prefix, file.id, start, end, length=10),
        file.id,
        start,
        end,
        _line_for_offset(file.line_starts, start),
        _line_for_offset(file.line_starts, max(start, end - 1)),
    )


def parse_plain(file: PlainFile) -> tuple[list[Section], list[PlainItem], dict[str, SourceSpan]]:
    sections: list[Section] = []
    items: list[PlainItem] = []
    spans: dict[str, SourceSpan] = {}
    current_section: Section | None = None
    stack: list[tuple[int, str]] = []
    section_counts: dict[str, int] = {}
    item_ordinals: dict[tuple[str, str | None], int] = {}

    offset = 0
    for raw_line in file.text.splitlines(keepends=True):
        line = raw_line.rstrip("\n")
        line_start = offset
        line_end = offset + len(raw_line)
        offset = line_end

        header = HEADER_RE.match(line)
        if header:
            title = header.group("title").strip()
            kind = section_kind(title)
            section_counts[kind] = section_counts.get(kind, 0) + 1
            span = source_span(file, "span", line_start, line_end)
            spans[span.id] = span
            sec_id = f"sec-{slugify(kind)}-{section_counts[kind]}"
            current_section = Section(sec_id, file.id, kind, len(sections) + 1, span.id, title)
            sections.append(current_section)
            stack.clear()
            continue

        bullet = BULLET_RE.match(line)
        if bullet and current_section is not None:
            indent = len(bullet.group("indent"))
            text = bullet.group("text").strip()
            while stack and stack[-1][0] >= indent:
                stack.pop()
            parent = stack[-1][1] if stack else None
            key = (current_section.id, parent)
            item_ordinals[key] = item_ordinals.get(key, 0) + 1
            ordinal = item_ordinals[key]
            span = source_span(file, "span", line_start + len(bullet.group("indent")), line_end)
            spans[span.id] = span
            item_id = stable_id("item", file.id, current_section.id, parent or "none", ordinal, text, length=10)
            item = PlainItem(item_id, current_section.id, parent, ordinal, text, span.id, indent)
            items.append(item)
            if parent:
                for prior in items:
                    if prior.id == parent:
                        prior.children.append(item_id)
                        break
            stack.append((indent, item_id))

    return sections, items, spans


def section_kind(title: str) -> str:
    norm = slugify(title)
    mapping = {
        "definitions": "Definitions",
        "functional-specifications": "FunctionalSpecifications",
        "acceptance-tests": "AcceptanceTests",
        "implementation-requirements": "ImplementationRequirements",
    }
    return mapping.get(norm, title.strip().title().replace(" ", ""))

"""Source indexer for the first SpecAtom-HS scaffold.

Recognizes only headings of the form ``***title***`` and dash bullets. Every
section and item receives a stable ID plus byte and line source span.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .schema import PlainFile, PlainItem, Section, SourceSpan, SpecDocument, stable_id

HEADER_RE = re.compile(r"^(?P<indent>\s*)\*\*\*(?P<title>.+?)\*\*\*\s*$")
BULLET_RE = re.compile(r"^(?P<indent>\s*)-\s+(?P<text>.*)$")
PHYSICAL_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$")


def _line_starts(text: str) -> tuple[int, ...]:
    starts = [0]
    byte_offset = 0
    previous_was_cr = False
    for ch in text:
        byte_offset += len(ch.encode("utf-8"))
        if ch == "\r":
            starts.append(byte_offset)
            previous_was_cr = True
        elif ch == "\n":
            if previous_was_cr:
                starts[-1] = byte_offset
            else:
                starts.append(byte_offset)
            previous_was_cr = False
        else:
            previous_was_cr = False
    return tuple(starts)


def _line_for_offset(starts: tuple[int, ...], offset: int) -> int:
    line = 1
    for idx, start in enumerate(starts, start=1):
        if start > offset:
            break
        line = idx
    return line


def section_kind(title: str) -> str:
    words = re.sub(r"[^A-Za-z0-9]+", " ", title).strip().title().replace(" ", "")
    return words or "Untitled"


def index_path(path: str | Path, file_ordinal: int = 1) -> SpecDocument:
    p = Path(path)
    data = p.read_bytes()
    return index_source(data.decode("utf-8"), str(p), file_ordinal=file_ordinal)


def index_source(text: str, path: str = "inline.plain", file_ordinal: int = 1) -> SpecDocument:
    digest = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    file_id = stable_id("file", path, digest, file_ordinal, length=8)
    plain_file = PlainFile(file_id, path, digest, text)
    starts = _line_starts(text)
    doc = SpecDocument(files=[plain_file])

    current: Section | None = None
    stack: list[tuple[int, str]] = []
    section_counts: dict[str, int] = {}
    item_ordinals: dict[tuple[str, str | None], int] = {}

    lines: list[tuple[str, int, int]] = []
    offset = 0
    # Plain source lines are delimited only by CR, LF, or CRLF.  Python's
    # str.splitlines() also splits on Unicode separators (for example U+2028),
    # which would disagree with _line_starts() and create phantom line numbers.
    for line_match in PHYSICAL_LINE_RE.finditer(text):
        raw_line = line_match.group(0)
        line_start = offset
        line_end = offset + len(raw_line.encode("utf-8"))
        lines.append((raw_line, line_start, line_end))
        offset = line_end

    i = 0
    while i < len(lines):
        raw_line, line_start, line_end = lines[i]
        line = raw_line.rstrip("\n")
        match_line = line.removeprefix("\ufeff") if line_start == 0 else line

        header = HEADER_RE.match(match_line)
        if header:
            title = header.group("title").strip()
            kind = section_kind(title)
            section_counts[kind] = section_counts.get(kind, 0) + 1
            span = SourceSpan(
                stable_id("span", file_id, line_start, line_end),
                file_id,
                line_start,
                line_end,
                _line_for_offset(starts, line_start),
                _line_for_offset(starts, max(line_start, line_end - 1)),
            )
            sec_id = stable_id("section", file_id, kind, section_counts[kind], length=10)
            current = Section(sec_id, file_id, title, kind, len(doc.sections) + 1, span)
            doc.sections.append(current)
            doc.spans.append(span)
            stack.clear()
            i += 1
            continue

        bullet = BULLET_RE.match(line)
        if bullet and current:
            indent = len(bullet.group("indent"))
            while stack and stack[-1][0] >= indent:
                stack.pop()
            parent = stack[-1][1] if stack else None
            key = (current.id, parent)
            item_ordinals[key] = item_ordinals.get(key, 0) + 1
            ordinal = item_ordinals[key]
            text_start = line_start + len(bullet.group("indent").encode("utf-8"))
            span_end = line_end
            raw_parts = [bullet.group("text").strip()]

            j = i + 1
            while j < len(lines):
                next_raw, _next_start, next_end = lines[j]
                next_line = next_raw.rstrip("\n")
                if not next_line.strip() or HEADER_RE.match(next_line) or BULLET_RE.match(next_line):
                    break
                if len(next_line) - len(next_line.lstrip()) <= indent:
                    break
                raw_parts.append(next_line.strip())
                span_end = next_end
                j += 1

            span = SourceSpan(
                stable_id("span", file_id, text_start, span_end),
                file_id,
                text_start,
                span_end,
                _line_for_offset(starts, text_start),
                _line_for_offset(starts, max(text_start, span_end - 1)),
            )
            raw_text = "\n".join(part for part in raw_parts if part)
            item_id = stable_id("item", file_id, current.id, parent or "none", ordinal, raw_text, length=10)
            doc.items.append(PlainItem(item_id, file_id, current.id, parent, ordinal, indent, raw_text, span))
            doc.spans.append(span)
            stack.append((indent, item_id))
            i = j
            continue
        i += 1
    return doc

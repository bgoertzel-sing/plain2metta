from __future__ import annotations

import hashlib
import re


def slugify(text: str, fallback: str = "x") -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", text.strip().lower()).strip("-")
    return text or fallback


def stable_id(prefix: str, *parts: object, length: int = 10) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part).encode("utf-8"))
        h.update(b"\0")
    return f"{prefix}-{h.hexdigest()[:length]}"

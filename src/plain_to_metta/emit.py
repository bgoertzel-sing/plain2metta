from __future__ import annotations

import json
from typing import Any


def write_json(doc: dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")


def atom_to_sexpr(atom: list[Any]) -> str:
    return "(" + " ".join(_sexpr_part(p) for p in atom) + ")"


def _sexpr_part(part: Any) -> str:
    if part is None:
        return "none"
    if isinstance(part, dict) and part.get("type") == "pbit":
        return f"(pbit {part['pos']:.2f} {part['neg']:.2f})"
    if isinstance(part, (int, float)):
        return str(part)
    s = str(part)
    if s == "" or any(ch.isspace() for ch in s) or any(ch in s for ch in '()"') or ":" in s and not s.startswith("C:"):
        return json.dumps(s)
    return s


def write_sexpr(doc: dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for atom in doc["facts"]:
            fh.write(atom_to_sexpr(atom))
            fh.write("\n")

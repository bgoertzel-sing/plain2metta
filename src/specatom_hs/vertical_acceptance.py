"""Strict data-driven Stage 10 examples and categorized mutation corpus."""
from __future__ import annotations
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

SCHEMA = "plain2metta-vertical-acceptance/v1"
ALLOWED_STATUS = {"executable", "blocked"}
ALLOWED_OUTCOME = {"killed", "survived-reviewed"}

@lru_cache(maxsize=1)
def load_vertical_acceptance() -> dict[str, Any]:
    raw = json.loads(Path(__file__).with_name("vertical_acceptance.json").read_text())
    if not isinstance(raw, dict) or set(raw) != {"schema","examples","mutants","threshold"} or raw["schema"] != SCHEMA:
        raise ValueError("unsupported vertical acceptance artifact")
    examples = raw["examples"]
    if not isinstance(examples, list) or len(examples) != 5:
        raise ValueError("vertical acceptance requires exactly five Section 9 examples")
    ids = []
    for item in examples:
        allowed = {"id","shape","source_ids","source","contract","validation","status","obligations","holes"}
        required = {"id","shape","source_ids","source","contract","validation","status","obligations"}
        if not isinstance(item, dict) or not set(item).issubset(allowed) or not required.issubset(item):
            raise ValueError("malformed vertical example")
        if (item["status"] not in ALLOWED_STATUS or not item["source_ids"] or not item["obligations"]
                or any(not isinstance(item[field], str) or not item[field].strip()
                       for field in ("source", "contract", "validation"))):
            raise ValueError("invalid vertical example")
        if item["status"] == "blocked" and not item.get("holes"):
            raise ValueError("blocked example must retain typed unresolved holes")
        if item["status"] == "executable" and item.get("holes"):
            raise ValueError("unresolved example cannot be executable")
        ids.append(item["id"])
    if len(ids) != len(set(ids)) or len({x["shape"] for x in examples}) < 4:
        raise ValueError("duplicate identity or insufficient semantic shapes")
    mutants = raw["mutants"]
    if not isinstance(mutants, list) or not mutants:
        raise ValueError("mutation corpus is empty")
    mutant_ids = []
    for mutant in mutants:
        if not isinstance(mutant, dict) or set(mutant) != {"id","category","example","expected"}:
            raise ValueError("malformed mutation")
        if mutant["example"] not in ids or mutant["expected"] not in ALLOWED_OUTCOME:
            raise ValueError("invalid mutation attribution")
        mutant_ids.append(mutant["id"])
    if len(mutant_ids) != len(set(mutant_ids)):
        raise ValueError("duplicate mutation identity")
    relevant = [x for x in mutants if x["category"] != "cosmetic"]
    killed = [x for x in relevant if x["expected"] == "killed"]
    if len(killed) != len(relevant):
        raise ValueError("relevant mutation survived without review")
    return raw

def mutation_report() -> dict[str, Any]:
    corpus = load_vertical_acceptance()
    relevant = [x for x in corpus["mutants"] if x["category"] != "cosmetic"]
    killed = [x for x in relevant if x["expected"] == "killed"]
    survivors = [x for x in corpus["mutants"] if x["expected"] == "survived-reviewed"]
    return {"schema":SCHEMA,"relevant":len(relevant),"killed":len(killed),
            "kill_ratio":f"{len(killed)}/{len(relevant)}","survivors":survivors}

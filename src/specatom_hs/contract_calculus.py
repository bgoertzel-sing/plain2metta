"""Finite typed contract calculus for semantic-validation revision 0.2 Stage 2.

The calculus intentionally accepts only canonical JSON terms.  Text fields are
never parsed as expressions.  Unsupported meaning is represented by an
explicit typed ``hole`` term and cannot be evaluated or projected as executable
MeTTa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from .semantic_artifacts import canonical_semantic_artifact, validate_semantic_artifact


CALCULUS = "plain2metta-contract-calculus/v1"
MAX_QUANTIFIER_DOMAIN = 1024
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9._:-]{0,127}\Z")
_SCALARS = {"Bool", "Int", "Text", "Decimal", "Timestamp", "Unit"}
_OWNERS = {"reference-interpreter", "metta", "python-grounded"}
_EFFECTS = {"pure", "state-read", "state-write", "trace-read", "trace-emit", "time-read"}


@dataclass(frozen=True)
class Event:
    name: str
    at: str
    data: Mapping[str, Any]


@dataclass(frozen=True)
class EvaluationContext:
    variables: Mapping[str, Any]
    state: Mapping[str, Any]
    trace: tuple[Event, ...] = ()
    assumptions: frozenset[str] = frozenset()
    now: str | None = None


@dataclass(frozen=True)
class CheckedContract:
    artifact_id: str
    artifact_hash: str
    name: str
    variables: Mapping[str, object]
    output_type: object
    preconditions: tuple[Mapping[str, Any], ...]
    postconditions: tuple[Mapping[str, Any], ...]
    invariants: tuple[Mapping[str, Any], ...]
    temporal: tuple[Mapping[str, Any], ...]
    effects: tuple[str, ...]
    assumption_refs: tuple[str, ...]
    ownership_locus: str
    unresolved_holes: tuple[Mapping[str, Any], ...]


def _exact(value: object, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{label} has unknown or missing fields")
    return value


def _name(value: object, label: str) -> str:
    if not isinstance(value, str) or _NAME.fullmatch(value) is None:
        raise ValueError(f"{label} is not a canonical identifier")
    return value


def canonical_type(value: object) -> object:
    if isinstance(value, str) and value in _SCALARS:
        return value
    if not isinstance(value, Mapping) or len(value) != 1:
        raise ValueError("invalid type expression")
    if "List" in value:
        return {"List": canonical_type(value["List"])}
    if "Option" in value:
        return {"Option": canonical_type(value["Option"])}
    if "Record" in value:
        fields = value["Record"]
        if not isinstance(fields, Mapping) or not fields:
            raise ValueError("record type requires fields")
        names = sorted(_name(key, "record field") for key in fields)
        return {"Record": {key: canonical_type(fields[key]) for key in names}}
    raise ValueError("unsupported type expression")


def _same(left: object, right: object) -> bool:
    return canonical_type(left) == canonical_type(right)


def _literal_type(value: object, declared: object) -> object:
    typ = canonical_type(declared)
    if typ == "Bool" and type(value) is bool:
        return typ
    if typ == "Int" and type(value) is int:
        return typ
    if typ == "Text" and isinstance(value, str):
        return typ
    if typ == "Decimal" and isinstance(value, str):
        try:
            Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("invalid canonical decimal") from exc
        return typ
    if typ == "Timestamp" and isinstance(value, str):
        _timestamp(value)
        return typ
    if typ == "Unit" and value is None:
        return typ
    if isinstance(typ, Mapping) and "List" in typ and isinstance(value, list):
        for item in value:
            _literal_type(item, typ["List"])
        return typ
    if isinstance(typ, Mapping) and "Record" in typ and isinstance(value, Mapping) and set(value) == set(typ["Record"]):
        for key, field_type in typ["Record"].items():
            _literal_type(value[key], field_type)
        return typ
    raise ValueError("literal does not match declared type")


def _timestamp(value: str) -> datetime:
    if not value.endswith("Z"):
        raise ValueError("timestamp must be canonical UTC text")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if parsed.tzinfo != timezone.utc or parsed.isoformat().replace("+00:00", "Z") != value:
        raise ValueError("timestamp is not canonical UTC text")
    return parsed


def type_check(term: object, variables: Mapping[str, object], *, bound: Mapping[str, object] | None = None) -> object:
    if not isinstance(term, Mapping) or "op" not in term or not isinstance(term["op"], str):
        raise ValueError("predicate term must be a typed operation object")
    op = term["op"]
    scope = dict(variables)
    scope.update(bound or {})
    if op == "literal":
        item = _exact(term, {"op", "type", "value"}, "literal")
        return _literal_type(item["value"], item["type"])
    if op == "var":
        item = _exact(term, {"op", "name"}, "variable")
        name = _name(item["name"], "variable")
        if name not in scope:
            raise ValueError(f"unknown variable {name}")
        return canonical_type(scope[name])
    if op == "state":
        item = _exact(term, {"op", "key", "type"}, "state read")
        _name(item["key"], "state key")
        return canonical_type(item["type"])
    if op == "now":
        _exact(term, {"op"}, "now")
        return "Timestamp"
    if op == "field":
        item = _exact(term, {"op", "record", "name"}, "field")
        record_type = type_check(item["record"], variables, bound=bound)
        name = _name(item["name"], "field")
        if not isinstance(record_type, Mapping) or "Record" not in record_type or name not in record_type["Record"]:
            raise ValueError("field access does not match record type")
        return record_type["Record"][name]
    if op in {"eq", "ne", "lt", "le", "gt", "ge"}:
        item = _exact(term, {"op", "left", "right"}, op)
        left = type_check(item["left"], variables, bound=bound)
        right = type_check(item["right"], variables, bound=bound)
        if not _same(left, right):
            raise ValueError(f"{op} operands have different types")
        if op not in {"eq", "ne"} and canonical_type(left) not in {"Int", "Decimal", "Text", "Timestamp"}:
            raise ValueError(f"{op} does not support this type")
        return "Bool"
    if op in {"and", "or"}:
        item = _exact(term, {"op", "args"}, op)
        if not isinstance(item["args"], list) or not item["args"]:
            raise ValueError(f"{op} requires a non-empty finite list")
        if any(type_check(arg, variables, bound=bound) != "Bool" for arg in item["args"]):
            raise ValueError(f"{op} requires Boolean operands")
        return "Bool"
    if op == "not":
        item = _exact(term, {"op", "arg"}, "not")
        if type_check(item["arg"], variables, bound=bound) != "Bool":
            raise ValueError("not requires Boolean operand")
        return "Bool"
    if op in {"add", "sub", "mul"}:
        item = _exact(term, {"op", "left", "right"}, op)
        left = type_check(item["left"], variables, bound=bound)
        right = type_check(item["right"], variables, bound=bound)
        if not _same(left, right) or canonical_type(left) not in {"Int", "Decimal"}:
            raise ValueError(f"{op} requires equal numeric types")
        return left
    if op in {"for-all", "exists"}:
        item = _exact(term, {"op", "var", "var_type", "domain", "predicate"}, op)
        name = _name(item["var"], "quantified variable")
        var_type = canonical_type(item["var_type"])
        domain_type = type_check(item["domain"], variables, bound=bound)
        if not isinstance(domain_type, Mapping) or domain_type != {"List": var_type}:
            raise ValueError("bounded quantifier domain type mismatch")
        nested = dict(bound or {}); nested[name] = var_type
        if type_check(item["predicate"], variables, bound=nested) != "Bool":
            raise ValueError("quantified predicate must be Boolean")
        return "Bool"
    if op in {"trace-count", "exactly-once"}:
        item = _exact(term, {"op", "event"}, op)
        _name(item["event"], "event")
        return "Int" if op == "trace-count" else "Bool"
    if op == "before":
        item = _exact(term, {"op", "first", "second"}, "before")
        _name(item["first"], "event"); _name(item["second"], "event")
        return "Bool"
    if op == "approximately":
        item = _exact(term, {"op", "expected", "observed", "tolerance"}, "approximately")
        types = [type_check(item[key], variables, bound=bound) for key in ("expected", "observed", "tolerance")]
        if len({json.dumps(canonical_type(t), sort_keys=True) for t in types}) != 1 or canonical_type(types[0]) not in {"Int", "Decimal"}:
            raise ValueError("approximately requires one numeric type")
        return "Bool"
    if op == "assumption":
        item = _exact(term, {"op", "ref"}, "assumption")
        _name(item["ref"], "assumption reference")
        return "Bool"
    if op == "hole":
        item = _exact(term, {"op", "hole_id", "type", "reason"}, "typed hole")
        _name(item["hole_id"], "hole"); canonical_type(item["type"])
        if not isinstance(item["reason"], str) or not item["reason"].strip():
            raise ValueError("typed hole requires a reason")
        return canonical_type(item["type"])
    raise ValueError(f"unsupported contract operation: {op}")


def check_contract(document: Mapping[str, Any]) -> CheckedContract:
    validate_semantic_artifact(document)
    if document["artifact_type"] != "SemanticContract":
        raise ValueError("contract calculus requires a SemanticContract artifact")
    payload = document["payload"]
    variables: dict[str, object] = {}
    if not isinstance(payload["inputs"], list):
        raise ValueError("contract inputs must be a list")
    for raw in payload["inputs"]:
        item = _exact(raw, {"name", "type"}, "typed variable")
        name = _name(item["name"], "input")
        if name in variables:
            raise ValueError("duplicate contract input")
        variables[name] = canonical_type(item["type"])
    variables["result"] = canonical_type(payload["output"])
    for field in ("preconditions", "postconditions", "invariants", "temporal_constraints"):
        terms = payload[field]
        if not isinstance(terms, list):
            raise ValueError(f"{field} must be a list")
        for term in terms:
            if type_check(term, variables) != "Bool":
                raise ValueError(f"{field} requires Boolean predicates")
    effects = payload["effects"]
    if not isinstance(effects, list) or any(effect not in _EFFECTS for effect in effects) or len(set(effects)) != len(effects):
        raise ValueError("effects must be unique declared effect names")
    assumptions = payload["environment_assumptions"]
    if not isinstance(assumptions, list) or any(not isinstance(a, Mapping) or set(a) != {"ref"} for a in assumptions):
        raise ValueError("environment assumptions must be exact references")
    assumption_refs = tuple(_name(a["ref"], "assumption reference") for a in assumptions)
    if len(set(assumption_refs)) != len(assumption_refs):
        raise ValueError("duplicate assumption reference")
    holes = payload["unresolved_holes"]
    if not isinstance(holes, list):
        raise ValueError("unresolved_holes must be a list")
    checked_holes = []
    for hole in holes:
        item = _exact(hole, {"hole_id", "type", "reason"}, "unresolved hole")
        _name(item["hole_id"], "hole"); canonical_type(item["type"])
        if not isinstance(item["reason"], str) or not item["reason"].strip():
            raise ValueError("unresolved hole requires reason")
        checked_holes.append(item)
    nondeterminism = payload["nondeterminism"]
    if not isinstance(nondeterminism, Mapping) or set(nondeterminism) != {"policy", "ownership_locus"}:
        raise ValueError("nondeterminism must declare policy and ownership locus")
    if nondeterminism["policy"] not in {"deterministic", "explicit-nondeterministic"} or nondeterminism["ownership_locus"] not in _OWNERS:
        raise ValueError("invalid determinism policy or ownership locus")
    canonical_semantic_artifact(document)
    return CheckedContract(
        document["artifact_id"], "sha256:" + sha256(canonical_semantic_artifact(document).encode()).hexdigest(),
        payload["name"], variables, canonical_type(payload["output"]),
        tuple(payload["preconditions"]), tuple(payload["postconditions"]), tuple(payload["invariants"]),
        tuple(payload["temporal_constraints"]), tuple(effects), assumption_refs,
        nondeterminism["ownership_locus"], tuple(checked_holes),
    )


def _runtime_value(value: Any, typ: object) -> Any:
    typ = canonical_type(typ)
    if typ == "Decimal":
        return Decimal(value)
    if typ == "Timestamp":
        return _timestamp(value)
    if isinstance(typ, Mapping) and "List" in typ:
        return [_runtime_value(item, typ["List"]) for item in value]
    if isinstance(typ, Mapping) and "Record" in typ:
        return {key: _runtime_value(value[key], field_type) for key, field_type in typ["Record"].items()}
    return value


def _value(term: Mapping[str, Any], checked: CheckedContract, context: EvaluationContext, bound: Mapping[str, Any] | None = None) -> Any:
    op = term["op"]
    local = dict(context.variables); local.update(bound or {})
    if op == "literal":
        if term["type"] == "Decimal": return Decimal(term["value"])
        if term["type"] == "Timestamp": return _timestamp(term["value"])
        return term["value"]
    if op == "var":
        value = local[term["name"]]
        if term["name"] in (bound or {}):
            return value
        return _runtime_value(value, checked.variables[term["name"]])
    if op == "state":
        if term["key"] not in context.state: raise ValueError("missing declared state value")
        _literal_type(context.state[term["key"]], term["type"])
        return _runtime_value(context.state[term["key"]], term["type"])
    if op == "now":
        if context.now is None: raise ValueError("now is unavailable")
        return _timestamp(context.now)
    if op == "field": return _value(term["record"], checked, context, bound)[term["name"]]
    if op in {"eq", "ne", "lt", "le", "gt", "ge"}:
        left, right = _value(term["left"], checked, context, bound), _value(term["right"], checked, context, bound)
        if op == "eq": return left == right
        if op == "ne": return left != right
        if op == "lt": return left < right
        if op == "le": return left <= right
        if op == "gt": return left > right
        return left >= right
    if op == "and": return all(_value(arg, checked, context, bound) for arg in term["args"])
    if op == "or": return any(_value(arg, checked, context, bound) for arg in term["args"])
    if op == "not": return not _value(term["arg"], checked, context, bound)
    if op in {"add", "sub", "mul"}:
        left, right = _value(term["left"], checked, context, bound), _value(term["right"], checked, context, bound)
        return {"add": lambda: left + right, "sub": lambda: left - right, "mul": lambda: left * right}[op]()
    if op in {"for-all", "exists"}:
        domain = _value(term["domain"], checked, context, bound)
        if len(domain) > MAX_QUANTIFIER_DOMAIN: raise ValueError("quantifier domain exceeds bound")
        values = (
            _value(
                term["predicate"], checked, context,
                {**(bound or {}), term["var"]: _runtime_value(item, term["var_type"])},
            )
            for item in domain
        )
        return all(values) if op == "for-all" else any(values)
    if op == "trace-count": return sum(event.name == term["event"] for event in context.trace)
    if op == "exactly-once": return sum(event.name == term["event"] for event in context.trace) == 1
    if op == "before":
        first = [(_timestamp(event.at), i) for i, event in enumerate(context.trace) if event.name == term["first"]]
        second = [(_timestamp(event.at), i) for i, event in enumerate(context.trace) if event.name == term["second"]]
        return bool(first and second and min(first) < min(second))
    if op == "approximately":
        expected, observed, tolerance = (_value(term[k], checked, context, bound) for k in ("expected", "observed", "tolerance"))
        return abs(expected - observed) <= tolerance
    if op == "assumption": return term["ref"] in context.assumptions
    if op == "hole": raise ValueError("typed hole has no executable meaning")
    raise ValueError("unsupported contract operation")


def interpret_contract(document: Mapping[str, Any], context: EvaluationContext) -> dict[str, Any]:
    checked = check_contract(document)
    if checked.unresolved_holes:
        raise ValueError("contract has unresolved executable meaning")
    if any(ref not in context.assumptions for ref in checked.assumption_refs):
        raise ValueError("required assumption is not approved in this context")
    for name, typ in checked.variables.items():
        if name not in context.variables: raise ValueError(f"missing variable {name}")
        _literal_type(context.variables[name], typ)
    groups = {
        "preconditions": checked.preconditions,
        "postconditions": checked.postconditions,
        "invariants": checked.invariants,
        "temporal_constraints": checked.temporal,
    }
    results = {name: tuple(bool(_value(term, checked, context)) for term in terms) for name, terms in groups.items()}
    return {
        "calculus": CALCULUS, "contract_artifact_id": checked.artifact_id,
        "contract_artifact_hash": checked.artifact_hash, "results": results,
        "satisfied": all(all(items) for items in results.values()),
    }


def _atom(value: str) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _metta_type(typ: object) -> str:
    typ = canonical_type(typ)
    if isinstance(typ, str): return typ
    key, value = next(iter(typ.items()))
    if key in {"List", "Option"}: return f"({key} {_metta_type(value)})"
    return "(Record " + " ".join(f"({_atom(k)} {_metta_type(v)})" for k, v in value.items()) + ")"


def _metta(term: Mapping[str, Any], variables: Mapping[str, object]) -> str:
    type_check(term, variables)
    op = term["op"]
    if op == "literal": return f"(literal {_metta_type(term['type'])} {_atom(json.dumps(term['value'], ensure_ascii=False, sort_keys=True, separators=(',', ':')))})"
    if op == "var": return f"(var {_atom(term['name'])} {_metta_type(variables[term['name']])})"
    if op == "state": return f"(state {_atom(term['key'])} {_metta_type(term['type'])})"
    if op == "now": return "(now Timestamp)"
    if op == "field": return f"(field {_metta(term['record'], variables)} {_atom(term['name'])})"
    if op in {"eq", "ne", "lt", "le", "gt", "ge", "add", "sub", "mul"}: return f"({op} {_metta(term['left'], variables)} {_metta(term['right'], variables)})"
    if op in {"and", "or"}: return f"({op} " + " ".join(_metta(a, variables) for a in term["args"]) + ")"
    if op == "not": return f"(not {_metta(term['arg'], variables)})"
    if op in {"trace-count", "exactly-once"}: return f"({op} {_atom(term['event'])})"
    if op == "before": return f"(before {_atom(term['first'])} {_atom(term['second'])})"
    if op == "approximately": return f"(approximately {_metta(term['expected'], variables)} {_metta(term['observed'], variables)} {_metta(term['tolerance'], variables)})"
    if op == "assumption": return f"(assumption {_atom(term['ref'])})"
    if op in {"for-all", "exists"}:
        nested = dict(variables); nested[term["var"]] = canonical_type(term["var_type"])
        return f"({op} ({_atom(term['var'])} {_metta_type(term['var_type'])}) {_metta(term['domain'], variables)} {_metta(term['predicate'], nested)})"
    if op == "hole": raise ValueError("typed hole cannot be projected as executable MeTTa")
    raise ValueError("unsupported contract operation")


def project_contract_to_metta(document: Mapping[str, Any]) -> str:
    checked = check_contract(document)
    if checked.unresolved_holes:
        raise ValueError("contract has unresolved executable meaning")
    lines = [
        f"(contract-calculus {_atom(CALCULUS)})",
        f"(contract-artifact {_atom(checked.artifact_id)} {_atom(checked.artifact_hash)})",
        f"(contract-owner {_atom(checked.ownership_locus)})",
    ]
    for name, terms in (("requires", checked.preconditions), ("ensures", checked.postconditions), ("invariant", checked.invariants), ("temporal", checked.temporal)):
        lines.extend(f"({name} {_atom(checked.artifact_id)} {_metta(term, checked.variables)})" for term in terms)
    return "\n".join(lines) + "\n"

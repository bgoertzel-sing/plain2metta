"""Canonical Stage-6 SMT-LIB lowering and pinned Z3 evidence admission."""

from __future__ import annotations

import json
import os
import re
import resource
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Mapping

from .projects import ApprovalDecision, ArtifactKind, Project, add_semantic_artifact
from .semantic_artifacts import build_semantic_artifact, validate_semantic_artifact
from .validation_plan import validate_plan_review_chain

SCHEMA = "plain2metta-smt-request/v1"
RESULT_SCHEMA = "plain2metta-smt-result/v1"
Z3_VERSION = "4.15.3"
Z3_SHA256 = "sha256:233a2a59f68a4793479d8429426d7833c6a7bd03782b415b8f38e1737ccab373"
LOGIC = "QF_LIA"
OPTIONS = {"produce_models": True, "produce_unsat_cores": True, "timeout_ms": 2000}
BOUNDS = {"cpu_seconds": 4, "memory_mb": 512, "file_mb": 4, "timeout_seconds": 5}
_ID = re.compile(r"[A-Za-z][A-Za-z0-9._:-]{0,127}\Z")


def _ref(ref):
    return {"artifact_id": ref.artifact_id, "content_hash": ref.content_hash}


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def request_hash(request: Mapping[str, Any]) -> str:
    return "sha256:" + sha256(_canonical(request).encode()).hexdigest()


def _approved_plan(project: Project):
    validate_plan_review_chain(project)
    plan = project.current(ArtifactKind.VALIDATION_PLAN)
    review = project.current(ArtifactKind.VALIDATION_PLAN_REVIEW)
    if plan is None or review is None:
        raise ValueError("SMT lowering requires an approved reviewed plan")
    approvals = [item for item in project.approvals if item.artifact == plan.ref]
    if len(approvals) != 1 or approvals[0].decision is not ApprovalDecision.APPROVED:
        raise ValueError("validation plan is not exactly approved")
    return plan, review


def _strict_task(value: object) -> dict[str, Any]:
    fields = {"task_id", "source_clause_refs", "fragment", "problem", "mutant", "proof_requested"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("SMT task is malformed")
    if not isinstance(value["task_id"], str) or _ID.fullmatch(value["task_id"]) is None:
        raise ValueError("SMT task id is not canonical")
    refs = value["source_clause_refs"]
    if not isinstance(refs, list) or not refs or any(not isinstance(x, str) or _ID.fullmatch(x) is None for x in refs) or len(set(refs)) != len(refs):
        raise ValueError("SMT source clauses are invalid or duplicated")
    if value["fragment"] not in {"pure", "bounded-transition"}:
        raise ValueError("unsupported SMT fragment remains blocked")
    allowed = {
        "exact-boolean-postcondition": ("pure", {"none"}),
        "contradictory-contract": ("pure", {"none", "consistent"}),
        "unreachable-state": ("bounded-transition", {"none", "reachable"}),
        "boundary-error": ("pure", {"none", "fixed"}),
        "finite-counterexample": ("bounded-transition", {"none", "fixed"}),
    }
    if value["problem"] not in allowed:
        raise ValueError("unsupported or unresolved SMT meaning remains blocked")
    fragment, mutants = allowed[value["problem"]]
    if value["fragment"] != fragment or value["mutant"] not in mutants:
        raise ValueError("SMT task fragment or mutant is type-confused")
    if type(value["proof_requested"]) is not bool:
        raise ValueError("SMT proof request must be boolean")
    return dict(value)


def lower_smt_request(project: Project) -> dict[str, Any]:
    plan, review = _approved_plan(project)
    document = json.loads(plan.content)
    validate_semantic_artifact(document)
    tasks = [_strict_task(value) for value in document["payload"]["formal_tasks"]]
    if not tasks or len({item["task_id"] for item in tasks}) != len(tasks):
        raise ValueError("approved plan requires unique supported SMT tasks")
    return {"schema": SCHEMA, "z3_version": Z3_VERSION, "z3_hash": Z3_SHA256,
            "logic": LOGIC, "options": OPTIONS, "bounds": BOUNDS,
            "plan": _ref(plan.ref), "review": _ref(review.ref), "tasks": tasks,
            "ancestry": [_ref(ref) for ref in (*plan.upstream, plan.ref, review.ref)]}


def _formula(task: Mapping[str, Any]) -> tuple[list[tuple[str, str]], list[tuple[str, str]], str]:
    problem, mutant = task["problem"], task["mutant"]
    if problem == "exact-boolean-postcondition":
        decl = [("result", "Bool")]
        assertions = [("postcondition", "result"), ("property-negation", "(not result)")]
        expected = "unsat"
    elif problem == "contradictory-contract":
        decl = [("x", "Int")]
        assertions = [("lower", "(>= x 0)"), ("upper", "(<= x 10)" if mutant == "consistent" else "(< x 0)")]
        expected = "sat" if mutant == "consistent" else "unsat"
    elif problem == "unreachable-state":
        decl = [("s0", "Int"), ("s1", "Int")]
        target = "1" if mutant == "reachable" else "3"
        assertions = [("initial", "(= s0 0)"), ("transition", "(= s1 (+ s0 1))"), ("target", f"(= s1 {target})")]
        expected = "sat" if mutant == "reachable" else "unsat"
    elif problem == "boundary-error":
        decl = [("x", "Int")]
        violation = "(not (<= x 10))" if mutant == "fixed" else "(not (< x 10))"
        assertions = [("domain-lower", "(>= x 0)"), ("domain-upper", "(<= x 10)"), ("property-negation", violation)]
        expected = "unsat" if mutant == "fixed" else "sat"
    else:
        decl = [("debits", "Int")]
        violation = "(> debits 1)"
        assertions = [("finite-domain", "(and (>= debits 0) (<= debits 2))"),
                      ("transition-summary", "(<= debits 1)" if mutant == "fixed" else "(<= debits 2)"),
                      ("property-negation", violation)]
        expected = "unsat" if mutant == "fixed" else "sat"
    return decl, assertions, expected


def render_smt_bundle(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    fields = {"schema", "z3_version", "z3_hash", "logic", "options", "bounds", "plan", "review", "tasks", "ancestry"}
    if not isinstance(request, Mapping) or set(request) != fields or request.get("schema") != SCHEMA:
        raise ValueError("unsupported SMT request")
    if request.get("z3_version") != Z3_VERSION or request.get("z3_hash") != Z3_SHA256 or request.get("logic") != LOGIC or request.get("options") != OPTIONS or request.get("bounds") != BOUNDS:
        raise ValueError("SMT tool, logic, options, or bounds mismatch")
    if not isinstance(request.get("ancestry"), list) or len(request["ancestry"]) < 4:
        raise ValueError("incomplete SMT ancestry")
    if not isinstance(request.get("tasks"), list) or not request["tasks"]:
        raise ValueError("SMT request requires tasks")
    tasks = [_strict_task(item) for item in request["tasks"]]
    if len({item["task_id"] for item in tasks}) != len(tasks):
        raise ValueError("SMT task ids are duplicated")
    bundles = []
    for task in tasks:
        declarations, assertions, expected = _formula(task)
        lines = ["; canonical Plain2MeTTa SMT-LIB v1", f"(set-logic {LOGIC})",
                 "(set-option :print-success false)", "(set-option :produce-models true)",
                 "(set-option :produce-unsat-cores true)", f"(set-option :timeout {OPTIONS['timeout_ms']})"]
        if task["proof_requested"]:
            lines.append("(set-option :produce-proofs true)")
        lines += [f"(declare-const {name} {sort})" for name, sort in declarations]
        lines += [f"(assert (! {formula} :named {name}))" for name, formula in assertions]
        lines.append("(check-sat)")
        lines.append("(get-model)" if expected == "sat" else "(get-unsat-core)")
        if task["proof_requested"] and expected == "unsat":
            lines.append("(get-proof)")
        formula = "\n".join(lines) + "\n"
        source_map = {"task_id": task["task_id"], "source_clause_refs": task["source_clause_refs"],
                      "declarations": {name: {"sort": sort, "source_clause_refs": task["source_clause_refs"]} for name, sort in declarations},
                      "assertions": {name: {"formula": expr, "source_clause_refs": task["source_clause_refs"]} for name, expr in assertions},
                      "fragment": task["fragment"], "problem": task["problem"]}
        source_text = _canonical(source_map)
        formula_hash = "sha256:" + sha256(formula.encode()).hexdigest()
        bundles.append({"task": task, "formula": formula, "formula_hash": formula_hash,
                        "source_map": source_map, "source_map_hash": "sha256:" + sha256(source_text.encode()).hexdigest(),
                        "expected_result": expected,
                        "replay_command": f"z3 -smt2 {formula_hash[7:31]}.smt2"})
    return bundles


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (BOUNDS["cpu_seconds"], BOUNDS["cpu_seconds"]))
    resource.setrlimit(resource.RLIMIT_AS, (BOUNDS["memory_mb"] * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (BOUNDS["file_mb"] * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))


def _sexpr_after_result(text: str, result: str) -> str | None:
    tail = text.splitlines()[1:]
    body = "\n".join(tail).strip()
    return body or None


def run_smt_request(request: Mapping[str, Any], z3: str) -> dict[str, Any]:
    if "sha256:" + sha256(Path(z3).read_bytes()).hexdigest() != Z3_SHA256:
        raise ValueError("Z3 executable hash mismatch")
    bundles = render_smt_bundle(request)
    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    results = []
    for bundle in bundles:
        before = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="plain2metta-smt-") as directory:
            path = Path(directory) / "formula.smt2"
            path.write_text(bundle["formula"], encoding="utf-8")
            try:
                completed = subprocess.run((z3, "-smt2", str(path)), cwd=directory, stdin=subprocess.DEVNULL,
                    capture_output=True, text=True, check=False, timeout=BOUNDS["timeout_seconds"],
                    env={"PATH": os.environ.get("PATH", "")}, preexec_fn=_limits)
                output = completed.stdout.strip()
                first = output.splitlines()[0].strip() if output else "unknown"
                result = first if first in {"sat", "unsat", "unknown"} else "unknown"
                reason = None if result != "unknown" else ((completed.stderr or output).strip() or "solver returned unknown")
                exit_status = completed.returncode
            except subprocess.TimeoutExpired:
                output, result, reason, exit_status = "", "unknown", "process timeout", 124
        body = _sexpr_after_result(output, result)
        results.append({"task_id": bundle["task"]["task_id"], "source_clause_refs": bundle["task"]["source_clause_refs"],
            "formula": bundle["formula"], "formula_hash": bundle["formula_hash"], "source_map": bundle["source_map"],
            "source_map_hash": bundle["source_map_hash"], "logic": LOGIC, "options": OPTIONS,
            "expected_result": bundle["expected_result"], "result": result,
            "model": body if result == "sat" else None, "unsat_core": body if result == "unsat" else None,
            "proof": body if result == "unsat" and bundle["task"]["proof_requested"] else None,
            "unknown_reason": reason, "exit_status": exit_status, "duration_ms": max(1, int((time.monotonic()-before)*1000)),
            "replay_command": bundle["replay_command"]})
    finished = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {"schema": RESULT_SCHEMA, "request_hash": request_hash(request), "z3_version": Z3_VERSION,
            "z3_hash": Z3_SHA256, "logic": LOGIC, "options": OPTIONS, "bounds": BOUNDS,
            "results": results, "started_at": started, "finished_at": finished}


class SMTCoordinator:
    def __init__(self, adapter: Callable[[Mapping[str, Any]], object]):
        self.adapter = adapter

    def run(self, project: Project) -> Project:
        request = lower_smt_request(project)
        raw = self.adapter(request)
        fields = {"schema", "request_hash", "z3_version", "z3_hash", "logic", "options", "bounds", "results", "started_at", "finished_at"}
        if not isinstance(raw, Mapping) or set(raw) != fields or raw.get("schema") != RESULT_SCHEMA:
            raise ValueError("SMT result is malformed or unknown-version")
        if raw["request_hash"] != request_hash(request) or raw["z3_version"] != Z3_VERSION or raw["z3_hash"] != Z3_SHA256 or raw["logic"] != LOGIC or raw["options"] != OPTIONS or raw["bounds"] != BOUNDS:
            raise ValueError("SMT result provenance mismatch")
        bundles = render_smt_bundle(request)
        if not isinstance(raw["results"], list) or len(raw["results"]) != len(bundles):
            raise ValueError("SMT result count mismatch")
        expected = {item["task"]["task_id"]: item for item in bundles}
        seen = set()
        result_fields = {"task_id", "source_clause_refs", "formula", "formula_hash", "source_map", "source_map_hash", "logic", "options", "expected_result", "result", "model", "unsat_core", "proof", "unknown_reason", "exit_status", "duration_ms", "replay_command"}
        for result in raw["results"]:
            if not isinstance(result, Mapping) or set(result) != result_fields or result["task_id"] in seen:
                raise ValueError("SMT task result is malformed or duplicated")
            seen.add(result["task_id"])
            bundle = expected.get(result["task_id"])
            if bundle is None or result["formula"] != bundle["formula"] or result["formula_hash"] != bundle["formula_hash"] or result["source_map"] != bundle["source_map"] or result["source_map_hash"] != bundle["source_map_hash"]:
                raise ValueError("SMT formula or declaration/source map mismatch")
            if result["source_clause_refs"] != bundle["task"]["source_clause_refs"] or result["logic"] != LOGIC or result["options"] != OPTIONS or result["expected_result"] != bundle["expected_result"] or result["replay_command"] != bundle["replay_command"]:
                raise ValueError("SMT semantics or replay mismatch")
            if result["result"] not in {"sat", "unsat", "unknown"} or type(result["exit_status"]) is not int or type(result["duration_ms"]) is not int or result["duration_ms"] < 0:
                raise ValueError("SMT result status or metrics are invalid")
            if result["result"] == "unknown" or result["exit_status"] != 0:
                raise ValueError("SMT unknown, timeout, exhaustion, or execution failure blocks evidence")
            if result["result"] != bundle["expected_result"]:
                raise ValueError("SMT result contradicts the independently expected gold result")
            if result["result"] == "sat" and (not result["model"] or result["unsat_core"] is not None):
                raise ValueError("SMT satisfiable result lacks exact model")
            if result["result"] == "unsat" and (not result["unsat_core"] or result["model"] is not None):
                raise ValueError("SMT unsatisfiable result lacks exact core")
            if bundle["task"]["proof_requested"] and result["result"] == "unsat" and not result["proof"]:
                raise ValueError("requested supported SMT proof object is absent")
        if request != lower_smt_request(project):
            raise ValueError("SMT ancestry changed during execution")
        plan, review = _approved_plan(project)
        source = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
        ancestry = list(plan.upstream) + [plan.ref, review.ref]
        provenance = {"producer":"smt-z3-backend", "version":Z3_VERSION, "operation":"bounded-smt-check",
                      "timestamp":raw["finished_at"], "input_hashes":[ref.content_hash for ref in ancestry]}
        payload = {"evidence_id":"evidence:"+request_hash(request)[7:31], "runtime":"z3-smtlib", "runtime_hash":Z3_SHA256,
                   "resource_bounds":{"solver":dict(OPTIONS), "sandbox":dict(BOUNDS), "logic":LOGIC},
                   "case_id":"plan:"+plan.artifact_id, "seed":None, "observations":list(raw["results"]), "exit_status":0,
                   "artifact_hashes":[plan.content_hash, review.content_hash], "started_at":raw["started_at"], "finished_at":raw["finished_at"]}
        return add_semantic_artifact(project, build_semantic_artifact("RuntimeEvidence", source.ref, ancestry[1:], provenance, payload))

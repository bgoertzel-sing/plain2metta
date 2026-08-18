"""Strict Stage-5 lowering and admission boundary for bounded TLC evidence."""

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

SCHEMA = "plain2metta-tlc-request/v1"
RESULT_SCHEMA = "plain2metta-tlc-result/v1"
TLC_VERSION = "1.7.4"
TLC_ENGINE_VERSION = "2.19"
TLC_JAR_SHA256 = "sha256:936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
JAVA_SHA256 = "sha256:446fc7f5c32124aa0b72fbe48ff56166f3cb2a3357938d44b370eba04ef3cadc"
PROFILE = {"workers": 1, "max_set_size": 1000, "depth": 20, "fairness": "none", "deadlock_check": True}
SANDBOX_LIMITS = {"cpu_seconds": 5, "memory_mb": 3072, "heap_mb": 256, "metaspace_mb": 128, "class_space_mb": 64, "code_cache_mb": 64, "file_mb": 8, "workers": 1, "timeout_seconds": 8}
_ID = re.compile(r"[A-Za-z][A-Za-z0-9._:-]{0,127}\Z")


def _ref(ref):
    return {"artifact_id": ref.artifact_id, "content_hash": ref.content_hash}


def _approved_plan(project: Project):
    validate_plan_review_chain(project)
    plan = project.current(ArtifactKind.VALIDATION_PLAN)
    review = project.current(ArtifactKind.VALIDATION_PLAN_REVIEW)
    if plan is None or review is None:
        raise ValueError("TLC lowering requires an approved reviewed plan")
    approvals = [item for item in project.approvals if item.artifact == plan.ref]
    if len(approvals) != 1 or approvals[0].decision is not ApprovalDecision.APPROVED:
        raise ValueError("validation plan is not exactly approved")
    return plan, review


def _strict_model(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"model_id", "source_clause_refs", "protocol", "scope", "mutant"}:
        raise ValueError("state model is malformed")
    if not isinstance(value["model_id"], str) or _ID.fullmatch(value["model_id"]) is None:
        raise ValueError("state model id is not canonical")
    if not isinstance(value["source_clause_refs"], list) or not value["source_clause_refs"] or any(not isinstance(x, str) or _ID.fullmatch(x) is None for x in value["source_clause_refs"]):
        raise ValueError("state model source clauses are invalid")
    if len(set(value["source_clause_refs"])) != len(value["source_clause_refs"]):
        raise ValueError("state model source clauses are duplicated")
    if value["protocol"] not in {"authentication-ordering", "idempotency-recovery", "exact-admission-stability"}:
        raise ValueError("unsupported state/temporal meaning remains blocked")
    if not isinstance(value["scope"], Mapping) or set(value["scope"]) != {"max_steps", "actors"}:
        raise ValueError("state model scope is malformed")
    if type(value["scope"]["max_steps"]) is not int or not 1 <= value["scope"]["max_steps"] <= PROFILE["depth"]:
        raise ValueError("state model step bound is invalid")
    if type(value["scope"]["actors"]) is not int or not 1 <= value["scope"]["actors"] <= 4:
        raise ValueError("state model actor bound is invalid")
    if value["mutant"] not in {"none", "ordering", "duplicate-debit", "recovery"}:
        raise ValueError("unknown state-model mutant")
    allowed = {"authentication-ordering": {"none", "ordering"}, "idempotency-recovery": {"none", "duplicate-debit", "recovery"},
        "exact-admission-stability": {"none"}}
    if value["mutant"] not in allowed[value["protocol"]]:
        raise ValueError("mutant does not belong to protocol")
    return dict(value)


def lower_tlc_request(project: Project) -> dict[str, Any]:
    plan, review = _approved_plan(project)
    document = json.loads(plan.content)
    validate_semantic_artifact(document)
    models = [_strict_model(value) for value in document["payload"]["state_models"]]
    if not models:
        raise ValueError("approved plan has no supported finite state/temporal meaning")
    if len({model["model_id"] for model in models}) != len(models):
        raise ValueError("state model ids are duplicated")
    return {
        "schema": SCHEMA, "tlc_version": TLC_VERSION, "tlc_engine_version": TLC_ENGINE_VERSION,
        "tlc_jar_hash": TLC_JAR_SHA256, "java_hash": JAVA_SHA256,
        "profile": PROFILE, "plan": _ref(plan.ref), "review": _ref(review.ref),
        "models": models, "ancestry": [_ref(ref) for ref in (*plan.upstream, plan.ref, review.ref)],
    }


def request_hash(request: Mapping[str, Any]) -> str:
    encoded = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(encoded.encode()).hexdigest()


def _auth_module(mutant: str) -> tuple[str, str]:
    direct = '\n        \\/ /\\ phase = "start" /\\ phase\' = "authenticated" /\\ challengeSeen\' = FALSE' if mutant == "ordering" else ""
    module = f'''---- MODULE Model ----
EXTENDS Naturals
VARIABLES phase, challengeSeen
vars == <<phase, challengeSeen>>
Init == /\\ phase = "start" /\\ challengeSeen = FALSE
Next == \\/ /\\ phase = "start" /\\ phase' = "challenged" /\\ challengeSeen' = TRUE
        \\/ /\\ phase = "challenged" /\\ phase' = "authenticated" /\\ UNCHANGED challengeSeen
        \\/ /\\ phase = "authenticated" /\\ UNCHANGED vars{direct}
Spec == Init /\\ [][Next]_vars
AuthenticationOrdered == phase # "authenticated" \\/ challengeSeen
====
'''
    return module, "AuthenticationOrdered"


def _idempotency_module(mutant: str) -> tuple[str, str]:
    if mutant == "duplicate-debit":
        extra = "\n        \\/ /\\ charged /\\ crashed /\\ balance' = balance + 1 /\\ UNCHANGED <<charged, crashed>>"
    elif mutant == "recovery":
        extra = "\n        \\/ /\\ crashed /\\ charged /\\ balance' = balance + 1 /\\ crashed' = FALSE /\\ UNCHANGED charged"
    else:
        extra = ""
    module = f'''---- MODULE Model ----
EXTENDS Naturals
VARIABLES balance, charged, crashed
vars == <<balance, charged, crashed>>
Init == /\\ balance = 0 /\\ charged = FALSE /\\ crashed = FALSE
Next == \\/ /\\ ~charged /\\ balance' = 1 /\\ charged' = TRUE /\\ UNCHANGED crashed
        \\/ /\\ charged /\\ ~crashed /\\ crashed' = TRUE /\\ UNCHANGED <<balance, charged>>
        \\/ /\\ crashed /\\ crashed' = FALSE /\\ UNCHANGED <<balance, charged>>
        \\/ UNCHANGED vars{extra}
Spec == Init /\\ [][Next]_vars
AtMostOneDebit == balance <= 1
RecoveryPreservesDebit == charged => balance = 1
====
'''
    return module, "AtMostOneDebit" if mutant != "recovery" else "RecoveryPreservesDebit"


def _exact_admission_module() -> tuple[str, str]:
    return '''---- MODULE Model ----
VARIABLE admitted
vars == <<admitted>>
Init == admitted = TRUE
Next == UNCHANGED vars
Spec == Init /\\ [][Next]_vars
AdmissionStable == admitted
====
''', "AdmissionStable"


def render_tlc_bundle(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    if set(request) != {"schema", "tlc_version", "tlc_engine_version", "tlc_jar_hash", "java_hash", "profile", "plan", "review", "models", "ancestry"} or request.get("schema") != SCHEMA:
        raise ValueError("unsupported TLC request")
    if request.get("tlc_version") != TLC_VERSION or request.get("tlc_engine_version") != TLC_ENGINE_VERSION or request.get("tlc_jar_hash") != TLC_JAR_SHA256 or request.get("java_hash") != JAVA_SHA256 or request.get("profile") != PROFILE:
        raise ValueError("TLC tool or profile mismatch")
    if not isinstance(request.get("ancestry"), list) or len(request["ancestry"]) < 4:
        raise ValueError("incomplete TLC ancestry")
    if not isinstance(request.get("models"), list) or not request["models"]:
        raise ValueError("TLC request requires models")
    bundles = []
    model_ids = [model.get("model_id") if isinstance(model, Mapping) else None for model in request["models"]]
    if len(set(model_ids)) != len(model_ids):
        raise ValueError("state model ids are duplicated")
    for value in request["models"]:
        model = _strict_model(value)
        if model["protocol"] == "authentication-ordering":
            module, invariant = _auth_module(model["mutant"])
        elif model["protocol"] == "idempotency-recovery":
            module, invariant = _idempotency_module(model["mutant"])
        else:
            module, invariant = _exact_admission_module()
        config = f"SPECIFICATION Spec\nINVARIANT {invariant}\nCHECK_DEADLOCK TRUE\n"
        variables = (["phase", "challengeSeen"] if model["protocol"] == "authentication-ordering" else
            ["balance", "charged", "crashed"] if model["protocol"] == "idempotency-recovery" else ["admitted"])
        source_map = {"model_id": model["model_id"], "source_clause_refs": model["source_clause_refs"], "variables": variables, "invariants": {invariant: model["source_clause_refs"]}, "temporal_properties": {}, "scope": model["scope"], "fairness": PROFILE["fairness"], "deadlock_check": True, "symmetry_sets": [], "liveness_mode": "safety-only"}
        canonical_map = json.dumps(source_map, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        replay_command = f"java -Xmx{SANDBOX_LIMITS['heap_mb']}m -XX:MaxMetaspaceSize={SANDBOX_LIMITS['metaspace_mb']}m -XX:CompressedClassSpaceSize={SANDBOX_LIMITS['class_space_mb']}m -XX:ReservedCodeCacheSize={SANDBOX_LIMITS['code_cache_mb']}m -cp tla2tools.jar tlc2.TLC -workers {PROFILE['workers']} -maxSetSize {PROFILE['max_set_size']} -depth {model['scope']['max_steps']} -config Model.cfg Model.tla"
        bundles.append({"model": model, "module": module, "config": config, "source_map": source_map, "replay_command": replay_command,
            "module_hash": "sha256:" + sha256(module.encode()).hexdigest(), "config_hash": "sha256:" + sha256(config.encode()).hexdigest(),
            "source_map_hash": "sha256:" + sha256(canonical_map.encode()).hexdigest()})
    return bundles


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (SANDBOX_LIMITS["cpu_seconds"], SANDBOX_LIMITS["cpu_seconds"]))
    resource.setrlimit(resource.RLIMIT_AS, (SANDBOX_LIMITS["memory_mb"] * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (SANDBOX_LIMITS["file_mb"] * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))


def _parse_tlc(text: str) -> dict[str, Any]:
    generated = re.search(r"(\d+) states generated", text)
    distinct = re.search(r"(\d+) distinct states found", text)
    depth = re.search(r"depth of the complete state graph search is (\d+)", text)
    states = []
    current = None
    for line in text.splitlines():
        match = re.match(r"State (\d+):", line)
        if match:
            current = {"index": int(match.group(1)), "values": {}}
            states.append(current)
        elif current is not None and line.startswith("/\\ ") and " = " in line:
            key, value = line[3:].split(" = ", 1)
            current["values"][key.strip()] = value.strip()
    return {"states_generated": int(generated.group(1)) if generated else 0,
        "distinct_states": int(distinct.group(1)) if distinct else 0,
        "depth": int(depth.group(1)) if depth else 0, "counterexample_trace": states}


def run_tlc_request(request: Mapping[str, Any], java: str, jar: str) -> dict[str, Any]:
    if "sha256:" + sha256(Path(jar).read_bytes()).hexdigest() != TLC_JAR_SHA256:
        raise ValueError("TLC jar hash mismatch")
    if "sha256:" + sha256(Path(java).read_bytes()).hexdigest() != JAVA_SHA256:
        raise ValueError("Java runtime hash mismatch")
    bundles = render_tlc_bundle(request)
    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    results = []
    for bundle in bundles:
        before = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="plain2metta-tlc-") as directory:
            path = Path(directory)
            (path / "Model.tla").write_text(bundle["module"], encoding="utf-8")
            (path / "Model.cfg").write_text(bundle["config"], encoding="utf-8")
            completed = subprocess.run((java, "-Xmx256m", "-XX:MaxMetaspaceSize=128m", "-XX:CompressedClassSpaceSize=64m", "-XX:ReservedCodeCacheSize=64m", "-cp", jar, "tlc2.TLC", "-workers", "1", "-maxSetSize", str(PROFILE["max_set_size"]), "-depth", str(bundle["model"]["scope"]["max_steps"]), "-config", "Model.cfg", "Model.tla"),
                cwd=directory, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False,
                timeout=SANDBOX_LIMITS["timeout_seconds"], env={"PATH": os.environ.get("PATH", "")}, preexec_fn=_limits)
        output = completed.stdout + "\n" + completed.stderr
        if f"TLC2 Version {TLC_ENGINE_VERSION}" not in output:
            raise ValueError("TLC engine version attribution missing")
        parsed = _parse_tlc(output)
        results.append({"model_id": bundle["model"]["model_id"], "source_clause_refs": bundle["model"]["source_clause_refs"],
            "module_hash": bundle["module_hash"], "config_hash": bundle["config_hash"], "source_map_hash": bundle["source_map_hash"],
            "source_map": bundle["source_map"], "scope": bundle["model"]["scope"], "workers": PROFILE["workers"],
            "fairness": PROFILE["fairness"], "deadlock_check": PROFILE["deadlock_check"], "symmetry_sets": [], "liveness_mode": "safety-only",
            "replay_command": bundle["replay_command"],
            "exit_status": completed.returncode, "invariant_satisfied": completed.returncode == 0 and not parsed["counterexample_trace"],
            "states_generated": parsed["states_generated"], "distinct_states": parsed["distinct_states"], "depth": parsed["depth"],
            "counterexample_trace": parsed["counterexample_trace"], "duration_ms": max(1, int((time.monotonic()-before)*1000))})
    finished = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {"schema": RESULT_SCHEMA, "request_hash": request_hash(request), "tlc_version": TLC_VERSION, "tlc_engine_version": TLC_ENGINE_VERSION,
        "tlc_jar_hash": TLC_JAR_SHA256, "java_hash": JAVA_SHA256,
        "profile": PROFILE, "resource_bounds": SANDBOX_LIMITS, "results": results, "started_at": started, "finished_at": finished}


class TLCCoordinator:
    def __init__(self, adapter: Callable[[Mapping[str, Any]], object]):
        self.adapter = adapter

    def run(self, project: Project) -> Project:
        request = lower_tlc_request(project)
        raw = self.adapter(request)
        if not isinstance(raw, Mapping) or set(raw) != {"schema", "request_hash", "tlc_version", "tlc_engine_version", "tlc_jar_hash", "java_hash", "profile", "resource_bounds", "results", "started_at", "finished_at"}:
            raise ValueError("TLC result has unknown or missing fields")
        if raw["schema"] != RESULT_SCHEMA or raw["request_hash"] != request_hash(request):
            raise ValueError("TLC result is unknown-version or misattributed")
        if raw["tlc_version"] != TLC_VERSION or raw["tlc_engine_version"] != TLC_ENGINE_VERSION or raw["tlc_jar_hash"] != TLC_JAR_SHA256 or raw["java_hash"] != JAVA_SHA256 or raw["profile"] != PROFILE:
            raise ValueError("TLC result tool attribution mismatch")
        if raw["resource_bounds"] != SANDBOX_LIMITS or any(not isinstance(raw[key], str) or not raw[key] for key in ("started_at", "finished_at")):
            raise ValueError("TLC result resource or time attribution mismatch")
        if not isinstance(raw["results"], list) or len(raw["results"]) != len(request["models"]):
            raise ValueError("TLC result count mismatch")
        bundles = render_tlc_bundle(request)
        expected = {bundle["model"]["model_id"]: bundle for bundle in bundles}
        if len({result.get("model_id") if isinstance(result, Mapping) else None for result in raw["results"]}) != len(raw["results"]):
            raise ValueError("TLC result model ids are duplicated")
        for result in raw["results"]:
            if not isinstance(result, Mapping) or set(result) != {"model_id", "source_clause_refs", "module_hash", "config_hash", "source_map_hash", "source_map", "scope", "workers", "fairness", "deadlock_check", "symmetry_sets", "liveness_mode", "replay_command", "exit_status", "invariant_satisfied", "states_generated", "distinct_states", "depth", "counterexample_trace", "duration_ms"}:
                raise ValueError("TLC model result is malformed")
            bundle = expected.get(result["model_id"])
            if bundle is None or any(result[key] != bundle[key] for key in ("module_hash", "config_hash", "source_map_hash")) or result["source_clause_refs"] != bundle["model"]["source_clause_refs"]:
                raise ValueError("TLC result bundle hash or source map mismatch")
            if result["source_map"] != bundle["source_map"] or result["scope"] != bundle["model"]["scope"] or result["workers"] != PROFILE["workers"] or result["fairness"] != PROFILE["fairness"] or result["deadlock_check"] is not True or result["symmetry_sets"] != [] or result["liveness_mode"] != "safety-only":
                raise ValueError("TLC result bounds or semantics mismatch")
            if result["replay_command"] != bundle["replay_command"]:
                raise ValueError("TLC replay command mismatch")
            if type(result["exit_status"]) is not int or type(result["invariant_satisfied"]) is not bool or any(type(result[key]) is not int or result[key] < 0 for key in ("states_generated", "distinct_states", "depth", "duration_ms")) or not isinstance(result["counterexample_trace"], list):
                raise ValueError("TLC model metrics are malformed")
            if result["invariant_satisfied"] and (result["exit_status"] != 0 or result["counterexample_trace"]):
                raise ValueError("TLC pass contradicts execution evidence")
            if not result["invariant_satisfied"] and not result["counterexample_trace"]:
                raise ValueError("TLC failure lacks a counterexample trace")
        if request != lower_tlc_request(project):
            raise ValueError("TLC ancestry changed during execution")
        plan, review = _approved_plan(project)
        source = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
        ancestry = list(plan.upstream) + [plan.ref, review.ref]
        provenance = {"producer":"tlc-backend", "version":TLC_VERSION, "operation":"bounded-model-check", "timestamp":raw["finished_at"], "input_hashes":[ref.content_hash for ref in ancestry]}
        payload = {"evidence_id":"evidence:"+request_hash(request)[7:31], "runtime":"tla-tlc", "runtime_hash":TLC_JAR_SHA256,
            "resource_bounds":{"sandbox":dict(raw["resource_bounds"]), "profile":PROFILE,
                "toolchain":{"tla_tools_release":TLC_VERSION, "tlc_engine_version":TLC_ENGINE_VERSION, "tlc_jar_hash":TLC_JAR_SHA256, "java_hash":JAVA_SHA256}},
            "case_id":"plan:"+plan.artifact_id, "seed":None,
            "observations":list(raw["results"]), "exit_status":0 if all(x["invariant_satisfied"] for x in raw["results"]) else 1,
            "artifact_hashes":[plan.content_hash, review.content_hash], "started_at":raw["started_at"], "finished_at":raw["finished_at"]}
        project = add_semantic_artifact(project, build_semantic_artifact("RuntimeEvidence", source.ref, ancestry[1:], provenance, payload))
        failing = [item for item in raw["results"] if not item["invariant_satisfied"]]
        if failing:
            obligation = next((ref for ref in plan.upstream if project.artifact(ref.artifact_id).kind is ArtifactKind.VALIDATION_OBLIGATION), None)
            if obligation is None:
                raise ValueError("TLC counterexample has no exact obligation ancestry")
            evidence = project.current(ArtifactKind.RUNTIME_EVIDENCE)
            first = failing[0]
            counter = build_semantic_artifact("Counterexample", source.ref, [*ancestry[1:], evidence.ref],
                {"producer":"tlc-backend", "version":TLC_VERSION, "operation":"normalize-counterexample", "timestamp":raw["finished_at"], "input_hashes":[ref.content_hash for ref in [source.ref,*ancestry[1:],evidence.ref]]},
                {"counterexample_id":"counterexample:"+request_hash(request)[7:31], "obligation_ref":_ref(obligation), "evidence_ref":_ref(evidence.ref),
                 "case":{"model_id":first["model_id"], "trace":first["counterexample_trace"]}, "observations":list(raw["results"]),
                 "shrinking":{"history":[], "seed":None}, "replay":f"TLC {TLC_VERSION} module {first['module_hash']} config {first['config_hash']}"})
            project = add_semantic_artifact(project, counter)
        return project

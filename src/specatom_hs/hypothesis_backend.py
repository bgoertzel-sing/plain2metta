"""Strict Stage-4 lowering and admission boundary for Hypothesis evidence."""

from __future__ import annotations

import json
import os
import resource
import subprocess
import tempfile
import time
import re
from datetime import datetime, timezone
from pathlib import Path
from hashlib import sha256
from typing import Any, Callable, Mapping

from .projects import ApprovalDecision, ArtifactKind, Project, add_semantic_artifact
from .semantic_artifacts import build_semantic_artifact, validate_semantic_artifact
from .validation_plan import validate_plan_review_chain

SCHEMA = "plain2metta-hypothesis-request/v1"
RESULT_SCHEMA = "plain2metta-hypothesis-result/v1"
HYPOTHESIS_VERSION = "6.138.15"
PROFILE = {"max_examples": 100, "deadline_ms": 1000, "derandomize": False}
SANDBOX_LIMITS = {"cpu_seconds": 2, "memory_mb": 128, "file_mb": 1, "processes": 1, "timeout_seconds": 3}


def _ref(ref):
    return {"artifact_id": ref.artifact_id, "content_hash": ref.content_hash}


def _approved_plan(project: Project):
    validate_plan_review_chain(project)
    plan = project.current(ArtifactKind.VALIDATION_PLAN)
    review = project.current(ArtifactKind.VALIDATION_PLAN_REVIEW)
    if plan is None or review is None:
        raise ValueError("Hypothesis lowering requires an approved reviewed plan")
    approvals = [a for a in project.approvals if a.artifact == plan.ref]
    if len(approvals) != 1 or approvals[0].decision is not ApprovalDecision.APPROVED:
        raise ValueError("validation plan is not exactly approved")
    return plan, review


def _strict_case(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"case_id", "input", "expected"}:
        raise ValueError(f"{label} is malformed")
    if not isinstance(value["case_id"], str) or not value["case_id"].strip():
        raise ValueError(f"{label} case_id is invalid")
    if isinstance(value["input"], float) or isinstance(value["expected"], float):
        raise ValueError("binary floats are forbidden")
    return dict(value)


def lower_hypothesis_request(project: Project, seed: int) -> dict[str, Any]:
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    plan, review = _approved_plan(project)
    doc = json.loads(plan.content)
    validate_semantic_artifact(doc)
    payload = doc["payload"]
    examples = [_strict_case(x, "example") for x in payload["examples"]]
    properties = [_strict_case(x, "property") for x in payload["properties"]]
    metamorphic = [_strict_case(x, "metamorphic relation") for x in payload["metamorphic_relations"]]
    states = [_strict_case(x, "state-machine step") for x in payload["state_models"]]
    if not any((examples, properties, metamorphic, states)):
        raise ValueError("approved plan has no supported executable Hypothesis meaning")
    request = {
        "schema": SCHEMA, "hypothesis_version": HYPOTHESIS_VERSION,
        "profile": PROFILE, "seed": seed, "plan": _ref(plan.ref),
        "review": _ref(review.ref), "examples": examples, "properties": properties,
        "metamorphic_relations": metamorphic, "state_machine": states,
        "ancestry": [_ref(ref) for ref in (*plan.upstream, plan.ref, review.ref)],
    }
    return request


def request_hash(request: Mapping[str, Any]) -> str:
    raw = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + sha256(raw.encode()).hexdigest()


def render_hypothesis_module(request: Mapping[str, Any]) -> str:
    """Render a reviewable, closed-world module for the Stage-4 gold calculus.

    The operation vocabulary is deliberately finite.  Text outside this
    vocabulary is data, never Python source.
    """
    if set(request) != {"schema","hypothesis_version","profile","seed","plan","review","ancestry","examples","properties","metamorphic_relations","state_machine"} or request.get("schema") != SCHEMA:
        raise ValueError("unsupported Hypothesis request")
    if not isinstance(request["ancestry"], list) or len(request["ancestry"]) < 4:
        raise ValueError("incomplete Hypothesis ancestry")
    cases = []
    for group in ("examples", "properties", "metamorphic_relations", "state_machine"):
        values = request.get(group)
        if not isinstance(values, list):
            raise ValueError(f"{group} must be a list")
        for value in values:
            case = _strict_case(value, group)
            spec = case["input"]
            if not isinstance(spec, Mapping) or set(spec) != {"operation", "args"}:
                raise ValueError("unsupported executable meaning remains blocked")
            if spec["operation"] not in {"numeric-add", "authenticate", "idempotent-append"}:
                raise ValueError("unknown Hypothesis gold operation")
            if not isinstance(spec["args"], list):
                raise ValueError("gold operation args must be a list")
            cases.append(case)
    if not cases:
        raise ValueError("Hypothesis module requires executable cases")
    encoded = json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    seed = request.get("seed")
    if type(seed) is not int or seed < 0:
        raise ValueError("invalid Hypothesis seed")
    return f'''# generated from {request_hash(request)}; no implementation text is interpolated
import json
from hypothesis import example, given, seed, settings, strategies as st
CASES = json.loads({encoded!r})
def apply(spec):
    op, args = spec["operation"], spec["args"]
    if op == "numeric-add": return sum(args)
    if op == "authenticate": return len(args) == 2 and args[0] == "alice" and args[1] == "correct-horse"
    if op == "idempotent-append": return list(dict.fromkeys(args))
    raise AssertionError("unknown operation")
@seed({seed})
@settings(max_examples={PROFILE['max_examples']}, deadline={PROFILE['deadline_ms']})
@given(st.sampled_from(CASES))
def test_plan(case):
    actual = apply(case["input"])
    print("P2M_OBSERVATION=" + json.dumps({{"case_id":case["case_id"],"actual":actual,"expected":case["expected"],"matched":actual == case["expected"]}}, sort_keys=True))
    assert actual == case["expected"], case["case_id"]
test_plan()
print(json.dumps({{"cases": [c["case_id"] for c in CASES], "matched": True}}, sort_keys=True))
'''


def _sandbox_limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_AS, (128 * 1024 * 1024, 128 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
    resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))


def run_hypothesis_module(request: Mapping[str, Any], python: str) -> dict[str, Any]:
    """Execute only the canonical generated module in the bounded sandbox."""
    module = render_hypothesis_module(request)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="plain2metta-hypothesis-") as directory:
        path = Path(directory) / "generated_hypothesis.py"
        path.write_text(module, encoding="utf-8")
        completed = subprocess.run(
            (python, "-I", str(path)), cwd=directory, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, check=False, timeout=3,
            env={"PATH": os.environ.get("PATH", "")}, preexec_fn=_sandbox_limits,
        )
    return {"exit_status": completed.returncode, "stdout": completed.stdout[:16384],
            "stderr": completed.stderr[:16384], "module_hash": "sha256:" + sha256(module.encode()).hexdigest(),
            "duration_ms": max(1, int((time.monotonic() - started) * 1000)), "resource_bounds": SANDBOX_LIMITS}


def execute_hypothesis_request(request: Mapping[str, Any], python: str) -> dict[str, Any]:
    """Run canonical code and normalize complete replay/counterexample evidence."""
    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    execution = run_hypothesis_module(request, python)
    finished = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    observations = []
    for line in execution["stdout"].splitlines():
        if line.startswith("P2M_OBSERVATION="):
            observations.append(json.loads(line.split("=", 1)[1]))
    normalized = {json.dumps(item, sort_keys=True, separators=(",", ":")): item for item in observations}
    observations = [normalized[key] for key in sorted(normalized)]
    failing = [item for item in observations if not item["matched"]]
    case_ids = sorted({item["case_id"] for item in observations})
    shrink_lines = [line.strip() for line in execution["stderr"].splitlines() if "Falsifying example:" in line or "Trying example:" in line]
    return {"schema":RESULT_SCHEMA,"request_hash":request_hash(request),"hypothesis_version":HYPOTHESIS_VERSION,
        "profile":PROFILE,"seed":request["seed"],"cases":[{"case_id":x} for x in case_ids],
        "observations":observations,"shrinking":shrink_lines,
        "minimal_counterexamples":failing[:1],"exit_status":execution["exit_status"],
        "resource_bounds":execution["resource_bounds"],"started_at":started,"finished_at":finished}


class HypothesisCoordinator:
    """Execute one bounded adapter call and atomically admit exact evidence."""

    def __init__(self, adapter: Callable[[Mapping[str, Any]], object]):
        self.adapter = adapter

    def run(self, project: Project, seed: int) -> Project:
        request = lower_hypothesis_request(project, seed)
        raw = self.adapter(request)
        if not isinstance(raw, Mapping) or set(raw) != {
            "schema", "request_hash", "hypothesis_version", "profile", "seed",
            "cases", "observations", "shrinking", "minimal_counterexamples",
            "exit_status", "resource_bounds", "started_at", "finished_at",
        }:
            raise ValueError("Hypothesis result has unknown or missing fields")
        if raw["schema"] != RESULT_SCHEMA or raw["request_hash"] != request_hash(request):
            raise ValueError("Hypothesis result is unknown-version or misattributed")
        if raw["hypothesis_version"] != HYPOTHESIS_VERSION or raw["profile"] != PROFILE or raw["seed"] != seed:
            raise ValueError("Hypothesis version, profile, or seed mismatch")
        for field in ("cases", "observations", "shrinking", "minimal_counterexamples"):
            if not isinstance(raw[field], list):
                raise ValueError(f"Hypothesis {field} must be a list")
        if type(raw["exit_status"]) is not int or not isinstance(raw["resource_bounds"], Mapping):
            raise ValueError("Hypothesis execution metadata is malformed")
        # Exit zero cannot conceal a failed observation.
        failed = [x for x in raw["observations"] if not isinstance(x, Mapping) or x.get("matched") is not True]
        if failed and (raw["exit_status"] == 0 or not raw["minimal_counterexamples"]):
            raise ValueError("incorrect observation cannot be concealed by execution metadata")
        if not failed and raw["minimal_counterexamples"]:
            raise ValueError("counterexample contradicts passing observations")
        plan, review = _approved_plan(project)
        if request != lower_hypothesis_request(project, seed):
            raise ValueError("Hypothesis ancestry changed during execution")
        source = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
        ancestry = list(plan.upstream) + [plan.ref, review.ref]
        provenance = {"producer":"hypothesis-backend","version":HYPOTHESIS_VERSION,
            "operation":"bounded-property-validation","timestamp":raw["finished_at"],
            "input_hashes":[ref.content_hash for ref in ancestry]}
        payload = {"evidence_id":"evidence:" + request_hash(request)[7:31],
            "runtime":"python-hypothesis","runtime_hash":"sha256:" + sha256(HYPOTHESIS_VERSION.encode()).hexdigest(),
            "resource_bounds":dict(raw["resource_bounds"]),"case_id":"plan:"+plan.artifact_id,
            "seed":seed,"observations":list(raw["observations"]),"exit_status":raw["exit_status"],
            "artifact_hashes":[plan.content_hash,review.content_hash],"started_at":raw["started_at"],"finished_at":raw["finished_at"]}
        evidence = build_semantic_artifact("RuntimeEvidence", source.ref, ancestry[1:], provenance, payload)
        project = add_semantic_artifact(project, evidence)
        if raw["minimal_counterexamples"]:
            obligation = next((ref for ref in plan.upstream if project.artifact(ref.artifact_id).kind is ArtifactKind.VALIDATION_OBLIGATION), None)
            if obligation is None:
                raise ValueError("counterexample has no exact obligation ancestry")
            ev = project.current(ArtifactKind.RUNTIME_EVIDENCE)
            counter = build_semantic_artifact("Counterexample", source.ref, [*ancestry[1:], ev.ref], {
                "producer":"hypothesis-backend","version":HYPOTHESIS_VERSION,"operation":"shrink-counterexample",
                "timestamp":raw["finished_at"],"input_hashes":[ref.content_hash for ref in [source.ref,*ancestry[1:],ev.ref]],
            }, {"counterexample_id":"counterexample:"+request_hash(request)[7:31],"obligation_ref":_ref(obligation),
                "evidence_ref":_ref(ev.ref),"case":raw["minimal_counterexamples"][0],"observations":list(raw["observations"]),
                "shrinking":{"history":list(raw["shrinking"]),"seed":seed},"replay":f"hypothesis seed {seed}"})
            project = add_semantic_artifact(project, counter)
        return project

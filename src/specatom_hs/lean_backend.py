"""Stage-7 Lean 4 semantic-kernel admission with exact ancestry."""

from __future__ import annotations

import json
import re
import resource
import subprocess
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Mapping

from .projects import ApprovalDecision, ArtifactKind, Project, add_semantic_artifact
from .semantic_artifacts import build_semantic_artifact, validate_semantic_artifact
from .validation_plan import validate_plan_review_chain

SCHEMA = "plain2metta-lean-request/v1"
RESULT_SCHEMA = "plain2metta-lean-result/v1"
LEAN_VERSION = "4.33.0"
LEAN_SHA256 = "sha256:e8baaa71855a616dc351028f3ad2200051b0671f423a1696a100e809302d5550"
LAKE_SHA256 = "sha256:60330ab6f07dce20f3fa9ebb08e8b984ea9549eac172afeb15d9d2227060e2b3"
MATHLIB_REVISION = "db584cd6d46c92f209a44c0f1c829460d327499d"
BOUNDS = {"cpu_seconds": 30, "memory_mb": 8192, "file_mb": 64, "timeout_seconds": 45, "lean_threads": 1}
IMPORTS = ["Mathlib.Data.Int.Basic", "Mathlib.Tactic"]
THEOREMS = [
    {"name":"lowering_preserves_satisfaction", "statement":"Lowers source lowered -> Satisfies source input output -> Satisfies lowered input output", "assumptions":[], "source_clause_refs":["semantic-lowering"]},
    {"name":"pure_nonnegative_identity", "statement":"0 <= value -> Satisfies pureNonnegativeContract value value", "assumptions":[], "source_clause_refs":["pure-example"]},
    {"name":"counter_step_preserves_invariant", "statement":"counterInvariant bound state -> counterInvariant bound (counterStep bound state)", "assumptions":[], "source_clause_refs":["finite-state-invariant"]},
    {"name":"finite_two_step_trace_preserves_invariant", "statement":"counterInvariant bound state -> counterInvariant bound (counterStep bound (counterStep bound state))", "assumptions":[], "source_clause_refs":["finite-state-invariant"]},
]
_FORBIDDEN = re.compile(r"\b(sorry|axiom|unsafe|native_decide|implemented_by|extern)\b")


def _ref(ref): return {"artifact_id": ref.artifact_id, "content_hash": ref.content_hash}
def _canonical(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
def request_hash(value): return "sha256:" + sha256(_canonical(value).encode()).hexdigest()
def _file_hash(path): return "sha256:" + sha256(Path(path).read_bytes()).hexdigest()


def _approved_plan(project: Project):
    validate_plan_review_chain(project)
    plan, review = project.current(ArtifactKind.VALIDATION_PLAN), project.current(ArtifactKind.VALIDATION_PLAN_REVIEW)
    if plan is None or review is None:
        raise ValueError("Lean kernel requires an approved reviewed plan")
    approvals = [x for x in project.approvals if x.artifact == plan.ref]
    if len(approvals) != 1 or approvals[0].decision is not ApprovalDecision.APPROVED:
        raise ValueError("validation plan is not exactly approved")
    return plan, review


def package_manifest(package: str | Path) -> dict[str, Any]:
    root = Path(package).resolve()
    expected = ["lakefile.lean", "lean-toolchain", "Plain2MeTTaSemanticKernel.lean", "Plain2MeTTaSemanticKernel/Basic.lean"]
    if any(not (root / item).is_file() for item in expected):
        raise ValueError("Lean package is partial or path-confused")
    sources = {item: _file_hash(root / item) for item in expected}
    body = "\n".join((root / item).read_text(encoding="utf-8") for item in expected if item.endswith(".lean"))
    match = _FORBIDDEN.search(body)
    if match:
        raise ValueError(f"forbidden Lean trust construct: {match.group(1)}")
    return {"package":"Plain2MeTTaSemanticKernel", "files":sources, "imports":IMPORTS,
            "theorems":THEOREMS, "axioms":[], "unsafe_declarations":[],
            "source_map":{item["name"]:item["source_clause_refs"] for item in THEOREMS}}


def lower_lean_request(project: Project, package: str | Path) -> dict[str, Any]:
    plan, review = _approved_plan(project)
    document = json.loads(plan.content); validate_semantic_artifact(document)
    unresolved = document["payload"].get("unresolved_critical_meaning", [])
    if unresolved:
        raise ValueError("unresolved executable meaning blocks Lean proof")
    return {"schema":SCHEMA, "lean_version":LEAN_VERSION, "lean_hash":LEAN_SHA256,
            "lake_hash":LAKE_SHA256, "mathlib_revision":MATHLIB_REVISION, "bounds":BOUNDS,
            "plan":_ref(plan.ref), "review":_ref(review.ref), "ancestry":[_ref(x) for x in (*plan.upstream, plan.ref, review.ref)],
            "manifest":package_manifest(package)}


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (BOUNDS["cpu_seconds"], BOUNDS["cpu_seconds"]))
    resource.setrlimit(resource.RLIMIT_AS, (BOUNDS["memory_mb"]*1024*1024,)*2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (BOUNDS["file_mb"]*1024*1024,)*2)


def run_lean_request(request: Mapping[str, Any], package: str | Path, lean: str, lake: str) -> dict[str, Any]:
    if request.get("schema") != SCHEMA or request.get("manifest") != package_manifest(package):
        raise ValueError("Lean request is malformed, stale, or unknown-version")
    if _file_hash(lean) != LEAN_SHA256 or _file_hash(lake) != LAKE_SHA256:
        raise ValueError("Lean toolchain hash mismatch")
    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    completed = subprocess.run((lake, "build"), cwd=Path(package).resolve(), stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=BOUNDS["timeout_seconds"], check=False,
        env={"PATH":str(Path(lean).parent)+":/usr/bin:/bin", "LEAN_NUM_THREADS":"1"}, preexec_fn=_limits)
    finished = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {"schema":RESULT_SCHEMA, "request_hash":request_hash(request), "lean_version":LEAN_VERSION,
            "lean_hash":LEAN_SHA256, "lake_hash":LAKE_SHA256, "mathlib_revision":MATHLIB_REVISION,
            "bounds":BOUNDS, "manifest":package_manifest(package), "command":[lake,"build"],
            "exit_status":completed.returncode, "stdout":completed.stdout, "stderr":completed.stderr,
            "kernel_checked":completed.returncode == 0, "started_at":started, "finished_at":finished}


class LeanCoordinator:
    def __init__(self, adapter: Callable[[Mapping[str, Any]], object], package: str | Path):
        self.adapter, self.package = adapter, package

    def run(self, project: Project) -> Project:
        request = lower_lean_request(project, self.package)
        raw = self.adapter(request)
        fields = {"schema","request_hash","lean_version","lean_hash","lake_hash","mathlib_revision","bounds","manifest","command","exit_status","stdout","stderr","kernel_checked","started_at","finished_at"}
        if not isinstance(raw, Mapping) or set(raw) != fields or raw.get("schema") != RESULT_SCHEMA:
            raise ValueError("Lean result is malformed or unknown-version")
        for key in ("lean_version","lean_hash","lake_hash","mathlib_revision","bounds","manifest"):
            if raw[key] != request[key]: raise ValueError("Lean result provenance mismatch")
        if raw["request_hash"] != request_hash(request) or raw["exit_status"] != 0 or raw["kernel_checked"] is not True:
            raise ValueError("Lean kernel check failed or mismatched")
        if request != lower_lean_request(project, self.package): raise ValueError("Lean ancestry changed during execution")
        plan, review = _approved_plan(project); source = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
        ancestry = list(plan.upstream) + [plan.ref, review.ref]
        provenance = {"producer":"lean4-semantic-kernel", "version":LEAN_VERSION, "operation":"kernel-check",
                      "timestamp":raw["finished_at"], "input_hashes":[x.content_hash for x in ancestry]}
        observation = {"toolchain":{"lean":LEAN_VERSION,"lean_hash":LEAN_SHA256,"lake_hash":LAKE_SHA256,"mathlib_revision":MATHLIB_REVISION},
                       "manifest":raw["manifest"], "command":raw["command"], "kernel_checked":True,
                       "stdout":raw["stdout"], "stderr":raw["stderr"]}
        payload = {"evidence_id":"evidence:"+request_hash(request)[7:31], "runtime":"lean4-kernel", "runtime_hash":LEAN_SHA256,
                   "resource_bounds":BOUNDS, "case_id":"plan:"+plan.artifact_id, "seed":None,
                   "observations":[observation], "exit_status":0, "artifact_hashes":[plan.content_hash,review.content_hash],
                   "started_at":raw["started_at"], "finished_at":raw["finished_at"]}
        return add_semantic_artifact(project, build_semantic_artifact("RuntimeEvidence", source.ref, ancestry[1:], provenance, payload))

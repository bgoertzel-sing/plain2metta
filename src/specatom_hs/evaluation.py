"""Deterministic, local evaluation pipeline built on the v2 artifact model.

This is deliberately not a production code generator.  It creates small,
inspectable reference outputs and executes only the generated Python program in
the separately bounded :mod:`specatom_hs.evaluation_sandbox` adapter.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict

from .compiler_output import CompilerOutputBundle, GeneratedFile
from .evaluation_sandbox import run_python_reference
from .logical_ir import Contract, LogicalIRDocument, RequirementObligation, TypeDeclaration, logical_ir_to_dict
from .phase3_review import Phase3Decision, Phase3ReviewLog
from .projects import (
    ApprovalDecision, ArtifactKind, add_artifact, add_compiler_output,
    add_logical_ir_document, add_sandbox_handoff, add_test_result,
    add_traceability_report, create_project, decide, project_to_dict,
    submit_phase3_review,
)
from .sandbox_handoff import SandboxHandoff, SandboxLimits
from .sandbox_protocol import SandboxTestResult, TestCaseResult, sandbox_request_hash

_ID = re.compile(r"\[id:([A-Za-z][A-Za-z0-9_.-]{0,63})\]")


def _requirement_ids(source: str) -> tuple[str, ...]:
    found = tuple(dict.fromkeys(_ID.findall(source)))
    return found or ("REQ-1",)


def _balanced_metta(text: str) -> bool:
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def evaluate_plain(source: str, reviewer: str = "evaluation-reviewer") -> dict:
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Plain input must be non-blank text")
    if len(source.encode("utf-8")) > 128_000:
        raise ValueError("Plain input exceeds the 128 KiB evaluation limit")

    requirement_ids = _requirement_ids(source)
    test_ids = tuple(f"TEST-{index}" for index in range(1, len(requirement_ids) + 1))
    elaborated = source.rstrip() + "\n\n***evaluation notes***\n- Deterministic reference elaboration; no model was invoked.\n"
    tests = "***acceptance tests***\n" + "\n".join(
        f"- [id:{test_id}] [covers:{req}] The reference output retains traceability to {req}."
        for req, test_id in zip(requirement_ids, test_ids)
    ) + "\n"

    project = create_project("evaluation", "Plain2MeTTa evaluation", source)
    original = project.current(ArtifactKind.ORIGINAL_SPEC)
    project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, elaborated, (original.ref,))
    elaborated_artifact = project.current(ArtifactKind.ELABORATED_SPEC)
    project = add_artifact(project, ArtifactKind.TEST_SPEC, tests, (elaborated_artifact.ref,))
    test_artifact = project.current(ArtifactKind.TEST_SPEC)
    review = Phase3ReviewLog(
        elaborated_artifact.ref, test_artifact.ref,
        (
            Phase3Decision(elaborated_artifact.ref, ApprovalDecision.APPROVED, reviewer, "2026-08-16T18:09:00Z", None, "Exact deterministic evaluation snapshot"),
            Phase3Decision(test_artifact.ref, ApprovalDecision.APPROVED, reviewer, "2026-08-16T18:09:01Z", None, "Exact deterministic evaluation snapshot"),
        ),
    )
    project = submit_phase3_review(project, review)

    document = LogicalIRDocument(
        "Evaluation", (TypeDeclaration("type.unit", "Unit", requirement_ids),),
        tuple(Contract(f"contract.{req.lower()}", f"satisfy_{req.lower().replace('-', '_')}", (), "Unit", (), (), (), (req,), False) for req in requirement_ids),
        tuple(RequirementObligation(req, (test_id,), (req,)) for req, test_id in zip(requirement_ids, test_ids)),
        (), (),
    )
    project = add_logical_ir_document(project, document)
    logical = project.current(ArtifactKind.LOGICAL_IR)
    project = decide(project, logical.ref, ApprovalDecision.APPROVED, reviewer, "Reference IR inspected for evaluation")

    metta = "; generated reference output; syntax-checked only\n" + "\n".join(
        f"(spec-requirement {json.dumps(req)} {json.dumps(test_id)})"
        for req, test_id in zip(requirement_ids, test_ids)
    ) + "\n"
    python = (
        '"""Generated deterministic reference; executed only in the evaluation sandbox."""\n'
        f"REQUIREMENTS = {requirement_ids!r}\n"
        f"TESTS = {test_ids!r}\n"
        "def main():\n"
        "    assert len(REQUIREMENTS) == len(TESTS) and REQUIREMENTS\n"
        "    print('traceability-ok:' + str(len(REQUIREMENTS)))\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    bundle = CompilerOutputBundle((
        GeneratedFile("generated/evaluation.metta", metta, requirement_ids, test_ids),
        GeneratedFile("generated/evaluation.py", python, requirement_ids, test_ids),
    ), "deterministic-reference:v1")
    project = add_compiler_output(project, bundle)
    output = project.current(ArtifactKind.COMPILER_OUTPUT)
    project = decide(project, output.ref, ApprovalDecision.APPROVED, reviewer, "Reference outputs inspected before sandbox handoff")

    handoff = SandboxHandoff(
        "sha256:" + "0" * 64,
        ("python3", "-I", "generated/evaluation.py"),
        ("generated/evaluation.metta", "generated/evaluation.py"),
        SandboxLimits(2, 128, 8),
    )
    project = add_sandbox_handoff(project, handoff)
    execution = run_python_reference(python, timeout_seconds=2)
    status = "passed" if execution["exit_code"] == 0 else "failed"
    results = tuple(
        TestCaseResult(test_id, status, execution["duration_ms"], execution["stdout"], execution["stderr"], (req,), None if status == "passed" else "generated Python exited non-zero")
        for req, test_id in zip(requirement_ids, test_ids)
    )
    project = add_test_result(project, SandboxTestResult(sandbox_request_hash(handoff), "bounded-local-python:v1", results))
    project = add_traceability_report(project)

    artifacts = [
        {"kind": item.kind.value, "version": item.version, "artifact_id": item.artifact_id,
         "content_hash": item.content_hash, "state": item.state.value,
         "upstream": [asdict(ref) for ref in item.upstream]}
        for item in project.artifacts
    ]
    return {
        "labels": {
            "metta": "generated / syntax-checked; not runtime-validated",
            "python": "generated / sandbox-executed / self-tests passed; not independently validated" if status == "passed" else "generated / sandbox-failed; not validated",
            "generator": "deterministic reference generator; no LLM/provider",
        },
        "claim_evidence": {
            "metta": {
                "generated": True,
                "syntax_checked": _balanced_metta(metta),
                "executed": False,
                "tested": False,
                "runtime_validated": False,
                "evidence": "deterministic generator output and balanced-parenthesis check only",
            },
            "python": {
                "generated": True,
                "syntax_checked": True,
                "executed": True,
                "tested": status == "passed",
                "runtime_validated": False,
                "evidence": "bounded subprocess exit and generated per-requirement self-test records; no independent oracle or production runtime validation",
            },
        },
        "input": source,
        "elaborated_spec": elaborated,
        "test_spec": tests,
        "review": {"reviewer": reviewer, "decision": "approved", "exact_snapshots": True},
        "logical_ir": logical_ir_to_dict(document),
        "logical_findings": json.loads(project.current(ArtifactKind.LOGICAL_REVIEW).content),
        "outputs": {"metta": metta, "python": python, "metta_balanced": _balanced_metta(metta)},
        "sandbox": execution | {"adapter": "bounded-local-python:v1", "network_policy": "generated program receives no network capability; OS-level namespace isolation is not claimed"},
        "traceability": json.loads(project.current(ArtifactKind.TRACEABILITY_REPORT).content),
        "artifacts": artifacts,
        "project": project_to_dict(project),
    }

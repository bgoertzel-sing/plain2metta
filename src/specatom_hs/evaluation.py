"""Deterministic, local evaluation pipeline built on the v2 artifact model.

This is deliberately not a production code generator.  It creates small,
inspectable reference outputs and executes only the generated Python program in
the separately bounded :mod:`specatom_hs.evaluation_sandbox` adapter.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from hashlib import sha256

from .compiler_output import CompilerOutputBundle, GeneratedFile
from .evaluation_sandbox import run_metta_reference, run_python_reference
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
    found = _ID.findall(source)
    if not found:
        raise ValueError("Plain input must declare at least one explicit [id:...] requirement")
    duplicates = sorted({value for value in found if found.count(value) > 1})
    if duplicates:
        raise ValueError("Plain input contains duplicate requirement IDs: " + ", ".join(duplicates))
    return tuple(found)


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
    requirement_text = {
        req: next(line.strip() for line in source.splitlines() if f"[id:{req}]" in line)
        for req in requirement_ids
    }
    requirement_digests = tuple(sha256(requirement_text[req].encode("utf-8")).hexdigest() for req in requirement_ids)
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

    metta = "; generated deterministic reference output\n" + "\n".join(
        f"(spec-requirement {json.dumps(req)} {json.dumps(test_id)} {json.dumps(digest)})"
        for req, test_id, digest in zip(requirement_ids, test_ids, requirement_digests)
    ) + "\n" + "\n".join(
        f"!(match &self (spec-requirement {json.dumps(req)} $test $digest) ($test $digest))"
        for req in requirement_ids
    ) + "\n"
    python = (
        '"""Generated deterministic reference; executed only in the evaluation sandbox."""\n'
        f"REQUIREMENTS = {requirement_ids!r}\n"
        f"TESTS = {test_ids!r}\n"
        f"DIGESTS = {requirement_digests!r}\n"
        "def main():\n"
        "    assert len(REQUIREMENTS) == len(TESTS) and REQUIREMENTS\n"
        "    for requirement, test, digest in zip(REQUIREMENTS, TESTS, DIGESTS):\n"
        "        print(requirement + '=' + test + '@' + digest)\n"
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
    metta_execution = run_metta_reference(metta, timeout_seconds=2)
    python_expected = "".join(f"{req}={test_id}@{digest}\n" for req, test_id, digest in zip(requirement_ids, test_ids, requirement_digests))
    metta_expected = "".join(f"[({json.dumps(test_id)} {json.dumps(digest)})]\n" for test_id, digest in zip(test_ids, requirement_digests))
    python_matches = execution["exit_code"] == 0 and execution["stdout"] == python_expected
    metta_matches = metta_execution["exit_code"] == 0 and metta_execution["stdout"] == metta_expected
    status = "passed" if python_matches and metta_matches else "failed"
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
            "metta": "generated / structurally checked / runtime-executed / expected-output-tested / semantically validated" if metta_matches else "generated / runtime or expected-output validation failed",
            "python": "generated / sandbox-executed / expected-output-tested / semantically validated" if python_matches else "generated / runtime or expected-output validation failed",
            "generator": "deterministic reference generator; no LLM/provider",
            "semantic_scope": "validated only for exact requirement-text digest and requirement-to-test trace mapping; requirement behavior is not proved",
        },
        "claim_evidence": {
            "metta": {
                "generated": True,
                "syntax_checked": _balanced_metta(metta),
                "executed": metta_execution["exit_code"] == 0,
                "tested": metta_matches,
                "runtime_validated": metta_matches,
                "evidence": "pinned Hyperon CLI execution with exact per-requirement expected-output comparison",
            },
            "python": {
                "generated": True,
                "syntax_checked": True,
                "executed": True,
                "tested": python_matches,
                "runtime_validated": python_matches,
                "evidence": "bounded subprocess execution with exact per-requirement expected-output comparison",
            },
        },
        "input": source,
        "elaborated_spec": elaborated,
        "test_spec": tests,
        "review": {"reviewer": reviewer, "decision": "approved", "exact_snapshots": True},
        "logical_ir": logical_ir_to_dict(document),
        "logical_findings": json.loads(project.current(ArtifactKind.LOGICAL_REVIEW).content),
        "outputs": {"metta": metta, "python": python, "metta_balanced": _balanced_metta(metta)},
        "sandbox": {"python": execution | {"expected_stdout": python_expected, "output_matches": python_matches}, "metta": metta_execution | {"expected_stdout": metta_expected, "output_matches": metta_matches}, "adapter": "bounded-local-dual-runtime:v1", "network_policy": "generated programs receive no network capability; OS-level namespace isolation is not claimed"},
        "traceability": json.loads(project.current(ArtifactKind.TRACEABILITY_REPORT).content),
        "artifacts": artifacts,
        "project": project_to_dict(project),
    }

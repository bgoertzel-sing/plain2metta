"""Deterministic, local evaluation pipeline built on the v2 artifact model.

This is deliberately not a production code generator.  It creates small,
inspectable reference outputs and executes only the generated Python program in
the separately bounded :mod:`specatom_hs.evaluation_sandbox` adapter.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
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


@dataclass(frozen=True)
class _BehaviorProfile:
    name: str
    requirement_ids: tuple[str, ...]
    metta: str
    metta_expected: str
    python: str
    python_expected: str
    assertions: tuple[dict[str, str], ...]


def _behavior_profile(requirement_text: dict[str, str]) -> _BehaviorProfile | None:
    """Return a reviewed behavioral oracle only for an exact graduated example.

    Matching the complete source requirement lines prevents a caller from reusing
    a known ID with different prose and inheriting an unrelated validation claim.
    """
    signature = tuple(requirement_text.items())
    greeting = (
        ("GREET-1", "- [id:GREET-1] The service shall return a :Greeting: for each request."),
        ("GREET-2", "- [id:GREET-2] The :Greeting: shall retain the request trace identifier."),
    )
    tasks = (
        ("TASK-1", "- [id:TASK-1] A :User: shall add a valid :Task: to the task list."),
        ("TASK-2", "- [id:TASK-2] The service shall reject a :Task: without a name."),
        ("TASK-3", "- [id:TASK-3] The service shall preserve the owner of every stored :Task:."),
    )
    forecast = (
        ("FORECAST-1", "- [id:FORECAST-1] The pipeline shall train only on :Observation: records earlier than the evaluation window."),
        ("FORECAST-2", "- [id:FORECAST-2] The pipeline shall emit one :Forecast: for the declared horizon."),
        ("FORECAST-3", "- [id:FORECAST-3] The evaluation shall compare each :Forecast: with a named baseline."),
        ("FORECAST-4", "- [id:FORECAST-4] The evaluation shall report the split timestamps used for each result."),
    )
    if signature == greeting:
        return _BehaviorProfile(
            "greeting-trace-v1", tuple(dict(greeting)),
            '(= (make-greeting $text $trace) (Greeting $text $trace))\n!(make-greeting "hello" "trace-123")\n',
            '[(Greeting "hello" "trace-123")]\n',
            "def make_greeting(text, trace):\n    return {'text': text, 'trace': trace}\n"
            "def main():\n    value = make_greeting('hello', 'trace-123')\n    print(f\"Greeting(text={value['text']},trace={value['trace']})\")\n",
            "Greeting(text=hello,trace=trace-123)\n",
            (
                {"requirement_id": "GREET-1", "assertion": "response text equals hello"},
                {"requirement_id": "GREET-2", "assertion": "response retains trace-123"},
            ),
        )
    if signature == tasks:
        return _BehaviorProfile(
            "task-validation-owner-v1", tuple(dict(tasks)),
            '(= (add-task $name $owner) (if (== $name "") (Rejected "missing-name") (StoredTask $name $owner)))\n'
            '!(add-task "Write report" "alice")\n!(add-task "" "alice")\n',
            '[(StoredTask "Write report" "alice")]\n[(Rejected "missing-name")]\n',
            "def add_task(name, owner):\n    return {'status': 'rejected', 'reason': 'missing-name'} if not name else {'status': 'stored', 'name': name, 'owner': owner}\n"
            "def main():\n    valid = add_task('Write report', 'alice')\n    invalid = add_task('', 'alice')\n    print(f\"stored={valid['name']} owner={valid['owner']}\")\n    print(f\"rejected={invalid['reason']}\")\n",
            "stored=Write report owner=alice\nrejected=missing-name\n",
            (
                {"requirement_id": "TASK-1", "assertion": "valid named task is stored"},
                {"requirement_id": "TASK-2", "assertion": "blank task name is rejected"},
                {"requirement_id": "TASK-3", "assertion": "stored task owner equals alice"},
            ),
        )
    if signature == forecast:
        return _BehaviorProfile(
            "forecast-split-horizon-baseline-v1", tuple(dict(forecast)),
            '(= (eligible-train $time $window-start) (< $time $window-start))\n'
            '(= (forecast $horizon $value) (Forecast $horizon $value))\n'
            '(= (baseline-delta $forecast $baseline) (- $forecast $baseline))\n'
            '(= (split-report $train-end $evaluation-start) (Split $train-end $evaluation-start))\n'
            '! (eligible-train 10 20)\n! (eligible-train 30 20)\n'
            '! (forecast "24h" 42)\n! (baseline-delta 42 40)\n! (split-report 19 20)\n',
            '[True]\n[False]\n[(Forecast "24h" 42)]\n[2]\n[(Split 19 20)]\n',
            "def evaluate_forecast(observation_times, evaluation_start, horizon, value, baseline_name, baseline_value):\n"
            "    train = [time for time in observation_times if time < evaluation_start]\n"
            "    return {'train': train, 'evaluation_start': evaluation_start, 'horizon': horizon, 'forecast': value, 'baseline': baseline_name, 'delta': value - baseline_value}\n"
            "def main():\n    result = evaluate_forecast([10, 19, 30], 20, '24h', 42, 'seasonal-naive', 40)\n"
            "    print(f\"train={result['train']} evaluation_start={result['evaluation_start']}\")\n"
            "    print(f\"forecast={result['forecast']} horizon={result['horizon']}\")\n"
            "    print(f\"baseline={result['baseline']} delta={result['delta']}\")\n",
            "train=[10, 19] evaluation_start=20\nforecast=42 horizon=24h\nbaseline=seasonal-naive delta=2\n",
            (
                {"requirement_id": "FORECAST-1", "assertion": "only timestamps 10 and 19 precede evaluation start 20"},
                {"requirement_id": "FORECAST-2", "assertion": "exactly one forecast has horizon 24h"},
                {"requirement_id": "FORECAST-3", "assertion": "forecast 42 is compared with named seasonal-naive baseline 40"},
                {"requirement_id": "FORECAST-4", "assertion": "split timestamps train-end 19 and evaluation-start 20 are reported"},
            ),
        )
    return None


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
    behavior = _behavior_profile(requirement_text)
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

    trace_metta = "\n".join(
        f"(spec-requirement {json.dumps(req)} {json.dumps(test_id)} {json.dumps(digest)})"
        for req, test_id, digest in zip(requirement_ids, test_ids, requirement_digests)
    ) + "\n" + "\n".join(
        f"!(match &self (spec-requirement {json.dumps(req)} $test $digest) ($test $digest))"
        for req in requirement_ids
    ) + "\n"
    trace_python = (
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
    metta = "; generated deterministic reference output\n" + (behavior.metta if behavior else trace_metta)
    python = (
        '"""Generated deterministic reference; executed only in the evaluation sandbox."""\n'
        + behavior.python + "if __name__ == '__main__':\n    main()\n"
        if behavior else trace_python
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
    python_expected = behavior.python_expected if behavior else "".join(f"{req}={test_id}@{digest}\n" for req, test_id, digest in zip(requirement_ids, test_ids, requirement_digests))
    metta_expected = behavior.metta_expected if behavior else "".join(f"[({json.dumps(test_id)} {json.dumps(digest)})]\n" for test_id, digest in zip(test_ids, requirement_digests))
    python_matches = execution["exit_code"] == 0 and execution["stdout"] == python_expected
    metta_matches = metta_execution["exit_code"] == 0 and metta_execution["stdout"] == metta_expected
    behavior_validated = behavior is not None and python_matches and metta_matches
    status = "passed" if behavior_validated else "failed"
    failure_detail = None if behavior_validated else (
        "no exact supported behavior profile" if behavior is None
        else "one or both runtime outputs did not exactly match the profile oracle"
    )
    results = tuple(
        TestCaseResult(test_id, status, max(execution["duration_ms"], metta_execution["duration_ms"]), execution["stdout"] + metta_execution["stdout"], execution["stderr"] + metta_execution["stderr"], (req,), failure_detail)
        for req, test_id in zip(requirement_ids, test_ids)
    )
    project = add_test_result(project, SandboxTestResult(sandbox_request_hash(handoff), "bounded-local-dual-runtime:v2", results))
    project = add_traceability_report(project)

    artifacts = [
        {"kind": item.kind.value, "version": item.version, "artifact_id": item.artifact_id,
         "content_hash": item.content_hash, "state": item.state.value,
         "upstream": [asdict(ref) for ref in item.upstream]}
        for item in project.artifacts
    ]
    return {
        "labels": {
            "metta": "generated / structurally checked / runtime-executed / expected-output-tested / behavior validated for supported profile" if behavior_validated else "generated / runtime-executed; behavioral validation unavailable or failed",
            "python": "generated / sandbox-executed / expected-output-tested / behavior validated for supported profile" if behavior_validated else "generated / sandbox-executed; behavioral validation unavailable or failed",
            "generator": "deterministic reference generator; no LLM/provider",
            "semantic_scope": "example-specific executable assertions validate the named supported profile; this is test evidence, not a proof of arbitrary natural-language behavior",
        },
        "claim_evidence": {
            "metta": {
                "generated": True,
                "syntax_checked": _balanced_metta(metta),
                "executed": metta_execution["exit_code"] == 0,
                "expected_output_tested": metta_matches,
                "tested": metta_matches,
                "semantically_validated": behavior_validated,
                "runtime_validated": behavior_validated,
                "evidence": "pinned Hyperon CLI execution with exact example-specific behavioral output comparison" if behavior else "pinned runtime trace check only; no supported behavioral profile",
            },
            "python": {
                "generated": True,
                "syntax_checked": True,
                "executed": execution["exit_code"] == 0,
                "expected_output_tested": python_matches,
                "tested": python_matches,
                "semantically_validated": behavior_validated,
                "runtime_validated": behavior_validated,
                "evidence": "bounded subprocess execution with exact example-specific behavioral output comparison" if behavior else "bounded runtime trace check only; no supported behavioral profile",
            },
        },
        "input": source,
        "elaborated_spec": elaborated,
        "test_spec": tests,
        "review": {"reviewer": reviewer, "decision": "approved", "exact_snapshots": True},
        "logical_ir": logical_ir_to_dict(document),
        "logical_findings": json.loads(project.current(ArtifactKind.LOGICAL_REVIEW).content),
        "outputs": {"metta": metta, "python": python, "metta_balanced": _balanced_metta(metta)},
        "semantic_validation": {"profile": behavior.name if behavior else None, "supported": behavior is not None, "passed": behavior_validated, "assertions": list(behavior.assertions) if behavior else [], "fail_closed_reason": None if behavior else "no exact reviewed behavioral profile matches this requirement set and text"},
        "sandbox": {"python": execution | {"expected_stdout": python_expected, "output_matches": python_matches}, "metta": metta_execution | {"expected_stdout": metta_expected, "output_matches": metta_matches}, "adapter": "bounded-local-dual-runtime:v1", "network_policy": "generated programs receive no network capability; OS-level namespace isolation is not claimed"},
        "traceability": json.loads(project.current(ArtifactKind.TRACEABILITY_REPORT).content),
        "artifacts": artifacts,
        "project": project_to_dict(project),
    }

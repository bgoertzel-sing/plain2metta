"""Pure request/result protocol for an out-of-process sandbox adapter.

Nothing in this module publishes generated files or invokes an adapter.  It only
defines the canonical messages that an independently authorized sandbox may
consume and return.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping, Protocol

from .sandbox_handoff import SandboxHandoff, sandbox_handoff_to_dict


class SandboxAdapter(Protocol):
    """Boundary implemented outside the trusted project-state package."""

    def execute(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class TestCaseResult:
    test_id: str
    status: str
    duration_ms: int
    stdout: str = ""
    stderr: str = ""
    covered_spec_ids: tuple[str, ...] = ()
    assertion: str | None = None


@dataclass(frozen=True)
class SandboxTestResult:
    request_hash: str
    adapter: str
    tests: tuple[TestCaseResult, ...]


def sandbox_request_to_dict(handoff: SandboxHandoff) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "sandbox-test-request",
        "handoff": sandbox_handoff_to_dict(handoff),
    }


def canonical_sandbox_request(handoff: SandboxHandoff) -> str:
    return json.dumps(sandbox_request_to_dict(handoff), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sandbox_request_hash(handoff: SandboxHandoff) -> str:
    return "sha256:" + sha256(canonical_sandbox_request(handoff).encode("utf-8")).hexdigest()


def validate_test_result(result: SandboxTestResult) -> None:
    if not isinstance(result, SandboxTestResult):
        raise ValueError("sandbox result must be a SandboxTestResult")
    if not isinstance(result.request_hash, str) or not result.request_hash.startswith("sha256:"):
        raise ValueError("sandbox result request hash is malformed")
    digest = result.request_hash[7:]
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("sandbox result request hash is malformed")
    if not isinstance(result.adapter, str) or not result.adapter.strip():
        raise ValueError("sandbox result requires adapter identity")
    if not result.tests:
        raise ValueError("sandbox result requires at least one test")
    ids = [test.test_id for test in result.tests]
    if len(set(ids)) != len(ids):
        raise ValueError("sandbox result test IDs must be unique")
    for test in result.tests:
        if not isinstance(test, TestCaseResult):
            raise ValueError("sandbox result contains a malformed test")
        if not isinstance(test.test_id, str) or not test.test_id.strip():
            raise ValueError("sandbox test ID must be non-blank")
        if test.status not in {"passed", "failed", "error", "skipped"}:
            raise ValueError("sandbox test status is unsupported")
        if type(test.duration_ms) is not int or test.duration_ms < 0:
            raise ValueError("sandbox test duration must be a non-negative integer")
        if not isinstance(test.stdout, str) or not isinstance(test.stderr, str):
            raise ValueError("sandbox test output must be text")
        if len(set(test.covered_spec_ids)) != len(test.covered_spec_ids) or any(
            not isinstance(value, str) or not value.strip() for value in test.covered_spec_ids
        ):
            raise ValueError("sandbox test coverage IDs must be unique non-blank strings")
        if test.assertion is not None and (not isinstance(test.assertion, str) or not test.assertion.strip()):
            raise ValueError("sandbox test assertion must be absent or non-blank")


def test_result_to_dict(result: SandboxTestResult) -> dict[str, Any]:
    validate_test_result(result)
    counts = {status: sum(test.status == status for test in result.tests) for status in ("passed", "failed", "error", "skipped")}
    return {
        "schema_version": 1,
        "kind": "sandbox-test-result",
        "request_hash": result.request_hash,
        "adapter": result.adapter,
        "summary": {**counts, "total": len(result.tests)},
        "tests": [
            {
                "test_id": test.test_id,
                "status": test.status,
                "duration_ms": test.duration_ms,
                "stdout": test.stdout,
                "stderr": test.stderr,
                "covered_spec_ids": list(test.covered_spec_ids),
                "assertion": test.assertion,
            }
            for test in result.tests
        ],
    }


def canonical_test_result(result: SandboxTestResult) -> str:
    return json.dumps(test_result_to_dict(result), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_result_from_dict(payload: Mapping[str, Any]) -> SandboxTestResult:
    expected = {"schema_version", "kind", "request_hash", "adapter", "summary", "tests"}
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("malformed sandbox test-result envelope")
    if payload["schema_version"] != 1 or payload["kind"] != "sandbox-test-result":
        raise ValueError("unsupported sandbox test result")
    if not isinstance(payload["tests"], list):
        raise ValueError("sandbox test results must be a list")
    if not isinstance(payload["summary"], Mapping) or set(payload["summary"]) != {"passed", "failed", "error", "skipped", "total"}:
        raise ValueError("malformed sandbox test-result summary")
    item_fields = {"test_id", "status", "duration_ms", "stdout", "stderr", "covered_spec_ids", "assertion"}
    if any(not isinstance(item, Mapping) or set(item) != item_fields for item in payload["tests"]):
        raise ValueError("malformed sandbox test entry")
    if any(not isinstance(item["covered_spec_ids"], list) for item in payload["tests"]):
        raise ValueError("sandbox test coverage IDs must be a list")
    try:
        result = SandboxTestResult(
            payload["request_hash"], payload["adapter"],
            tuple(TestCaseResult(
                item["test_id"], item["status"], item["duration_ms"], item["stdout"], item["stderr"],
                tuple(item["covered_spec_ids"]), item["assertion"],
            ) for item in payload["tests"]),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"malformed sandbox test result: {exc}") from exc
    validate_test_result(result)
    if payload["summary"] != test_result_to_dict(result)["summary"]:
        raise ValueError("sandbox test-result summary is forged")
    return result

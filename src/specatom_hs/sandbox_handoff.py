"""Strict, inert metadata for handing approved output to a future sandbox.

This module describes an execution request but cannot publish files or start a
process.  A separate, explicitly invoked sandbox adapter must consume it.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping


@dataclass(frozen=True)
class SandboxLimits:
    cpu_seconds: int
    memory_mb: int
    timeout_seconds: int


@dataclass(frozen=True)
class SandboxHandoff:
    image_digest: str
    argv: tuple[str, ...]
    files: tuple[str, ...]
    limits: SandboxLimits


def validate_sandbox_handoff(handoff: SandboxHandoff) -> None:
    if not isinstance(handoff, SandboxHandoff):
        raise ValueError("sandbox handoff must be a SandboxHandoff")
    if not isinstance(handoff.image_digest, str) or not handoff.image_digest.startswith("sha256:"):
        raise ValueError("sandbox image must use a sha256 digest")
    digest = handoff.image_digest[7:]
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("sandbox image digest is malformed")
    if not handoff.argv or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in handoff.argv):
        raise ValueError("sandbox argv must contain non-empty, NUL-free strings")
    if not handoff.files or len(set(handoff.files)) != len(handoff.files):
        raise ValueError("sandbox handoff requires unique generated files")
    if not isinstance(handoff.limits, SandboxLimits):
        raise ValueError("sandbox limits are required")
    for name, value in (
        ("cpu_seconds", handoff.limits.cpu_seconds),
        ("memory_mb", handoff.limits.memory_mb),
        ("timeout_seconds", handoff.limits.timeout_seconds),
    ):
        if type(value) is not int or value <= 0:
            raise ValueError(f"sandbox {name} must be a positive integer")


def sandbox_handoff_to_dict(handoff: SandboxHandoff) -> dict[str, Any]:
    validate_sandbox_handoff(handoff)
    return {
        "schema_version": 1,
        "kind": "sandbox-handoff",
        "executed": False,
        "opt_in_required": True,
        "isolation": {"host_filesystem": False, "network": False, "secrets": False},
        "image_digest": handoff.image_digest,
        "argv": list(handoff.argv),
        "files": list(handoff.files),
        "limits": {
            "cpu_seconds": handoff.limits.cpu_seconds,
            "memory_mb": handoff.limits.memory_mb,
            "timeout_seconds": handoff.limits.timeout_seconds,
        },
    }


def canonical_sandbox_handoff(handoff: SandboxHandoff) -> str:
    return json.dumps(sandbox_handoff_to_dict(handoff), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sandbox_handoff_from_dict(payload: Mapping[str, Any]) -> SandboxHandoff:
    expected = {"schema_version", "kind", "executed", "opt_in_required", "isolation", "image_digest", "argv", "files", "limits"}
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ValueError("malformed sandbox handoff envelope")
    if payload["schema_version"] != 1 or payload["kind"] != "sandbox-handoff":
        raise ValueError("unsupported sandbox handoff")
    if payload["executed"] is not False or payload["opt_in_required"] is not True:
        raise ValueError("sandbox handoff must remain unexecuted and opt-in")
    if payload["isolation"] != {"host_filesystem": False, "network": False, "secrets": False}:
        raise ValueError("sandbox handoff weakens required isolation")
    limits = payload["limits"]
    if not isinstance(limits, Mapping) or set(limits) != {"cpu_seconds", "memory_mb", "timeout_seconds"}:
        raise ValueError("malformed sandbox limits")
    if not isinstance(payload["argv"], list) or not isinstance(payload["files"], list):
        raise ValueError("sandbox argv and files must be lists")
    handoff = SandboxHandoff(
        payload["image_digest"], tuple(payload["argv"]), tuple(payload["files"]),
        SandboxLimits(limits["cpu_seconds"], limits["memory_mb"], limits["timeout_seconds"]),
    )
    validate_sandbox_handoff(handoff)
    return handoff

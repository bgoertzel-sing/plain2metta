"""Single-call, provider-independent Phase 6 sandbox adapter boundary.

The core package supplies no host executor.  An explicitly injected adapter is
the only component permitted to execute the canonical inert sandbox request.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping, Protocol, Any

from .projects import ArtifactKind, add_test_result
from .sandbox_handoff import sandbox_handoff_from_dict
from .sandbox_protocol import (
    SandboxTestResult, sandbox_request_hash, sandbox_request_to_dict,
    test_result_from_dict,
)


@dataclass(frozen=True)
class SandboxAdapterConfig:
    adapter: str


class SandboxExecutionAdapter(Protocol):
    def execute(
        self, request: Mapping[str, Any], config: SandboxAdapterConfig,
    ) -> Mapping[str, Any]: ...


def validate_adapter_config(config: object) -> None:
    if not isinstance(config, SandboxAdapterConfig):
        raise ValueError("config must be SandboxAdapterConfig")
    if not isinstance(config.adapter, str) or not config.adapter.strip():
        raise ValueError("adapter must be non-blank text")


def _current_handoff(project):
    artifact = project.current(ArtifactKind.SANDBOX_HANDOFF)
    if artifact is None:
        raise ValueError("project has no current sandbox handoff")
    try:
        payload = json.loads(artifact.content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("current sandbox handoff is malformed") from exc
    return artifact, sandbox_handoff_from_dict(payload)


class SandboxCoordinator:
    """Make exactly one injected adapter call and atomically admit its result."""

    def __init__(self, repository, adapter: SandboxExecutionAdapter, config: SandboxAdapterConfig):
        validate_adapter_config(config)
        if not callable(getattr(adapter, "execute", None)):
            raise ValueError("adapter must provide execute(request, config)")
        self._repository = repository
        self._adapter = adapter
        self._config = config

    def execute_once(self, project_id: str):
        before = self._repository.get(project_id)
        handoff_artifact, handoff = _current_handoff(before)
        request = sandbox_request_to_dict(handoff)
        returned = self._adapter.execute(request, self._config)
        result = test_result_from_dict(returned)
        if result.adapter != self._config.adapter:
            raise ValueError("result attribution does not match the configured adapter")
        if result.request_hash != sandbox_request_hash(handoff):
            raise ValueError("result does not bind the exact sandbox request")

        # External I/O may race with review or source changes. Re-read and admit
        # only if the exact handoff artifact and canonical request remain current.
        current = self._repository.get(project_id)
        current_artifact, current_handoff = _current_handoff(current)
        if current_artifact.ref != handoff_artifact.ref or current_handoff != handoff:
            raise ValueError("sandbox handoff changed during execution")
        updated = add_test_result(current, result)
        self._repository.save(updated)
        return updated

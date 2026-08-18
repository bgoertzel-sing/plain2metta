"""Single-call, vendor-neutral Phase 4 logical-IR adapter boundary."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol

from .logical_ir_prompt import (
    LogicalIRPromptEnvelope, LogicalIRRequest, ProviderCompletion,
    build_logical_ir_prompt, parse_logical_ir_completion,
)
from .projects import ArtifactKind, add_logical_ir_response


@dataclass(frozen=True)
class LogicalIRBackendConfig:
    backend: str
    model: str
    temperature: float = 0.0
    max_tokens: int = 8192


class LogicalIRBackend(Protocol):
    def generate_logical_ir(
        self, prompt: LogicalIRPromptEnvelope, config: LogicalIRBackendConfig,
    ) -> ProviderCompletion: ...


def validate_backend_config(config: object) -> None:
    if not isinstance(config, LogicalIRBackendConfig):
        raise ValueError("config must be LogicalIRBackendConfig")
    for field in ("backend", "model"):
        value = getattr(config, field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be non-blank text")
    if (
        not isinstance(config.temperature, (int, float))
        or isinstance(config.temperature, bool)
        or not math.isfinite(config.temperature)
        or not 0.0 <= config.temperature <= 2.0
    ):
        raise ValueError("temperature must be a finite number from 0 through 2")
    if (
        not isinstance(config.max_tokens, int)
        or isinstance(config.max_tokens, bool)
        or not 1 <= config.max_tokens <= 1_000_000
    ):
        raise ValueError("max_tokens must be an integer from 1 through 1000000")


class LogicalIRCoordinator:
    """Make exactly one call and atomically persist its exact admitted return."""

    def __init__(self, repository, backend: LogicalIRBackend, config: LogicalIRBackendConfig):
        validate_backend_config(config)
        if not callable(getattr(backend, "generate_logical_ir", None)):
            raise ValueError("backend must provide generate_logical_ir(prompt, config)")
        self._repository = repository
        self._backend = backend
        self._config = config

    def generate_once(self, project_id: str, guidance: str = ""):
        project = self._repository.get(project_id)
        reviewed_spec = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
        reviewed_tests = project.current(ArtifactKind.REVIEWED_TEST_SPEC)
        if reviewed_spec is None or reviewed_tests is None:
            raise ValueError("logical IR generation requires exact current reviewed snapshots")
        request = LogicalIRRequest(
            reviewed_spec.ref, reviewed_spec.content,
            reviewed_tests.ref, reviewed_tests.content, guidance,
        )
        prompt = build_logical_ir_prompt(request)
        completion = self._backend.generate_logical_ir(prompt, self._config)
        response = parse_logical_ir_completion(request, completion)
        if (
            response.provenance.backend != self._config.backend
            or response.provenance.model != self._config.model
        ):
            raise ValueError("response provenance does not match the configured backend and model")

        # Re-read after the external call.  Admission is allowed only if the exact
        # reviewed versions used in the prompt are still current.
        current = self._repository.get(project_id)
        current_spec = current.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
        current_tests = current.current(ArtifactKind.REVIEWED_TEST_SPEC)
        if (
            current_spec is None or current_tests is None
            or current_spec.ref != request.reviewed_spec
            or current_tests.ref != request.reviewed_tests
        ):
            raise ValueError("reviewed snapshots changed during logical IR generation")
        updated = add_logical_ir_response(current, request, response)
        self._repository.save(updated)
        return updated

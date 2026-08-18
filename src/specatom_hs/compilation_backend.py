"""Single-call, vendor-neutral Phase 5 compilation adapter boundary."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol

from .compilation_prompt import (
    CompilationPromptEnvelope, ProviderCompletion, build_compilation_prompt,
    build_compilation_request, parse_compilation_completion,
)
from .projects import add_compilation_response


@dataclass(frozen=True)
class CompilationBackendConfig:
    backend: str
    model: str
    temperature: float = 0.0
    max_tokens: int = 16384


class CompilationBackend(Protocol):
    def compile(
        self, prompt: CompilationPromptEnvelope, config: CompilationBackendConfig,
    ) -> ProviderCompletion: ...


def validate_backend_config(config: object) -> None:
    if not isinstance(config, CompilationBackendConfig):
        raise ValueError("config must be CompilationBackendConfig")
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


class CompilationCoordinator:
    """Make exactly one call and atomically persist its exact admitted return."""

    def __init__(self, repository, backend: CompilationBackend, config: CompilationBackendConfig):
        validate_backend_config(config)
        if not callable(getattr(backend, "compile", None)):
            raise ValueError("backend must provide compile(prompt, config)")
        self._repository = repository
        self._backend = backend
        self._config = config

    def compile_once(self, project_id: str, guidance: str = ""):
        request = build_compilation_request(self._repository.get(project_id), guidance)
        prompt = build_compilation_prompt(request)
        completion = self._backend.compile(prompt, self._config)
        response = parse_compilation_completion(request, completion)
        if (
            response.provenance.backend != self._config.backend
            or response.provenance.model != self._config.model
        ):
            raise ValueError("response provenance does not match the configured backend and model")

        # Re-read after external I/O and admit only the exact still-current inputs.
        current = self._repository.get(project_id)
        expected = build_compilation_request(current, guidance)
        if expected != request:
            raise ValueError("approved compilation inputs changed during compilation")
        updated = add_compilation_response(current, request, response)
        self._repository.save(updated)
        return updated

"""Explicit, vendor-neutral invocation boundary for Phase 2 elaboration.

Only an injected adapter can perform I/O. The coordinator makes one call and
routes the returned message through the existing exact-request admission gate;
it has no retry, fallback, provider selection, or credential handling policy.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol

from .elaboration_admission import (
    ElaborationAdmissionService, ElaborationRequestService, Validator,
    validate_elaboration_outputs,
)
from .elaboration_protocol import ElaborationRequest, ElaborationResponse, validate_elaboration_response


@dataclass(frozen=True)
class ElaborationBackendConfig:
    backend: str
    model: str
    temperature: float = 0.0
    max_tokens: int = 8192


class ElaborationBackend(Protocol):
    def elaborate(
        self, request: ElaborationRequest, config: ElaborationBackendConfig,
    ) -> ElaborationResponse: ...


def validate_backend_config(config: object) -> None:
    if not isinstance(config, ElaborationBackendConfig):
        raise ValueError("config must be ElaborationBackendConfig")
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


class ElaborationCoordinator:
    """Make one configured adapter call and atomically admit its exact response."""

    def __init__(
        self, repository, backend: ElaborationBackend, config: ElaborationBackendConfig,
        validator: Validator = validate_elaboration_outputs,
    ):
        validate_backend_config(config)
        if not callable(getattr(backend, "elaborate", None)):
            raise ValueError("backend must provide elaborate(request, config)")
        self._requests = ElaborationRequestService(repository)
        self._admission = ElaborationAdmissionService(repository, validator)
        self._backend = backend
        self._config = config

    def elaborate_once(
        self, project_id: str, guidance: str = "", section: str | None = None,
    ):
        request = self._requests.build_request(project_id, guidance, section)
        response = self._backend.elaborate(request, self._config)
        validate_elaboration_response(response, request)
        if (
            response.provenance.backend != self._config.backend
            or response.provenance.model != self._config.model
        ):
            raise ValueError("response provenance does not match the configured backend and model")
        return self._admission.admit_and_persist(project_id, request, response)

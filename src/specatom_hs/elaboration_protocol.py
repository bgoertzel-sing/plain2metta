"""Pure Phase 2 elaboration messages and validation admission.

The types in this module describe an adapter boundary.  They never invoke a
provider, retry a request, persist state, or execute returned content.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping

from .projects import ArtifactRef, content_sha256


SCHEMA = "plain2metta-elaboration/v1"
_MARKER = re.compile(r"\[(?:id|covers):[^\]\r\n]+\]|:[A-Za-z][A-Za-z0-9_-]*:")


@dataclass(frozen=True)
class ElaborationRequest:
    source: ArtifactRef
    source_text: str
    guidance: str = ""
    section: str | None = None


@dataclass(frozen=True)
class ProviderProvenance:
    backend: str
    model: str
    interaction_id: str
    input_tokens: int
    output_tokens: int
    timestamp: str


@dataclass(frozen=True)
class ElaborationResponse:
    request_hash: str
    elaborated_spec: str
    test_spec: str
    provenance: ProviderProvenance


@dataclass(frozen=True)
class ValidationSummary:
    pass_count: int
    fail_count: int
    unknown_count: int
    blocking_questions: int


@dataclass(frozen=True)
class ElaborationAdmission:
    request_hash: str
    response_hash: str
    elaborated_validation: ValidationSummary
    test_validation: ValidationSummary
    required_markers: tuple[str, ...]
    preserved_markers: tuple[str, ...]
    admitted: bool


def _text(value: object, field: str, *, blank: bool = False) -> str:
    if not isinstance(value, str) or (not blank and not value.strip()):
        raise ValueError(f"{field} must be {'text' if blank else 'non-blank text'}")
    return value


def _hash(value: object, field: str) -> str:
    text = _text(value, field)
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", text):
        raise ValueError(f"{field} must be a canonical SHA-256 hash")
    return text


def _exact(data: object, fields: set[str], field: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping) or set(data) != fields:
        raise ValueError(f"{field} must contain exactly {sorted(fields)!r}")
    return data


def _canonical(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(data: Mapping[str, Any]) -> str:
    return "sha256:" + sha256(_canonical(data).encode("utf-8")).hexdigest()


def elaboration_request_to_dict(request: ElaborationRequest) -> dict[str, Any]:
    validate_elaboration_request(request)
    return {
        "schema": SCHEMA,
        "source": {"artifact_id": request.source.artifact_id, "content_hash": request.source.content_hash},
        "source_text": request.source_text,
        "guidance": request.guidance,
        "section": request.section,
    }


def elaboration_request_from_dict(data: object) -> ElaborationRequest:
    value = _exact(data, {"schema", "source", "source_text", "guidance", "section"}, "request")
    if value["schema"] != SCHEMA:
        raise ValueError("unsupported elaboration schema")
    source = _exact(value["source"], {"artifact_id", "content_hash"}, "source")
    request = ElaborationRequest(
        ArtifactRef(_text(source["artifact_id"], "artifact_id"), _hash(source["content_hash"], "content_hash")),
        value["source_text"], value["guidance"], value["section"],
    )
    validate_elaboration_request(request)
    return request


def validate_elaboration_request(request: object) -> None:
    if not isinstance(request, ElaborationRequest):
        raise ValueError("request must be an ElaborationRequest")
    _text(request.source.artifact_id, "artifact_id")
    _hash(request.source.content_hash, "content_hash")
    _text(request.source_text, "source_text", blank=True)
    if content_sha256(request.source_text) != request.source.content_hash:
        raise ValueError("source text does not match the exact source artifact hash")
    _text(request.guidance, "guidance", blank=True)
    if request.section is not None:
        _text(request.section, "section")


def elaboration_request_hash(request: ElaborationRequest) -> str:
    return _digest(elaboration_request_to_dict(request))


def _provenance_to_dict(value: ProviderProvenance) -> dict[str, Any]:
    _validate_provenance(value)
    return {
        "backend": value.backend, "model": value.model, "interaction_id": value.interaction_id,
        "input_tokens": value.input_tokens, "output_tokens": value.output_tokens, "timestamp": value.timestamp,
    }


def _validate_provenance(value: object) -> None:
    if not isinstance(value, ProviderProvenance):
        raise ValueError("provenance must be ProviderProvenance")
    for field in ("backend", "model", "interaction_id", "timestamp"):
        _text(getattr(value, field), field)
    for field in ("input_tokens", "output_tokens"):
        count = getattr(value, field)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError(f"{field} must be a non-negative integer")


def elaboration_response_to_dict(response: ElaborationResponse) -> dict[str, Any]:
    validate_elaboration_response(response)
    return {
        "schema": SCHEMA, "request_hash": response.request_hash,
        "elaborated_spec": response.elaborated_spec, "test_spec": response.test_spec,
        "provenance": _provenance_to_dict(response.provenance),
    }


def elaboration_response_from_dict(data: object) -> ElaborationResponse:
    value = _exact(data, {"schema", "request_hash", "elaborated_spec", "test_spec", "provenance"}, "response")
    if value["schema"] != SCHEMA:
        raise ValueError("unsupported elaboration schema")
    raw = _exact(value["provenance"], {"backend", "model", "interaction_id", "input_tokens", "output_tokens", "timestamp"}, "provenance")
    response = ElaborationResponse(
        _hash(value["request_hash"], "request_hash"), value["elaborated_spec"], value["test_spec"],
        ProviderProvenance(raw["backend"], raw["model"], raw["interaction_id"], raw["input_tokens"], raw["output_tokens"], raw["timestamp"]),
    )
    validate_elaboration_response(response)
    return response


def validate_elaboration_response(response: object, request: ElaborationRequest | None = None) -> None:
    if not isinstance(response, ElaborationResponse):
        raise ValueError("response must be an ElaborationResponse")
    _hash(response.request_hash, "request_hash")
    _text(response.elaborated_spec, "elaborated_spec")
    _text(response.test_spec, "test_spec")
    _validate_provenance(response.provenance)
    if request is not None and response.request_hash != elaboration_request_hash(request):
        raise ValueError("response does not bind to the exact elaboration request")


def elaboration_response_hash(response: ElaborationResponse) -> str:
    return _digest(elaboration_response_to_dict(response))


def _validate_summary(summary: object, field: str) -> None:
    if not isinstance(summary, ValidationSummary):
        raise ValueError(f"{field} must be ValidationSummary")
    for name in ("pass_count", "fail_count", "unknown_count", "blocking_questions"):
        value = getattr(summary, name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{field}.{name} must be a non-negative integer")


def admit_elaboration(
    request: ElaborationRequest,
    response: ElaborationResponse,
    elaborated_validation: ValidationSummary,
    test_validation: ValidationSummary,
) -> ElaborationAdmission:
    validate_elaboration_request(request)
    validate_elaboration_response(response, request)
    _validate_summary(elaborated_validation, "elaborated_validation")
    _validate_summary(test_validation, "test_validation")
    required = tuple(dict.fromkeys(_MARKER.findall(request.source_text)))
    preserved = tuple(marker for marker in required if marker in response.elaborated_spec)
    admitted = (
        preserved == required
        and elaborated_validation.fail_count == 0
        and elaborated_validation.blocking_questions == 0
        and test_validation.fail_count == 0
        and test_validation.blocking_questions == 0
    )
    return ElaborationAdmission(
        elaboration_request_hash(request), elaboration_response_hash(response),
        elaborated_validation, test_validation, required, preserved, admitted,
    )


def elaboration_admission_to_dict(admission: ElaborationAdmission) -> dict[str, Any]:
    validate_elaboration_admission(admission)
    def summary(value: ValidationSummary) -> dict[str, int]:
        return {
            "pass_count": value.pass_count, "fail_count": value.fail_count,
            "unknown_count": value.unknown_count, "blocking_questions": value.blocking_questions,
        }
    return {
        "schema": SCHEMA, "request_hash": admission.request_hash,
        "response_hash": admission.response_hash,
        "elaborated_validation": summary(admission.elaborated_validation),
        "test_validation": summary(admission.test_validation), "required_markers": list(admission.required_markers),
        "preserved_markers": list(admission.preserved_markers), "admitted": admission.admitted,
    }


def elaboration_admission_from_dict(data: object) -> ElaborationAdmission:
    value = _exact(data, {
        "schema", "request_hash", "response_hash", "elaborated_validation",
        "test_validation", "required_markers", "preserved_markers", "admitted",
    }, "admission")
    if value["schema"] != SCHEMA:
        raise ValueError("unsupported elaboration schema")
    def summary(raw: object, field: str) -> ValidationSummary:
        item = _exact(raw, {"pass_count", "fail_count", "unknown_count", "blocking_questions"}, field)
        return ValidationSummary(item["pass_count"], item["fail_count"], item["unknown_count"], item["blocking_questions"])
    required = value["required_markers"]
    preserved = value["preserved_markers"]
    if not isinstance(required, list) or not isinstance(preserved, list):
        raise ValueError("marker collections must be arrays")
    admission = ElaborationAdmission(
        _hash(value["request_hash"], "request_hash"), _hash(value["response_hash"], "response_hash"),
        summary(value["elaborated_validation"], "elaborated_validation"),
        summary(value["test_validation"], "test_validation"), tuple(required), tuple(preserved), value["admitted"],
    )
    validate_elaboration_admission(admission)
    return admission


def validate_elaboration_admission(admission: object) -> None:
    if not isinstance(admission, ElaborationAdmission):
        raise ValueError("admission must be ElaborationAdmission")
    _hash(admission.request_hash, "request_hash")
    _hash(admission.response_hash, "response_hash")
    _validate_summary(admission.elaborated_validation, "elaborated_validation")
    _validate_summary(admission.test_validation, "test_validation")
    for field in ("required_markers", "preserved_markers"):
        markers = getattr(admission, field)
        if not isinstance(markers, tuple) or any(not isinstance(x, str) or not x for x in markers):
            raise ValueError(f"{field} must be a non-blank text tuple")
        if len(set(markers)) != len(markers):
            raise ValueError(f"{field} must not contain duplicates")
    if any(marker not in admission.required_markers for marker in admission.preserved_markers):
        raise ValueError("preserved markers must be required markers")
    expected = (
        admission.preserved_markers == admission.required_markers
        and
        admission.elaborated_validation.fail_count == 0
        and admission.elaborated_validation.blocking_questions == 0
        and admission.test_validation.fail_count == 0
        and admission.test_validation.blocking_questions == 0
    )
    if not isinstance(admission.admitted, bool) or admission.admitted != expected:
        raise ValueError("admitted flag does not match marker and validation evidence")

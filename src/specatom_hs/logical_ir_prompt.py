"""Canonical provider-independent Phase 4 logical-IR prompt boundary."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping

from .elaboration_protocol import ProviderProvenance
from .logical_ir import LogicalIRDocument, logical_ir_from_dict
from .projects import ArtifactRef, content_sha256


REQUEST_SCHEMA = "plain2metta-logical-ir-request/v1"
PROMPT_SCHEMA = "plain2metta-logical-ir-prompt/v1"
RESPONSE_SCHEMA = "plain2metta-logical-ir-response/v1"
SYSTEM_PROMPT = """Translate the exact reviewed specification and test specification into Plain2MeTTa logical IR.
Return exactly one JSON object matching the supplied response schema, with no Markdown fence or commentary.
The logical_ir value must match the supplied non-executable logical-IR schema exactly.
Preserve source-clause and planned-test identifiers as explicit provenance; do not infer new requirements.
Represent implementation-dependent behavior as operational holes, never executable code.
Do not claim validation, execution, approval, or evidence that was not supplied."""


@dataclass(frozen=True)
class LogicalIRRequest:
    reviewed_spec: ArtifactRef
    reviewed_spec_text: str
    reviewed_tests: ArtifactRef
    reviewed_tests_text: str
    guidance: str = ""


@dataclass(frozen=True)
class PromptMessage:
    role: str
    content: str


@dataclass(frozen=True)
class LogicalIRPromptEnvelope:
    request_hash: str
    messages: tuple[PromptMessage, ...]
    response_schema: Mapping[str, Any]


@dataclass(frozen=True)
class ProviderCompletion:
    text: str
    provenance: ProviderProvenance


@dataclass(frozen=True)
class LogicalIRResponse:
    request_hash: str
    logical_ir: LogicalIRDocument
    provenance: ProviderProvenance


def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError(f"{label} must be a canonical SHA-256 hash")
    return value


def _text(value: object, label: str, *, blank: bool = False) -> str:
    if not isinstance(value, str) or (not blank and not value.strip()):
        raise ValueError(f"{label} must be text")
    return value


def _ref(value: ArtifactRef, text: str, label: str) -> dict[str, str]:
    if not isinstance(value, ArtifactRef) or not value.artifact_id.strip():
        raise ValueError(f"{label} must be an artifact reference")
    _hash(value.content_hash, f"{label} hash")
    if content_sha256(text) != value.content_hash:
        raise ValueError(f"{label} text does not match its exact artifact hash")
    return {"artifact_id": value.artifact_id, "content_hash": value.content_hash}


def logical_ir_request_to_dict(request: LogicalIRRequest) -> dict[str, Any]:
    if not isinstance(request, LogicalIRRequest):
        raise ValueError("request must be a LogicalIRRequest")
    _text(request.reviewed_spec_text, "reviewed_spec_text", blank=True)
    _text(request.reviewed_tests_text, "reviewed_tests_text", blank=True)
    _text(request.guidance, "guidance", blank=True)
    return {
        "schema": REQUEST_SCHEMA,
        "reviewed_spec": _ref(request.reviewed_spec, request.reviewed_spec_text, "reviewed_spec"),
        "reviewed_spec_text": request.reviewed_spec_text,
        "reviewed_tests": _ref(request.reviewed_tests, request.reviewed_tests_text, "reviewed_tests"),
        "reviewed_tests_text": request.reviewed_tests_text,
        "guidance": request.guidance,
    }


def logical_ir_request_hash(request: LogicalIRRequest) -> str:
    value = json.dumps(logical_ir_request_to_dict(request), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(value.encode("utf-8")).hexdigest()


def _response_schema() -> dict[str, Any]:
    return {
        "type": "object", "additionalProperties": False,
        "required": ["schema", "logical_ir"],
        "properties": {
            "schema": {"const": RESPONSE_SCHEMA},
            "logical_ir": {"type": "object", "additionalProperties": False},
        },
    }


def build_logical_ir_prompt(request: LogicalIRRequest) -> LogicalIRPromptEnvelope:
    payload = logical_ir_request_to_dict(request)
    user = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return LogicalIRPromptEnvelope(
        logical_ir_request_hash(request),
        (PromptMessage("system", SYSTEM_PROMPT), PromptMessage("user", user)),
        _response_schema(),
    )


def logical_ir_prompt_to_dict(prompt: LogicalIRPromptEnvelope) -> dict[str, Any]:
    if not isinstance(prompt, LogicalIRPromptEnvelope):
        raise ValueError("prompt must be a LogicalIRPromptEnvelope")
    if len(prompt.messages) != 2 or tuple(x.role for x in prompt.messages) != ("system", "user"):
        raise ValueError("prompt must contain exactly one system and one user message")
    if prompt.messages[0].content != SYSTEM_PROMPT or prompt.response_schema != _response_schema():
        raise ValueError("prompt is not canonical")
    expected_hash = "sha256:" + sha256(prompt.messages[1].content.encode("utf-8")).hexdigest()
    try:
        payload = json.loads(prompt.messages[1].content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("prompt request is not canonical JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema", "reviewed_spec", "reviewed_spec_text", "reviewed_tests", "reviewed_tests_text", "guidance"}:
        raise ValueError("prompt request schema is invalid")
    if payload.get("schema") != REQUEST_SCHEMA or prompt.request_hash != expected_hash:
        raise ValueError("prompt does not bind to its exact request")
    for key, text_key in (("reviewed_spec", "reviewed_spec_text"), ("reviewed_tests", "reviewed_tests_text")):
        ref = payload[key]
        if not isinstance(ref, dict) or set(ref) != {"artifact_id", "content_hash"}:
            raise ValueError("prompt artifact reference is invalid")
        _ref(ArtifactRef(ref["artifact_id"], ref["content_hash"]), payload[text_key], key)
    if not isinstance(payload["guidance"], str):
        raise ValueError("prompt guidance must be text")
    return {
        "schema": PROMPT_SCHEMA, "request_hash": prompt.request_hash,
        "messages": [{"role": x.role, "content": x.content} for x in prompt.messages],
        "response_schema": dict(prompt.response_schema),
    }


def parse_logical_ir_completion(request: LogicalIRRequest, completion: ProviderCompletion) -> LogicalIRResponse:
    request_hash = logical_ir_request_hash(request)
    if not isinstance(completion, ProviderCompletion) or not isinstance(completion.text, str) or not isinstance(completion.provenance, ProviderProvenance):
        raise ValueError("completion must contain text and provider provenance")
    for field in ("backend", "model", "interaction_id", "timestamp"):
        if not isinstance(getattr(completion.provenance, field), str) or not getattr(completion.provenance, field).strip():
            raise ValueError(f"provenance {field} must be non-blank text")
    for field in ("input_tokens", "output_tokens"):
        count = getattr(completion.provenance, field)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError(f"provenance {field} must be a non-negative integer")
    try:
        payload = json.loads(completion.text, object_pairs_hook=_reject_duplicate_keys)
    except (TypeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("provider completion must be one unambiguous JSON object") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema", "logical_ir"} or payload.get("schema") != RESPONSE_SCHEMA:
        raise ValueError("provider completion does not match the response schema")
    if not isinstance(payload["logical_ir"], Mapping):
        raise ValueError("logical_ir must be an object")
    return LogicalIRResponse(request_hash, logical_ir_from_dict(payload["logical_ir"]), completion.provenance)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result

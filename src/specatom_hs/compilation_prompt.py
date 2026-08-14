"""Canonical provider-independent Phase 5 compilation prompt boundary.

The boundary only validates messages and generated text.  It never publishes,
imports, evaluates, or executes compiler output.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping

from .compiler_output import CompilerOutputBundle, compiler_output_from_dict
from .elaboration_protocol import ProviderProvenance
from .projects import ArtifactKind, ArtifactRef, Project, admit_compilation, content_sha256


REQUEST_SCHEMA = "plain2metta-compilation-request/v1"
PROMPT_SCHEMA = "plain2metta-compilation-prompt/v1"
RESPONSE_SCHEMA = "plain2metta-compilation-response/v1"
SYSTEM_PROMPT = """Compile the exact approved reviewed specification, reviewed tests, and logical IR into Plain2MeTTa artifacts.
Return exactly one JSON object matching the supplied response schema, with no Markdown fence or commentary.
Produce literate MeTTa as the primary executable representation, preserving requirement IDs in comments.
Use grounded Python only for operations better expressed in Python; Python must be called through MeTTa and must not bypass it.
Produce executable unit tests for every requirement and system tests declared by the reviewed tests.
Every generated file must cite the exact requirement IDs it implements and the test IDs it contains.
Implement exactly the supplied approved inputs: do not add features, drop requirements, claim execution, or invent evidence."""


@dataclass(frozen=True)
class CompilationRequest:
    reviewed_spec: ArtifactRef
    reviewed_spec_text: str
    reviewed_tests: ArtifactRef
    reviewed_tests_text: str
    logical_ir: ArtifactRef
    logical_ir_text: str
    guidance: str = ""


@dataclass(frozen=True)
class PromptMessage:
    role: str
    content: str


@dataclass(frozen=True)
class CompilationPromptEnvelope:
    request_hash: str
    messages: tuple[PromptMessage, ...]
    response_schema: Mapping[str, Any]


@dataclass(frozen=True)
class ProviderCompletion:
    text: str
    provenance: ProviderProvenance


@dataclass(frozen=True)
class CompilationResponse:
    request_hash: str
    compiler_output: CompilerOutputBundle
    provenance: ProviderProvenance


def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError(f"{label} must be a canonical SHA-256 hash")
    return value


def _ref(value: ArtifactRef, text: object, label: str) -> dict[str, str]:
    if not isinstance(value, ArtifactRef) or not value.artifact_id.strip():
        raise ValueError(f"{label} must be an artifact reference")
    if not isinstance(text, str):
        raise ValueError(f"{label} text must be text")
    _hash(value.content_hash, f"{label} hash")
    if content_sha256(text) != value.content_hash:
        raise ValueError(f"{label} text does not match its exact artifact hash")
    return {"artifact_id": value.artifact_id, "content_hash": value.content_hash}


def compilation_request_to_dict(request: CompilationRequest) -> dict[str, Any]:
    if not isinstance(request, CompilationRequest):
        raise ValueError("request must be a CompilationRequest")
    if not isinstance(request.guidance, str):
        raise ValueError("guidance must be text")
    return {
        "schema": REQUEST_SCHEMA,
        "reviewed_spec": _ref(request.reviewed_spec, request.reviewed_spec_text, "reviewed_spec"),
        "reviewed_spec_text": request.reviewed_spec_text,
        "reviewed_tests": _ref(request.reviewed_tests, request.reviewed_tests_text, "reviewed_tests"),
        "reviewed_tests_text": request.reviewed_tests_text,
        "logical_ir": _ref(request.logical_ir, request.logical_ir_text, "logical_ir"),
        "logical_ir_text": request.logical_ir_text,
        "guidance": request.guidance,
    }


def compilation_request_hash(request: CompilationRequest) -> str:
    encoded = json.dumps(compilation_request_to_dict(request), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(encoded.encode("utf-8")).hexdigest()


def build_compilation_request(project: Project, guidance: str = "") -> CompilationRequest:
    """Load only the exact current inputs after the Phase 4 admission gate."""
    if not isinstance(project, Project):
        raise ValueError("project must be a Project")
    if not isinstance(guidance, str):
        raise ValueError("guidance must be text")
    logical = admit_compilation(project)
    reviewed_spec = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
    reviewed_tests = project.current(ArtifactKind.REVIEWED_TEST_SPEC)
    if reviewed_spec is None or reviewed_tests is None:
        raise ValueError("compilation requires exact current reviewed inputs")
    if logical.upstream != (reviewed_spec.ref, reviewed_tests.ref):
        raise ValueError("admitted logical IR is not bound to exact current reviewed inputs")
    return CompilationRequest(
        reviewed_spec.ref, reviewed_spec.content,
        reviewed_tests.ref, reviewed_tests.content,
        logical.ref, logical.content, guidance,
    )


def _response_schema() -> dict[str, Any]:
    return {
        "type": "object", "additionalProperties": False,
        "required": ["schema", "compiler_output"],
        "properties": {
            "schema": {"const": RESPONSE_SCHEMA},
            "compiler_output": {"type": "object", "additionalProperties": False},
        },
    }


def build_compilation_prompt(request: CompilationRequest) -> CompilationPromptEnvelope:
    user = json.dumps(compilation_request_to_dict(request), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return CompilationPromptEnvelope(
        compilation_request_hash(request),
        (PromptMessage("system", SYSTEM_PROMPT), PromptMessage("user", user)),
        _response_schema(),
    )


def compilation_prompt_to_dict(prompt: CompilationPromptEnvelope) -> dict[str, Any]:
    if not isinstance(prompt, CompilationPromptEnvelope):
        raise ValueError("prompt must be a CompilationPromptEnvelope")
    if len(prompt.messages) != 2 or tuple(message.role for message in prompt.messages) != ("system", "user"):
        raise ValueError("prompt must contain exactly one system and one user message")
    if prompt.messages[0].content != SYSTEM_PROMPT or prompt.response_schema != _response_schema():
        raise ValueError("prompt is not canonical")
    try:
        payload = json.loads(prompt.messages[1].content, object_pairs_hook=_reject_duplicate_keys)
    except (TypeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("prompt request is not canonical JSON") from exc
    required = {"schema", "reviewed_spec", "reviewed_spec_text", "reviewed_tests", "reviewed_tests_text", "logical_ir", "logical_ir_text", "guidance"}
    if not isinstance(payload, dict) or set(payload) != required or payload.get("schema") != REQUEST_SCHEMA:
        raise ValueError("prompt request schema is invalid")
    expected_hash = "sha256:" + sha256(prompt.messages[1].content.encode("utf-8")).hexdigest()
    if prompt.request_hash != expected_hash:
        raise ValueError("prompt does not bind to its exact request")
    for key, text_key in (("reviewed_spec", "reviewed_spec_text"), ("reviewed_tests", "reviewed_tests_text"), ("logical_ir", "logical_ir_text")):
        ref = payload[key]
        if not isinstance(ref, dict) or set(ref) != {"artifact_id", "content_hash"}:
            raise ValueError("prompt artifact reference is invalid")
        _ref(ArtifactRef(ref["artifact_id"], ref["content_hash"]), payload[text_key], key)
    if not isinstance(payload["guidance"], str):
        raise ValueError("prompt guidance must be text")
    return {
        "schema": PROMPT_SCHEMA, "request_hash": prompt.request_hash,
        "messages": [{"role": message.role, "content": message.content} for message in prompt.messages],
        "response_schema": dict(prompt.response_schema),
    }


def parse_compilation_completion(request: CompilationRequest, completion: ProviderCompletion) -> CompilationResponse:
    request_hash = compilation_request_hash(request)
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
    if not isinstance(payload, dict) or set(payload) != {"schema", "compiler_output"} or payload.get("schema") != RESPONSE_SCHEMA:
        raise ValueError("provider completion does not match the response schema")
    if not isinstance(payload["compiler_output"], Mapping):
        raise ValueError("compiler_output must be an object")
    bundle = compiler_output_from_dict(payload["compiler_output"])
    expected_compiler = f"{completion.provenance.backend}:{completion.provenance.model}"
    if bundle.compiler != expected_compiler or bundle.guidance != (request.guidance or None):
        raise ValueError("compiler output is not attributed to the exact request and provider")
    return CompilationResponse(request_hash, bundle, completion.provenance)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result

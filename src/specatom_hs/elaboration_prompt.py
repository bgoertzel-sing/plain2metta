"""Canonical, provider-independent Phase 2 prompt and completion format."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from .elaboration_protocol import (
    ElaborationRequest, ElaborationResponse, ProviderProvenance,
    elaboration_request_from_dict, elaboration_request_hash, elaboration_request_to_dict,
    validate_elaboration_request, validate_elaboration_response,
)


PROMPT_SCHEMA = "plain2metta-elaboration-prompt/v1"
RESPONSE_SCHEMA = "plain2metta-elaboration-response/v1"

SYSTEM_PROMPT = """You elaborate a Plain2MeTTa source specification into two reviewable English documents.
Return exactly one JSON object matching the supplied response schema, with no Markdown fence or commentary.
The elaborated_spec must contain detailed functional behavior in Plain text, not code, MeTTa, or JSON.
The test_spec must contain reviewable verification procedures in Plain text, not implementation code.
Preserve every [id:...], [covers:...], and :Concept: marker from the source verbatim.
Give new spec items unique IDs. Turn unresolved ambiguity into explicit Question: items.
Do not invent external dependencies, libraries, platforms, or implementation choices unless guidance names them.
For every functional requirement or constraint, include at least one test with a [covers:...] marker.
Do not claim that tests ran or that evidence exists when it was not supplied."""


@dataclass(frozen=True)
class PromptMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ElaborationPromptEnvelope:
    request_hash: str
    messages: tuple[PromptMessage, ...]
    response_schema: Mapping[str, Any]


@dataclass(frozen=True)
class ProviderCompletion:
    text: str
    provenance: ProviderProvenance


def _response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema", "elaborated_spec", "test_spec"],
        "properties": {
            "schema": {"const": RESPONSE_SCHEMA},
            "elaborated_spec": {"type": "string", "minLength": 1},
            "test_spec": {"type": "string", "minLength": 1},
        },
    }


def build_elaboration_prompt(request: ElaborationRequest) -> ElaborationPromptEnvelope:
    validate_elaboration_request(request)
    payload = elaboration_request_to_dict(request)
    user = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return ElaborationPromptEnvelope(
        elaboration_request_hash(request),
        (PromptMessage("system", SYSTEM_PROMPT), PromptMessage("user", user)),
        _response_schema(),
    )


def elaboration_prompt_to_dict(prompt: ElaborationPromptEnvelope) -> dict[str, Any]:
    validate_elaboration_prompt(prompt)
    return {
        "schema": PROMPT_SCHEMA,
        "request_hash": prompt.request_hash,
        "messages": [{"role": message.role, "content": message.content} for message in prompt.messages],
        "response_schema": dict(prompt.response_schema),
    }


def validate_elaboration_prompt(prompt: object) -> None:
    if not isinstance(prompt, ElaborationPromptEnvelope):
        raise ValueError("prompt must be an ElaborationPromptEnvelope")
    if len(prompt.messages) != 2 or tuple(message.role for message in prompt.messages) != ("system", "user"):
        raise ValueError("prompt must contain exactly one system and one user message")
    if prompt.messages[0].content != SYSTEM_PROMPT or not prompt.messages[1].content:
        raise ValueError("prompt content is not canonical")
    if prompt.response_schema != _response_schema():
        raise ValueError("response schema is not canonical")
    try:
        request = elaboration_request_from_dict(json.loads(prompt.messages[1].content))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("prompt user message is not a canonical elaboration request") from exc
    if prompt.messages[1].content != json.dumps(
        elaboration_request_to_dict(request), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ) or prompt.request_hash != elaboration_request_hash(request):
        raise ValueError("prompt does not bind to its exact canonical request")


def parse_elaboration_completion(
    request: ElaborationRequest, completion: ProviderCompletion,
) -> ElaborationResponse:
    validate_elaboration_request(request)
    if not isinstance(completion, ProviderCompletion) or not isinstance(completion.text, str):
        raise ValueError("completion must contain text and provider provenance")
    try:
        value = json.loads(completion.text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("provider completion must be one JSON object") from exc
    fields = {"schema", "elaborated_spec", "test_spec"}
    if not isinstance(value, dict) or set(value) != fields or value.get("schema") != RESPONSE_SCHEMA:
        raise ValueError("provider completion does not match the response schema")
    if any(not isinstance(value[field], str) or not value[field].strip() for field in ("elaborated_spec", "test_spec")):
        raise ValueError("provider completion documents must be non-blank text")
    response = ElaborationResponse(
        elaboration_request_hash(request), value["elaborated_spec"], value["test_spec"], completion.provenance,
    )
    validate_elaboration_response(response, request)
    return response

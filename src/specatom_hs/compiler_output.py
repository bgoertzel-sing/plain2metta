"""Strict, inert representation of Plain2MeTTa v2 compiler outputs.

This module validates and serializes generated text.  It deliberately has no
filesystem publication, imports, evaluation, subprocess, or test execution.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping


@dataclass(frozen=True)
class GeneratedFile:
    path: str
    content: str
    spec_ids: tuple[str, ...]
    test_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompilerOutputBundle:
    files: tuple[GeneratedFile, ...]
    compiler: str
    guidance: str | None = None


def _nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-blank text")
    return value


def _validate_path(path: object) -> str:
    value = _nonblank(path, "generated path")
    if value.startswith(("/", "\\")) or "\\" in value:
        raise ValueError("generated path must be a relative POSIX path")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("generated path contains an unsafe segment")
    return value


def compiler_output_to_dict(bundle: CompilerOutputBundle) -> dict[str, Any]:
    validate_compiler_output(bundle)
    return {
        "schema_version": 1,
        "executed": False,
        "compiler": bundle.compiler,
        "guidance": bundle.guidance,
        "files": [
            {
                "path": item.path,
                "content": item.content,
                "spec_ids": list(item.spec_ids),
                "test_ids": list(item.test_ids),
            }
            for item in bundle.files
        ],
    }


def canonical_compiler_output(bundle: CompilerOutputBundle) -> str:
    return json.dumps(
        compiler_output_to_dict(bundle), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def validate_compiler_output(bundle: CompilerOutputBundle) -> None:
    if not isinstance(bundle, CompilerOutputBundle):
        raise ValueError("compiler output must be a CompilerOutputBundle")
    _nonblank(bundle.compiler, "compiler")
    if bundle.guidance is not None and not isinstance(bundle.guidance, str):
        raise ValueError("guidance must be text or null")
    if not bundle.files:
        raise ValueError("compiler output requires at least one generated file")
    paths: set[str] = set()
    for item in bundle.files:
        if not isinstance(item, GeneratedFile):
            raise ValueError("compiler output files must be GeneratedFile records")
        path = _validate_path(item.path)
        if path in paths:
            raise ValueError("compiler output contains duplicate generated paths")
        paths.add(path)
        if not isinstance(item.content, str):
            raise ValueError("generated content must be text")
        if not item.spec_ids or any(not isinstance(v, str) or not v.strip() for v in item.spec_ids):
            raise ValueError("each generated file requires non-blank spec traceability IDs")
        if len(set(item.spec_ids)) != len(item.spec_ids):
            raise ValueError("generated file contains duplicate spec traceability IDs")
        if any(not isinstance(v, str) or not v.strip() for v in item.test_ids):
            raise ValueError("test traceability IDs must be non-blank text")
        if len(set(item.test_ids)) != len(item.test_ids):
            raise ValueError("generated file contains duplicate test traceability IDs")


def compiler_output_from_dict(payload: Mapping[str, Any]) -> CompilerOutputBundle:
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema_version", "executed", "compiler", "guidance", "files"
    }:
        raise ValueError("malformed compiler output envelope")
    if payload["schema_version"] != 1 or payload["executed"] is not False:
        raise ValueError("unsupported or executed compiler output")
    files = payload["files"]
    if not isinstance(files, list):
        raise ValueError("compiler output files must be a list")
    parsed = []
    for item in files:
        if not isinstance(item, Mapping) or set(item) != {"path", "content", "spec_ids", "test_ids"}:
            raise ValueError("malformed generated file record")
        if not isinstance(item["spec_ids"], list) or not isinstance(item["test_ids"], list):
            raise ValueError("traceability IDs must be lists")
        parsed.append(GeneratedFile(item["path"], item["content"], tuple(item["spec_ids"]), tuple(item["test_ids"])))
    bundle = CompilerOutputBundle(tuple(parsed), payload["compiler"], payload["guidance"])
    validate_compiler_output(bundle)
    return bundle

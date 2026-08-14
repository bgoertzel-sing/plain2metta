"""Immutable, content-addressed project state for the Plain2MeTTa v2 pipeline.

This module deliberately contains no LLM or execution integration.  It is the
small reviewable seam that binds derived artifacts and approvals to exact
upstream bytes before later pipeline phases are added.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from hashlib import sha256
from typing import Any, Iterable, Mapping


class ArtifactKind(str, Enum):
    ORIGINAL_SPEC = "original-spec"
    ELABORATED_SPEC = "elaborated-spec"
    TEST_SPEC = "test-spec"
    LOGICAL_IR = "logical-ir"


class ArtifactState(str, Enum):
    CURRENT = "current"
    INVALIDATED = "invalidated"


class ApprovalDecision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes-requested"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"


def content_sha256(content: str) -> str:
    if not isinstance(content, str):
        raise TypeError("artifact content must be text")
    return "sha256:" + sha256(content.encode("utf-8", errors="surrogatepass")).hexdigest()


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    content_hash: str


@dataclass(frozen=True)
class ArtifactVersion:
    artifact_id: str
    kind: ArtifactKind
    version: int
    content: str
    content_hash: str
    upstream: tuple[ArtifactRef, ...] = ()
    state: ArtifactState = ArtifactState.CURRENT

    @property
    def ref(self) -> ArtifactRef:
        return ArtifactRef(self.artifact_id, self.content_hash)


@dataclass(frozen=True)
class ApprovalState:
    artifact: ArtifactRef
    decision: ApprovalDecision
    reviewer: str | None = None
    rationale: str | None = None


@dataclass(frozen=True)
class Project:
    project_id: str
    name: str
    artifacts: tuple[ArtifactVersion, ...]
    approvals: tuple[ApprovalState, ...] = ()

    def artifact(self, artifact_id: str) -> ArtifactVersion:
        matches = [artifact for artifact in self.artifacts if artifact.artifact_id == artifact_id]
        if len(matches) != 1:
            raise ValueError(f"expected one artifact {artifact_id!r}, found {len(matches)}")
        return matches[0]

    def current(self, kind: ArtifactKind) -> ArtifactVersion | None:
        matches = [a for a in self.artifacts if a.kind is kind and a.state is ArtifactState.CURRENT]
        return max(matches, key=lambda a: a.version) if matches else None


def _artifact_id(project_id: str, kind: ArtifactKind, version: int, digest: str) -> str:
    value = sha256(f"{project_id}\0{kind.value}\0{version}\0{digest}".encode()).hexdigest()[:16]
    return f"artifact-{value}"


def create_project(project_id: str, name: str, source: str) -> Project:
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be non-blank text")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be non-blank text")
    digest = content_sha256(source)
    artifact = ArtifactVersion(
        _artifact_id(project_id, ArtifactKind.ORIGINAL_SPEC, 1, digest),
        ArtifactKind.ORIGINAL_SPEC,
        1,
        source,
        digest,
    )
    return Project(project_id, name, (artifact,))


def add_artifact(
    project: Project,
    kind: ArtifactKind,
    content: str,
    upstream: Iterable[ArtifactRef],
) -> Project:
    if kind is ArtifactKind.ORIGINAL_SPEC:
        raise ValueError("use replace_source to version the original spec")
    refs = tuple(upstream)
    if not refs:
        raise ValueError("derived artifacts require explicit upstream provenance")
    for ref in refs:
        artifact = project.artifact(ref.artifact_id)
        if artifact.content_hash != ref.content_hash or artifact.state is not ArtifactState.CURRENT:
            raise ValueError(f"upstream artifact {ref.artifact_id!r} is stale or hash-mismatched")
    previous = project.current(kind)
    if previous is not None:
        project = _invalidate_from(project, {previous.artifact_id})
    version = 1 + max((a.version for a in project.artifacts if a.kind is kind), default=0)
    digest = content_sha256(content)
    artifact = ArtifactVersion(_artifact_id(project.project_id, kind, version, digest), kind, version, content, digest, refs)
    return replace(project, artifacts=project.artifacts + (artifact,))


def decide(
    project: Project,
    artifact_ref: ArtifactRef,
    decision: ApprovalDecision,
    reviewer: str | None = None,
    rationale: str | None = None,
) -> Project:
    artifact = project.artifact(artifact_ref.artifact_id)
    if artifact.content_hash != artifact_ref.content_hash or artifact.state is not ArtifactState.CURRENT:
        raise ValueError("approval must bind to the exact current artifact content")
    if decision is ApprovalDecision.INVALIDATED:
        raise ValueError("invalidation is derived from upstream change, not a review decision")
    if decision is ApprovalDecision.APPROVED and (not isinstance(reviewer, str) or not reviewer.strip()):
        raise ValueError("approved artifacts require a reviewer identity")
    retained = tuple(a for a in project.approvals if a.artifact.artifact_id != artifact.artifact_id)
    return replace(project, approvals=retained + (ApprovalState(artifact.ref, decision, reviewer, rationale),))


def _invalidate_from(project: Project, invalid_ids: set[str]) -> Project:
    """Transitively invalidate exact derived versions and their review state."""
    changed = True
    while changed:
        changed = False
        for artifact in project.artifacts:
            if artifact.artifact_id not in invalid_ids and any(ref.artifact_id in invalid_ids for ref in artifact.upstream):
                invalid_ids.add(artifact.artifact_id)
                changed = True
    return replace(
        project,
        artifacts=tuple(
        replace(a, state=ArtifactState.INVALIDATED) if a.artifact_id in invalid_ids else a
        for a in project.artifacts
        ),
        approvals=tuple(
            replace(a, decision=ApprovalDecision.INVALIDATED)
            if a.artifact.artifact_id in invalid_ids else a
            for a in project.approvals
        ),
    )


def replace_source(project: Project, source: str) -> Project:
    current = project.current(ArtifactKind.ORIGINAL_SPEC)
    if current is None:
        raise ValueError("project has no current original source")
    digest = content_sha256(source)
    if digest == current.content_hash:
        return project
    project = _invalidate_from(project, {current.artifact_id})
    version = current.version + 1
    new_source = ArtifactVersion(
        _artifact_id(project.project_id, ArtifactKind.ORIGINAL_SPEC, version, digest),
        ArtifactKind.ORIGINAL_SPEC,
        version,
        source,
        digest,
    )
    return replace(project, artifacts=project.artifacts + (new_source,))


def project_to_dict(project: Project) -> dict[str, Any]:
    def ref(value: ArtifactRef) -> dict[str, str]:
        return {"artifact_id": value.artifact_id, "content_hash": value.content_hash}
    return {
        "schema_version": 1,
        "project_id": project.project_id,
        "name": project.name,
        "artifacts": [
            {
                "artifact_id": a.artifact_id,
                "kind": a.kind.value,
                "version": a.version,
                "content": a.content,
                "content_hash": a.content_hash,
                "upstream": [ref(value) for value in a.upstream],
                "state": a.state.value,
            }
            for a in project.artifacts
        ],
        "approvals": [
            {"artifact": ref(a.artifact), "decision": a.decision.value, "reviewer": a.reviewer, "rationale": a.rationale}
            for a in project.approvals
        ],
    }


def project_from_dict(payload: Mapping[str, Any]) -> Project:
    """Deserialize and validate all hashes/references; malformed state fails closed."""
    try:
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported project schema_version")
        artifacts = tuple(
            ArtifactVersion(
                item["artifact_id"], ArtifactKind(item["kind"]), item["version"], item["content"],
                item["content_hash"],
                tuple(ArtifactRef(ref["artifact_id"], ref["content_hash"]) for ref in item["upstream"]),
                ArtifactState(item["state"]),
            )
            for item in payload["artifacts"]
        )
        approvals = tuple(
            ApprovalState(
                ArtifactRef(item["artifact"]["artifact_id"], item["artifact"]["content_hash"]),
                ApprovalDecision(item["decision"]), item.get("reviewer"), item.get("rationale"),
            )
            for item in payload["approvals"]
        )
        project = Project(payload["project_id"], payload["name"], artifacts, approvals)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed project state: {exc}") from exc
    if len({a.artifact_id for a in artifacts}) != len(artifacts):
        raise ValueError("malformed project state: duplicate artifact_id")
    for artifact in artifacts:
        if artifact.version < 1 or artifact.content_hash != content_sha256(artifact.content):
            raise ValueError(f"malformed project state: invalid content hash/version for {artifact.artifact_id}")
        expected_id = _artifact_id(project.project_id, artifact.kind, artifact.version, artifact.content_hash)
        if artifact.artifact_id != expected_id:
            raise ValueError(f"malformed project state: invalid artifact_id {artifact.artifact_id}")
        for upstream in artifact.upstream:
            target = project.artifact(upstream.artifact_id)
            if target.content_hash != upstream.content_hash:
                raise ValueError("malformed project state: upstream hash mismatch")
    for approval in approvals:
        target = project.artifact(approval.artifact.artifact_id)
        if target.content_hash != approval.artifact.content_hash:
            raise ValueError("malformed project state: approval hash mismatch")
        if approval.decision is ApprovalDecision.APPROVED and (not approval.reviewer or not approval.reviewer.strip()):
            raise ValueError("malformed project state: approved artifact lacks reviewer")
        if target.state is ArtifactState.INVALIDATED and approval.decision is not ApprovalDecision.INVALIDATED:
            raise ValueError("malformed project state: stale artifact has active approval")
    return project

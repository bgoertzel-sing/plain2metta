"""Framework-neutral persisted commands for the first v2 review transitions."""

from __future__ import annotations

from typing import Protocol

from .projects import (
    ApprovalDecision,
    ArtifactKind,
    ArtifactRef,
    Project,
    add_artifact,
    annotate,
    decide,
    decide_logical_finding,
    submit_phase3_review,
)


class ProjectWriter(Protocol):
    """Minimum persistence capability required by the command boundary."""

    def create(self, project_id: str, name: str, source: str) -> Project: ...

    def get(self, project_id: str) -> Project: ...

    def save(self, project: Project, *, require_existing: bool = True) -> None: ...


class ProjectCommandService:
    """Persist explicit user commands without exposing generic mutation seams."""

    def __init__(self, repository: ProjectWriter):
        self._repository = repository

    def create_project(self, project_id: str, name: str, source: str) -> Project:
        return self._repository.create(project_id, name, source)

    def submit_elaborated_spec(
        self, project_id: str, upstream_artifact_id: str,
        upstream_content_hash: str, content: str,
    ) -> Project:
        return self._submit_derived_spec(
            project_id, ArtifactKind.ORIGINAL_SPEC, ArtifactKind.ELABORATED_SPEC,
            upstream_artifact_id, upstream_content_hash, content,
        )

    def submit_test_spec(
        self, project_id: str, upstream_artifact_id: str,
        upstream_content_hash: str, content: str,
    ) -> Project:
        return self._submit_derived_spec(
            project_id, ArtifactKind.ELABORATED_SPEC, ArtifactKind.TEST_SPEC,
            upstream_artifact_id, upstream_content_hash, content,
        )

    def _submit_derived_spec(
        self, project_id: str, upstream_kind: ArtifactKind, result_kind: ArtifactKind,
        upstream_artifact_id: str, upstream_content_hash: str, content: str,
    ) -> Project:
        project = self._repository.get(project_id)
        supplied = _artifact_ref(upstream_artifact_id, upstream_content_hash)
        current = project.current(upstream_kind)
        if current is None or supplied != current.ref:
            raise ValueError(f"submission requires the exact current {upstream_kind.value} artifact")
        updated = add_artifact(project, result_kind, content, (supplied,))
        self._repository.save(updated)
        return updated

    def add_annotation(
        self,
        project_id: str,
        artifact_id: str,
        content_hash: str,
        reviewer: str,
        comment: str,
        target: str | None = None,
    ) -> Project:
        project = self._repository.get(project_id)
        updated = annotate(
            project,
            _artifact_ref(artifact_id, content_hash),
            reviewer,
            comment,
            target,
        )
        self._repository.save(updated)
        return updated

    def submit_decision(
        self,
        project_id: str,
        artifact_id: str,
        content_hash: str,
        decision: str,
        reviewer: str | None = None,
        rationale: str | None = None,
    ) -> Project:
        if not isinstance(decision, str):
            raise ValueError("decision must be a declared review decision")
        try:
            declared = ApprovalDecision(decision)
        except ValueError as exc:
            raise ValueError("decision must be a declared review decision") from exc
        if declared is ApprovalDecision.INVALIDATED:
            raise ValueError("invalidation is derived and cannot be submitted")
        project = self._repository.get(project_id)
        updated = decide(
            project,
            _artifact_ref(artifact_id, content_hash),
            declared,
            reviewer,
            rationale,
        )
        self._repository.save(updated)
        return updated

    def submit_phase3_review(self, project_id: str, review_log: object) -> Project:
        """Atomically persist a strict exact-version Phase 3 review transaction."""
        project = self._repository.get(project_id)
        updated = submit_phase3_review(project, review_log)
        self._repository.save(updated)
        return updated

    def submit_logical_finding_decision(
        self,
        project_id: str,
        logical_ir_artifact_id: str,
        logical_ir_content_hash: str,
        logical_review_artifact_id: str,
        logical_review_content_hash: str,
        finding_id: str,
        disposition: str,
        reviewer: str,
        rationale: str,
    ) -> Project:
        """Persist one decision only against the exact current IR and review."""
        from .logical_ir import FindingDisposition

        project = self._repository.get(project_id)
        logical = project.current(ArtifactKind.LOGICAL_IR)
        review = project.current(ArtifactKind.LOGICAL_REVIEW)
        if logical is None or logical.ref != _artifact_ref(logical_ir_artifact_id, logical_ir_content_hash):
            raise ValueError("decision requires the exact current logical IR artifact")
        if review is None or review.ref != _artifact_ref(logical_review_artifact_id, logical_review_content_hash):
            raise ValueError("decision requires the exact current logical review artifact")
        if not isinstance(disposition, str):
            raise ValueError("disposition must be a declared logical finding disposition")
        try:
            declared = FindingDisposition(disposition)
        except ValueError as exc:
            raise ValueError("disposition must be a declared logical finding disposition") from exc
        updated = decide_logical_finding(project, finding_id, declared, reviewer, rationale)
        self._repository.save(updated)
        return updated


def _artifact_ref(artifact_id: str, content_hash: str) -> ArtifactRef:
    if not isinstance(artifact_id, str) or not artifact_id.strip():
        raise ValueError("artifact_id must be non-blank text")
    if not isinstance(content_hash, str) or not content_hash.startswith("sha256:"):
        raise ValueError("content_hash must be an explicit SHA-256 artifact hash")
    return ArtifactRef(artifact_id, content_hash)

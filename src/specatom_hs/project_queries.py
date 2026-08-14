"""Read-only query boundary for persisted Plain2MeTTa v2 project state."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Protocol

from .project_repository import ProjectStatus, project_status
from .projects import ArtifactKind, ArtifactState, Project
from .traceability import TraceabilityEntry, traceability_report_from_dict


class ProjectReader(Protocol):
    """The storage capabilities exposed to the query service."""

    def get(self, project_id: str) -> Project: ...

    def list_statuses(self) -> tuple[ProjectStatus, ...]: ...


@dataclass(frozen=True)
class VersionSummary:
    artifact_id: str
    kind: str
    version: int
    content_hash: str
    state: str
    upstream_artifact_ids: tuple[str, ...]
    approval: str | None


class ProjectQueryService:
    """Serializable status, version-history, and trace queries with no writes."""

    def __init__(self, projects: ProjectReader):
        self._projects = projects

    def list_projects(self) -> tuple[dict[str, Any], ...]:
        return tuple(_status_to_dict(status) for status in self._projects.list_statuses())

    def status(self, project_id: str) -> dict[str, Any]:
        return _status_to_dict(project_status(self._projects.get(project_id)))

    def version_history(self, project_id: str) -> tuple[dict[str, Any], ...]:
        project = self._projects.get(project_id)
        approvals = {approval.artifact.artifact_id: approval.decision for approval in project.approvals}
        versions = tuple(
            VersionSummary(
                artifact.artifact_id,
                artifact.kind.value,
                artifact.version,
                artifact.content_hash,
                artifact.state.value,
                tuple(ref.artifact_id for ref in artifact.upstream),
                approvals[artifact.artifact_id].value if artifact.artifact_id in approvals else None,
            )
            for artifact in sorted(project.artifacts, key=lambda item: (item.kind.value, item.version))
        )
        return tuple(asdict(version) for version in versions)

    def trace(self, project_id: str, spec_id: str | None = None) -> dict[str, Any]:
        if spec_id is not None and (not isinstance(spec_id, str) or not spec_id.strip()):
            raise ValueError("spec_id must be absent or non-blank text")
        project = self._projects.get(project_id)
        artifact = project.current(ArtifactKind.TRACEABILITY_REPORT)
        if artifact is None or artifact.state is not ArtifactState.CURRENT:
            raise ValueError("project has no current traceability report")
        try:
            report = traceability_report_from_dict(json.loads(artifact.content))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"invalid current traceability report: {exc}") from exc
        entries = report.entries
        if spec_id is not None:
            entries = tuple(entry for entry in entries if entry.spec_id == spec_id)
            if not entries:
                raise KeyError(f"unknown traceability spec_id {spec_id!r}")
        return {
            "project_id": project.project_id,
            "artifact_id": artifact.artifact_id,
            "content_hash": artifact.content_hash,
            "provenance": tuple(asdict(link) for link in report.provenance),
            "entries": tuple(_trace_entry_to_dict(entry) for entry in entries),
        }


def _status_to_dict(status: ProjectStatus) -> dict[str, Any]:
    return {
        "project_id": status.project_id,
        "name": status.name,
        "current_artifacts": tuple(kind.value for kind in status.current_artifacts),
        "invalidated_artifact_count": status.invalidated_artifact_count,
        "approved_artifact_count": status.approved_artifact_count,
    }


def _trace_entry_to_dict(entry: TraceabilityEntry) -> dict[str, Any]:
    return asdict(entry)

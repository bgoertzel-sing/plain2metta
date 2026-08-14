"""Atomic local persistence for immutable Plain2MeTTa project state."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .projects import (
    ApprovalDecision,
    ArtifactKind,
    ArtifactState,
    Project,
    create_project,
    project_from_dict,
    project_to_dict,
)


_PROJECT_ID = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\Z")


def validate_project_id(project_id: str) -> str:
    """Return a canonical storage-safe project ID or fail closed."""
    if not isinstance(project_id, str) or _PROJECT_ID.fullmatch(project_id) is None:
        raise ValueError("project_id must be 1-64 lowercase ASCII letters, digits, or interior hyphens")
    return project_id


@dataclass(frozen=True)
class ProjectStatus:
    project_id: str
    name: str
    current_artifacts: tuple[ArtifactKind, ...]
    invalidated_artifact_count: int
    approved_artifact_count: int


def project_status(project: Project) -> ProjectStatus:
    current = tuple(sorted(
        (artifact.kind for artifact in project.artifacts if artifact.state is ArtifactState.CURRENT),
        key=lambda kind: kind.value,
    ))
    return ProjectStatus(
        project.project_id,
        project.name,
        current,
        sum(artifact.state is ArtifactState.INVALIDATED for artifact in project.artifacts),
        sum(approval.decision is ApprovalDecision.APPROVED for approval in project.approvals),
    )


class FilesystemProjectRepository:
    """One strict JSON document per project, committed with an atomic rename."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir() or self.root.is_symlink():
            raise ValueError("project repository root must be a real directory")

    def _path(self, project_id: str) -> Path:
        return self.root / f"{validate_project_id(project_id)}.json"

    def create(self, project_id: str, name: str, source: str) -> Project:
        path = self._path(project_id)
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"project {project_id!r} already exists")
        project = create_project(project_id, name, source)
        self.save(project, require_existing=False)
        return project

    def save(self, project: Project, *, require_existing: bool = True) -> None:
        path = self._path(project.project_id)
        if path.is_symlink():
            raise ValueError("refusing symlink project state")
        if require_existing and not path.is_file():
            raise FileNotFoundError(f"project {project.project_id!r} does not exist")
        serialized = project_to_dict(project)
        project_from_dict(serialized)  # Refuse programmatically forged state too.
        payload = json.dumps(serialized, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        fd, temporary = tempfile.mkstemp(prefix=f".{project.project_id}.", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if require_existing:
                os.replace(temporary, path)
            else:
                # Linking a fully flushed inode publishes it without an overwrite
                # window; concurrent creators get FileExistsError.
                os.link(temporary, path)
                os.unlink(temporary)
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def get(self, project_id: str) -> Project:
        path = self._path(project_id)
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                os.close(fd)
                raise ValueError("project state must be a regular file")
            with os.fdopen(fd, "r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except OSError as exc:
            if path.is_symlink():
                raise ValueError("refusing symlink project state") from exc
            raise
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed stored project {project_id!r}: {exc.msg}") from exc
        project = project_from_dict(payload)
        if project.project_id != project_id:
            raise ValueError("stored project_id does not match its filename")
        return project

    def list_statuses(self) -> tuple[ProjectStatus, ...]:
        statuses = []
        for path in sorted(self.root.iterdir(), key=lambda item: item.name):
            if path.name.startswith("."):
                continue
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise ValueError(f"unexpected repository entry {path.name!r}")
            statuses.append(project_status(self.get(path.stem)))
        return tuple(statuses)

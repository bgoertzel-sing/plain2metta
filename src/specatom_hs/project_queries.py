"""Read-only query boundary for persisted Plain2MeTTa v2 project state."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Protocol

from .project_repository import ProjectStatus, project_status
from .projects import ArtifactKind, ArtifactState, Project, content_sha256
from .phase3_review import (
    phase3_review_log_from_dict,
    phase3_review_log_to_dict,
    validate_phase3_review_log,
)
from .review_diff import build_phase3_review_diff, phase3_review_diff_to_dict
from .traceability import (
    ProvenanceLink,
    TraceabilityEntry,
    build_traceability_report,
    canonical_traceability_report,
    traceability_report_from_dict,
)
from .logical_ir import (
    logical_ir_from_dict,
    logical_review_from_dict,
    logical_review_to_dict,
    validate_review_for_document,
)
from .compiler_output import (
    canonical_compiler_output,
    compiler_output_from_dict,
)
from .sandbox_handoff import sandbox_handoff_from_dict
from .sandbox_protocol import (
    canonical_test_result,
    sandbox_request_hash,
    test_result_from_dict,
    test_result_to_dict,
)


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

    def phase3_review(self, project_id: str) -> dict[str, Any]:
        """Return recomputed exact-version review material without artifact bodies."""
        return phase3_review_diff_to_dict(build_phase3_review_diff(self._projects.get(project_id)))

    def phase3_review_decisions(self, project_id: str) -> dict[str, Any]:
        """Return the validated current review log without reviewed artifact bodies."""
        project = self._projects.get(project_id)
        artifact = project.current(ArtifactKind.REVIEW_LOG)
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        tests = project.current(ArtifactKind.TEST_SPEC)
        if artifact is None or artifact.state is not ArtifactState.CURRENT:
            raise ValueError("project has no current Phase 3 review log")
        if elaborated is None or tests is None or artifact.upstream != (elaborated.ref, tests.ref):
            raise ValueError("current Phase 3 review log is not bound to exact current inputs")
        try:
            log = phase3_review_log_from_dict(json.loads(artifact.content))
            validate_phase3_review_log(log, elaborated.ref, tests.ref)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"invalid current Phase 3 review log: {exc}") from exc
        metadata = phase3_review_log_to_dict(log)
        metadata["reviewed_outputs"] = {
            "elaborated_spec_hash": (
                content_sha256(log.reviewed_elaborated_spec)
                if log.reviewed_elaborated_spec is not None else None
            ),
            "test_spec_hash": (
                content_sha256(log.reviewed_test_spec)
                if log.reviewed_test_spec is not None else None
            ),
        }
        return {
            "project_id": project.project_id,
            "review_log_artifact_id": artifact.artifact_id,
            "review_log_content_hash": artifact.content_hash,
            "review_log": metadata,
        }

    def logical_review(self, project_id: str) -> dict[str, Any]:
        """Return the validated exact-version logical review without IR content."""
        project = self._projects.get(project_id)
        logical = project.current(ArtifactKind.LOGICAL_IR)
        review = project.current(ArtifactKind.LOGICAL_REVIEW)
        if logical is None or review is None:
            raise ValueError("project has no current logical IR review")
        if review.state is not ArtifactState.CURRENT or review.upstream != (logical.ref,):
            raise ValueError("current logical review is not bound to the exact current logical IR")
        try:
            document = logical_ir_from_dict(json.loads(logical.content))
            report = logical_review_from_dict(json.loads(review.content))
            validate_review_for_document(report, document)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"invalid current logical review: {exc}") from exc
        return {
            "project_id": project.project_id,
            "logical_ir_artifact_id": logical.artifact_id,
            "logical_ir_content_hash": logical.content_hash,
            "logical_review_artifact_id": review.artifact_id,
            "logical_review_content_hash": review.content_hash,
            "logical_review": logical_review_to_dict(report),
        }

    def compiler_output(self, project_id: str) -> dict[str, Any]:
        """Return validated inert output metadata without generated-file bodies."""
        project = self._projects.get(project_id)
        output = project.current(ArtifactKind.COMPILER_OUTPUT)
        interaction = project.current(ArtifactKind.COMPILATION_LOG)
        logical = project.current(ArtifactKind.LOGICAL_IR)
        if output is None or interaction is None:
            raise ValueError("project has no current compiler output")
        if (
            output.state is not ArtifactState.CURRENT
            or interaction.state is not ArtifactState.CURRENT
            or logical is None
            or output.upstream != (logical.ref,)
        ):
            raise ValueError("current compiler output is not bound to the exact current logical IR")
        try:
            bundle = compiler_output_from_dict(json.loads(output.content))
            log = json.loads(interaction.content)
            if output.content != canonical_compiler_output(bundle):
                raise ValueError("compiler output is not canonical")
            if (
                not isinstance(log, dict)
                or set(log) != {"schema", "request", "request_hash", "compiler_output_hash", "provenance"}
                or log.get("schema") != "plain2metta-compilation-log/v1"
                or log.get("compiler_output_hash") != output.content_hash
            ):
                raise ValueError("compilation log does not bind the exact compiler output")
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"invalid current compiler output: {exc}") from exc
        return {
            "project_id": project.project_id,
            "compilation_log_artifact_id": interaction.artifact_id,
            "compilation_log_content_hash": interaction.content_hash,
            "compiler_output_artifact_id": output.artifact_id,
            "compiler_output_content_hash": output.content_hash,
            "logical_ir_artifact_id": logical.artifact_id,
            "logical_ir_content_hash": logical.content_hash,
            "compiler": bundle.compiler,
            "executed": False,
            "files": tuple({
                "path": item.path,
                "content_hash": content_sha256(item.content),
                "byte_size": len(item.content.encode("utf-8")),
                "spec_ids": item.spec_ids,
                "test_ids": item.test_ids,
            } for item in bundle.files),
        }

    def test_result(self, project_id: str) -> dict[str, Any]:
        """Return validated test metadata without captured stdout/stderr bodies."""
        project = self._projects.get(project_id)
        result_artifact = project.current(ArtifactKind.TEST_RESULT)
        handoff_artifact = project.current(ArtifactKind.SANDBOX_HANDOFF)
        if result_artifact is None or handoff_artifact is None:
            raise ValueError("project has no current test result")
        if (
            result_artifact.state is not ArtifactState.CURRENT
            or handoff_artifact.state is not ArtifactState.CURRENT
            or result_artifact.upstream != (handoff_artifact.ref,)
        ):
            raise ValueError("current test result is not bound to the exact current sandbox handoff")
        try:
            handoff = sandbox_handoff_from_dict(json.loads(handoff_artifact.content))
            result = test_result_from_dict(json.loads(result_artifact.content))
            if result_artifact.content != canonical_test_result(result):
                raise ValueError("test result is not canonical")
            if result.request_hash != sandbox_request_hash(handoff):
                raise ValueError("test result does not bind the exact sandbox request")
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"invalid current test result: {exc}") from exc
        serialized = test_result_to_dict(result)
        return {
            "project_id": project.project_id,
            "sandbox_handoff_artifact_id": handoff_artifact.artifact_id,
            "sandbox_handoff_content_hash": handoff_artifact.content_hash,
            "test_result_artifact_id": result_artifact.artifact_id,
            "test_result_content_hash": result_artifact.content_hash,
            "request_hash": result.request_hash,
            "adapter": result.adapter,
            "summary": serialized["summary"],
            "tests": tuple({
                "test_id": test.test_id,
                "status": test.status,
                "duration_ms": test.duration_ms,
                "stdout_hash": content_sha256(test.stdout),
                "stdout_byte_size": len(test.stdout.encode("utf-8")),
                "stderr_hash": content_sha256(test.stderr),
                "stderr_byte_size": len(test.stderr.encode("utf-8")),
                "covered_spec_ids": test.covered_spec_ids,
                "assertion": test.assertion,
            } for test in result.tests),
        }

    def trace(self, project_id: str, spec_id: str | None = None) -> dict[str, Any]:
        if spec_id is not None and (not isinstance(spec_id, str) or not spec_id.strip()):
            raise ValueError("spec_id must be absent or non-blank text")
        project = self._projects.get(project_id)
        artifact = project.current(ArtifactKind.TRACEABILITY_REPORT)
        if artifact is None or artifact.state is not ArtifactState.CURRENT:
            raise ValueError("project has no current traceability report")
        required = tuple(project.current(kind) for kind in (
            ArtifactKind.ORIGINAL_SPEC,
            ArtifactKind.ELABORATED_SPEC,
            ArtifactKind.TEST_SPEC,
            ArtifactKind.REVIEWED_ELABORATED_SPEC,
            ArtifactKind.REVIEWED_TEST_SPEC,
            ArtifactKind.LOGICAL_IR,
            ArtifactKind.COMPILER_OUTPUT,
            ArtifactKind.SANDBOX_HANDOFF,
            ArtifactKind.TEST_RESULT,
        ))
        if any(item is None or item.state is not ArtifactState.CURRENT for item in required):
            raise ValueError("current traceability provenance chain is incomplete")
        original, elaborated, tests, reviewed_elaborated, reviewed_tests, logical, output, handoff, result = required
        expected_links = (
            (elaborated, (original.ref,)),
            (tests, (elaborated.ref,)),
            (logical, (reviewed_elaborated.ref, reviewed_tests.ref)),
            (output, (logical.ref,)),
            (handoff, (output.ref,)),
            (result, (handoff.ref,)),
            (artifact, (output.ref, result.ref)),
        )
        if any(item.upstream != upstream for item, upstream in expected_links):
            raise ValueError("current traceability report is not bound to the exact current chain")
        try:
            report = traceability_report_from_dict(json.loads(artifact.content))
            bundle = compiler_output_from_dict(json.loads(output.content))
            test_result = test_result_from_dict(json.loads(result.content))
            provenance = tuple(
                ProvenanceLink(item.kind.value, item.artifact_id, item.content_hash)
                for item in required
            )
            expected = build_traceability_report(provenance, bundle, test_result)
            if report != expected or artifact.content != canonical_traceability_report(expected):
                raise ValueError("traceability report does not match exact current inputs")
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

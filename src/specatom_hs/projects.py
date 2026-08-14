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
    LOGICAL_REVIEW = "logical-review"
    COMPILER_OUTPUT = "compiler-output"
    SANDBOX_HANDOFF = "sandbox-handoff"
    TEST_RESULT = "test-result"
    TRACEABILITY_REPORT = "traceability-report"


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
class ReviewAnnotation:
    artifact: ArtifactRef
    reviewer: str
    comment: str
    target: str | None = None


@dataclass(frozen=True)
class Project:
    project_id: str
    name: str
    artifacts: tuple[ArtifactVersion, ...]
    approvals: tuple[ApprovalState, ...] = ()
    annotations: tuple[ReviewAnnotation, ...] = ()

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
    if kind in (ArtifactKind.LOGICAL_IR, ArtifactKind.LOGICAL_REVIEW):
        raise ValueError("use add_logical_ir or add_logical_ir_document to enforce the review gate")
    if kind is ArtifactKind.COMPILER_OUTPUT:
        raise ValueError("use the phase-specific add_compiler_output transition API")
    if kind is ArtifactKind.SANDBOX_HANDOFF:
        raise ValueError("use the phase-specific add_sandbox_handoff transition API")
    if kind is ArtifactKind.TEST_RESULT:
        raise ValueError("use the phase-specific add_test_result transition API")
    if kind is ArtifactKind.TRACEABILITY_REPORT:
        raise ValueError("use the phase-specific add_traceability_report transition API")
    return _add_derived_artifact(project, kind, content, upstream)


def _add_derived_artifact(
    project: Project,
    kind: ArtifactKind,
    content: str,
    upstream: Iterable[ArtifactRef],
) -> Project:
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


def _is_approved(project: Project, artifact: ArtifactVersion) -> bool:
    return any(
        approval.artifact == artifact.ref and approval.decision is ApprovalDecision.APPROVED
        for approval in project.approvals
    )


def add_logical_ir(project: Project, content: str) -> Project:
    """Add a logical IR only from the exact current approved spec and tests."""
    elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
    tests = project.current(ArtifactKind.TEST_SPEC)
    if elaborated is None or tests is None:
        raise ValueError("logical IR requires current elaborated-spec and test-spec artifacts")
    if not _is_approved(project, elaborated) or not _is_approved(project, tests):
        raise ValueError("logical IR requires explicit approval of exact current elaborated spec and test spec")
    return _add_derived_artifact(project, ArtifactKind.LOGICAL_IR, content, (elaborated.ref, tests.ref))


def add_logical_ir_document(project: Project, document: object) -> Project:
    """Persist a canonical non-executable IR and its initial hash-bound review."""
    from .logical_ir import canonical_logical_ir, logical_review_to_dict, review_logical_ir
    import json

    project = add_logical_ir(project, canonical_logical_ir(document))
    logical = project.current(ArtifactKind.LOGICAL_IR)
    report = review_logical_ir(document)
    if report.logical_ir_hash != logical.content_hash:
        raise ValueError("logical review hash does not bind to the persisted logical IR")
    content = json.dumps(logical_review_to_dict(report), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _add_derived_artifact(project, ArtifactKind.LOGICAL_REVIEW, content, (logical.ref,))


def decide_logical_finding(
    project: Project,
    finding_id: str,
    disposition: object,
    reviewer: str,
    rationale: str,
) -> Project:
    """Persist one attributed finding transition as a new review version."""
    from .logical_ir import (
        decide_finding,
        logical_ir_from_dict,
        logical_review_from_dict,
        logical_review_to_dict,
        validate_review_for_document,
    )
    import json

    logical = project.current(ArtifactKind.LOGICAL_IR)
    review = project.current(ArtifactKind.LOGICAL_REVIEW)
    if logical is None or review is None or review.upstream != (logical.ref,):
        raise ValueError("logical finding decisions require the exact current logical IR and review")
    try:
        document = logical_ir_from_dict(json.loads(logical.content))
        report = logical_review_from_dict(json.loads(review.content))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid current logical review state: {exc}") from exc
    validate_review_for_document(report, document)
    updated = decide_finding(report, finding_id, disposition, reviewer, rationale)
    content = json.dumps(logical_review_to_dict(updated), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _add_derived_artifact(project, ArtifactKind.LOGICAL_REVIEW, content, (logical.ref,))


def admit_compilation(project: Project) -> ArtifactVersion:
    """Return the exact logical IR admitted for compilation, or fail closed."""
    from .logical_ir import (
        logical_ir_from_dict,
        logical_review_from_dict,
        validate_review_for_document,
    )
    import json

    logical = project.current(ArtifactKind.LOGICAL_IR)
    review = project.current(ArtifactKind.LOGICAL_REVIEW)
    if logical is None or review is None or review.upstream != (logical.ref,):
        raise ValueError("compilation requires the exact current logical IR and logical review")
    if not _is_approved(project, logical):
        raise ValueError("compilation requires explicit approval of the exact current logical IR")
    try:
        document = logical_ir_from_dict(json.loads(logical.content))
        report = logical_review_from_dict(json.loads(review.content))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid current logical review state: {exc}") from exc
    validate_review_for_document(report, document)
    if report.blocks_compilation:
        raise ValueError("compilation blocked by unresolved critical logical-review findings")
    return logical


def add_compiler_output(project: Project, bundle: object) -> Project:
    """Persist generated text from the exact admitted IR without executing it."""
    from .compiler_output import canonical_compiler_output

    logical = admit_compilation(project)
    return _add_derived_artifact(
        project, ArtifactKind.COMPILER_OUTPUT, canonical_compiler_output(bundle), (logical.ref,)
    )


def add_sandbox_handoff(project: Project, handoff: object) -> Project:
    """Persist inert sandbox metadata for the exact approved compiler output."""
    from .compiler_output import compiler_output_from_dict
    from .sandbox_handoff import canonical_sandbox_handoff, validate_sandbox_handoff
    import json

    output = project.current(ArtifactKind.COMPILER_OUTPUT)
    if output is None or not _is_approved(project, output):
        raise ValueError("sandbox handoff requires explicit approval of the exact current compiler output")
    try:
        bundle = compiler_output_from_dict(json.loads(output.content))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid current compiler output: {exc}") from exc
    validate_sandbox_handoff(handoff)
    expected_files = tuple(generated.path for generated in bundle.files)
    if handoff.files != expected_files:
        raise ValueError("sandbox handoff files must exactly match the approved compiler output")
    return _add_derived_artifact(
        project, ArtifactKind.SANDBOX_HANDOFF, canonical_sandbox_handoff(handoff), (output.ref,)
    )


def add_test_result(project: Project, result: object) -> Project:
    """Persist adapter output without invoking an adapter or generated code."""
    import json
    from .sandbox_handoff import sandbox_handoff_from_dict
    from .sandbox_protocol import canonical_test_result, sandbox_request_hash, validate_test_result

    handoff_artifact = project.current(ArtifactKind.SANDBOX_HANDOFF)
    if handoff_artifact is None:
        raise ValueError("test result requires the exact current sandbox handoff")
    try:
        handoff = sandbox_handoff_from_dict(json.loads(handoff_artifact.content))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid current sandbox handoff: {exc}") from exc
    validate_test_result(result)
    if result.request_hash != sandbox_request_hash(handoff):
        raise ValueError("test result does not bind to the exact sandbox request")
    return _add_derived_artifact(project, ArtifactKind.TEST_RESULT, canonical_test_result(result), (handoff_artifact.ref,))


def add_traceability_report(project: Project) -> Project:
    """Persist the exact Phase 7 provenance/code/test/result join."""
    import json
    from .compiler_output import compiler_output_from_dict
    from .sandbox_protocol import test_result_from_dict
    from .traceability import ProvenanceLink, build_traceability_report, canonical_traceability_report

    required = tuple(
        project.current(kind) for kind in (
            ArtifactKind.ORIGINAL_SPEC, ArtifactKind.ELABORATED_SPEC, ArtifactKind.TEST_SPEC,
            ArtifactKind.LOGICAL_IR, ArtifactKind.COMPILER_OUTPUT, ArtifactKind.SANDBOX_HANDOFF,
            ArtifactKind.TEST_RESULT,
        )
    )
    if any(artifact is None for artifact in required):
        raise ValueError("traceability report requires the exact complete current provenance chain")
    original, elaborated, tests, logical, output, handoff, result_artifact = required
    expected_links = (
        (elaborated, (original.ref,)),
        (tests, (elaborated.ref,)),
        (logical, (elaborated.ref, tests.ref)),
        (output, (logical.ref,)),
        (handoff, (output.ref,)),
        (result_artifact, (handoff.ref,)),
    )
    if any(artifact.upstream != upstream for artifact, upstream in expected_links):
        raise ValueError("traceability report has invalid provenance chain")
    try:
        bundle = compiler_output_from_dict(json.loads(output.content))
        result = test_result_from_dict(json.loads(result_artifact.content))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid traceability inputs: {exc}") from exc
    provenance = tuple(
        ProvenanceLink(artifact.kind.value, artifact.artifact_id, artifact.content_hash)
        for artifact in required
    )
    report = build_traceability_report(provenance, bundle, result)
    return _add_derived_artifact(
        project, ArtifactKind.TRACEABILITY_REPORT, canonical_traceability_report(report),
        (output.ref, result_artifact.ref),
    )


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
    previous = next((a for a in project.approvals if a.artifact == artifact.ref), None)
    retained = tuple(a for a in project.approvals if a.artifact.artifact_id != artifact.artifact_id)
    project = replace(project, approvals=retained + (ApprovalState(artifact.ref, decision, reviewer, rationale),))
    if previous is not None and previous.decision is ApprovalDecision.APPROVED and decision is not ApprovalDecision.APPROVED:
        project = _invalidate_dependents(project, artifact.artifact_id)
    return project


def annotate(
    project: Project,
    artifact_ref: ArtifactRef,
    reviewer: str,
    comment: str,
    target: str | None = None,
) -> Project:
    """Append a section/item/general comment bound to exact current artifact bytes."""
    artifact = project.artifact(artifact_ref.artifact_id)
    if artifact.content_hash != artifact_ref.content_hash or artifact.state is not ArtifactState.CURRENT:
        raise ValueError("annotation must bind to the exact current artifact content")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("annotation requires a reviewer identity")
    if not isinstance(comment, str) or not comment.strip():
        raise ValueError("annotation comment must be non-blank text")
    if target is not None and (not isinstance(target, str) or not target.strip()):
        raise ValueError("annotation target must be absent or non-blank text")
    annotation = ReviewAnnotation(artifact.ref, reviewer, comment, target)
    return replace(project, annotations=project.annotations + (annotation,))


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


def _invalidate_dependents(project: Project, artifact_id: str) -> Project:
    direct = {
        artifact.artifact_id
        for artifact in project.artifacts
        if any(ref.artifact_id == artifact_id for ref in artifact.upstream)
    }
    return _invalidate_from(project, direct) if direct else project


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
        "annotations": [
            {"artifact": ref(a.artifact), "reviewer": a.reviewer, "comment": a.comment, "target": a.target}
            for a in project.annotations
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
        annotations = tuple(
            ReviewAnnotation(
                ArtifactRef(item["artifact"]["artifact_id"], item["artifact"]["content_hash"]),
                item["reviewer"], item["comment"], item.get("target"),
            )
            for item in payload.get("annotations", [])
        )
        project = Project(payload["project_id"], payload["name"], artifacts, approvals, annotations)
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
    logical = project.current(ArtifactKind.LOGICAL_IR)
    if logical is not None:
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        tests = project.current(ArtifactKind.TEST_SPEC)
        if elaborated is None or tests is None or logical.upstream != (elaborated.ref, tests.ref):
            raise ValueError("malformed project state: logical IR has invalid reviewed inputs")
        if not _is_approved(project, elaborated) or not _is_approved(project, tests):
            raise ValueError("malformed project state: logical IR lacks exact input approvals")
    logical_review = project.current(ArtifactKind.LOGICAL_REVIEW)
    if logical_review is not None:
        from .logical_ir import logical_ir_from_dict, logical_review_from_dict, validate_review_for_document
        import json
        if logical is None or logical_review.upstream != (logical.ref,):
            raise ValueError("malformed project state: logical review has invalid logical-IR input")
        try:
            report = logical_review_from_dict(json.loads(logical_review.content))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"malformed project state: invalid logical review: {exc}") from exc
        if report.logical_ir_hash != logical.content_hash:
            raise ValueError("malformed project state: logical review hash mismatch")
        try:
            document = logical_ir_from_dict(json.loads(logical.content))
            validate_review_for_document(report, document)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"malformed project state: logical review does not match logical IR: {exc}") from exc
    compiler_output = project.current(ArtifactKind.COMPILER_OUTPUT)
    if compiler_output is not None:
        from .compiler_output import canonical_compiler_output, compiler_output_from_dict
        import json
        if logical is None or compiler_output.upstream != (logical.ref,):
            raise ValueError("malformed project state: compiler output has invalid admitted logical-IR input")
        try:
            bundle = compiler_output_from_dict(json.loads(compiler_output.content))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"malformed project state: invalid compiler output: {exc}") from exc
        if compiler_output.content != canonical_compiler_output(bundle):
            raise ValueError("malformed project state: compiler output is not canonical")
        try:
            admitted = admit_compilation(project)
        except ValueError as exc:
            raise ValueError(f"malformed project state: compiler output lacks compile admission: {exc}") from exc
        if admitted.ref != logical.ref:
            raise ValueError("malformed project state: compiler output logical IR is not admitted")
    sandbox_handoff = project.current(ArtifactKind.SANDBOX_HANDOFF)
    if sandbox_handoff is not None:
        from .compiler_output import compiler_output_from_dict
        from .sandbox_handoff import canonical_sandbox_handoff, sandbox_handoff_from_dict
        import json
        if compiler_output is None or sandbox_handoff.upstream != (compiler_output.ref,):
            raise ValueError("malformed project state: sandbox handoff has invalid compiler-output input")
        if not _is_approved(project, compiler_output):
            raise ValueError("malformed project state: sandbox handoff lacks exact compiler-output approval")
        try:
            handoff = sandbox_handoff_from_dict(json.loads(sandbox_handoff.content))
            bundle = compiler_output_from_dict(json.loads(compiler_output.content))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"malformed project state: invalid sandbox handoff: {exc}") from exc
        if sandbox_handoff.content != canonical_sandbox_handoff(handoff):
            raise ValueError("malformed project state: sandbox handoff is not canonical")
        if handoff.files != tuple(generated.path for generated in bundle.files):
            raise ValueError("malformed project state: sandbox handoff files do not match compiler output")
    test_result = project.current(ArtifactKind.TEST_RESULT)
    if test_result is not None:
        from .sandbox_handoff import sandbox_handoff_from_dict
        from .sandbox_protocol import canonical_test_result, sandbox_request_hash, test_result_from_dict
        import json
        if sandbox_handoff is None or test_result.upstream != (sandbox_handoff.ref,):
            raise ValueError("malformed project state: test result has invalid sandbox-handoff input")
        try:
            handoff = sandbox_handoff_from_dict(json.loads(sandbox_handoff.content))
            result = test_result_from_dict(json.loads(test_result.content))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"malformed project state: invalid test result: {exc}") from exc
        if test_result.content != canonical_test_result(result):
            raise ValueError("malformed project state: test result is not canonical")
        if result.request_hash != sandbox_request_hash(handoff):
            raise ValueError("malformed project state: test result request hash mismatch")
    traceability = project.current(ArtifactKind.TRACEABILITY_REPORT)
    if traceability is not None:
        from .compiler_output import compiler_output_from_dict
        from .sandbox_protocol import test_result_from_dict
        from .traceability import (
            ProvenanceLink, build_traceability_report, canonical_traceability_report,
            traceability_report_from_dict,
        )
        import json
        if (
            compiler_output is None or test_result is None
            or traceability.upstream != (compiler_output.ref, test_result.ref)
        ):
            raise ValueError("malformed project state: traceability report has invalid inputs")
        required = tuple(
            project.current(kind) for kind in (
                ArtifactKind.ORIGINAL_SPEC, ArtifactKind.ELABORATED_SPEC, ArtifactKind.TEST_SPEC,
                ArtifactKind.LOGICAL_IR, ArtifactKind.COMPILER_OUTPUT, ArtifactKind.SANDBOX_HANDOFF,
                ArtifactKind.TEST_RESULT,
            )
        )
        if any(artifact is None for artifact in required):
            raise ValueError("malformed project state: traceability provenance chain is incomplete")
        try:
            report = traceability_report_from_dict(json.loads(traceability.content))
            bundle = compiler_output_from_dict(json.loads(compiler_output.content))
            result = test_result_from_dict(json.loads(test_result.content))
            provenance = tuple(ProvenanceLink(a.kind.value, a.artifact_id, a.content_hash) for a in required)
            expected = build_traceability_report(provenance, bundle, result)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"malformed project state: invalid traceability report: {exc}") from exc
        if report != expected or traceability.content != canonical_traceability_report(expected):
            raise ValueError("malformed project state: traceability report does not match exact inputs")
    for annotation in annotations:
        target = project.artifact(annotation.artifact.artifact_id)
        if target.content_hash != annotation.artifact.content_hash:
            raise ValueError("malformed project state: annotation hash mismatch")
        if not isinstance(annotation.reviewer, str) or not annotation.reviewer.strip():
            raise ValueError("malformed project state: annotation lacks reviewer")
        if not isinstance(annotation.comment, str) or not annotation.comment.strip():
            raise ValueError("malformed project state: annotation comment is blank")
        if annotation.target is not None and (
            not isinstance(annotation.target, str) or not annotation.target.strip()
        ):
            raise ValueError("malformed project state: annotation target is invalid")
    return project

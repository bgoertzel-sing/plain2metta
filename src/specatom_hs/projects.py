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
    ELABORATION_LOG = "elaboration-log"
    ELABORATED_SPEC = "elaborated-spec"
    TEST_SPEC = "test-spec"
    REVIEW_LOG = "review-log"
    REVIEWED_ELABORATED_SPEC = "reviewed-elaborated-spec"
    REVIEWED_TEST_SPEC = "reviewed-test-spec"
    LOGICAL_IR_LOG = "logical-ir-log"
    LOGICAL_IR = "logical-ir"
    LOGICAL_REVIEW = "logical-review"
    COMPILATION_LOG = "compilation-log"
    COMPILER_OUTPUT = "compiler-output"
    SANDBOX_HANDOFF = "sandbox-handoff"
    TEST_RESULT = "test-result"
    TRACEABILITY_REPORT = "traceability-report"
    SEMANTIC_CONTRACT = "semantic-contract"
    VALIDATION_OBLIGATION = "validation-obligation"
    VALIDATION_PLAN = "validation-plan"
    VALIDATION_PLAN_REVIEW = "validation-plan-review"
    INPUT_GENERATOR = "input-generator"
    VALIDATION_ORACLE = "validation-oracle"
    RUNTIME_EVIDENCE = "runtime-evidence"
    COUNTEREXAMPLE = "counterexample"
    VALIDATION_VERDICT = "validation-verdict"


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
    if kind is ArtifactKind.ELABORATION_LOG:
        raise ValueError("use add_admitted_elaboration to enforce validation admission")
    if kind in (ArtifactKind.REVIEW_LOG, ArtifactKind.REVIEWED_ELABORATED_SPEC, ArtifactKind.REVIEWED_TEST_SPEC):
        raise ValueError("use submit_phase3_review to enforce exact-version review admission")
    if kind in (ArtifactKind.LOGICAL_IR_LOG, ArtifactKind.LOGICAL_IR, ArtifactKind.LOGICAL_REVIEW):
        raise ValueError("use add_logical_ir or add_logical_ir_document to enforce the review gate")
    if kind in (ArtifactKind.COMPILATION_LOG, ArtifactKind.COMPILER_OUTPUT):
        raise ValueError("use the phase-specific add_compiler_output transition API")
    if kind is ArtifactKind.SANDBOX_HANDOFF:
        raise ValueError("use the phase-specific add_sandbox_handoff transition API")
    if kind is ArtifactKind.TEST_RESULT:
        raise ValueError("use the phase-specific add_test_result transition API")
    if kind is ArtifactKind.TRACEABILITY_REPORT:
        raise ValueError("use the phase-specific add_traceability_report transition API")
    if kind is ArtifactKind.VALIDATION_PLAN_REVIEW:
        raise ValueError("use add_validation_plan_review to enforce exact plan review")
    if kind in {
        ArtifactKind.SEMANTIC_CONTRACT, ArtifactKind.VALIDATION_OBLIGATION,
        ArtifactKind.VALIDATION_PLAN, ArtifactKind.INPUT_GENERATOR,
        ArtifactKind.VALIDATION_ORACLE, ArtifactKind.RUNTIME_EVIDENCE,
        ArtifactKind.COUNTEREXAMPLE, ArtifactKind.VALIDATION_VERDICT,
    }:
        raise ValueError("use add_semantic_artifact to enforce semantic ancestry")
    return _add_derived_artifact(project, kind, content, upstream)


def add_semantic_artifact(project: Project, document: object) -> Project:
    """Persist one strict Stage-1 semantic document with exact ancestry."""
    from .semantic_artifacts import canonical_semantic_artifact, validate_semantic_artifact

    kind, refs = validate_semantic_artifact(document)
    reviewed = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
    if reviewed is None or reviewed.ref not in refs:
        raise ValueError("semantic artifact must bind the exact current reviewed source")
    for ref in refs:
        target = project.artifact(ref.artifact_id)
        if target.ref != ref or target.state is not ArtifactState.CURRENT:
            raise ValueError("semantic artifact reference is stale or hash-mismatched")
    return _add_derived_artifact(project, kind, canonical_semantic_artifact(document), refs)


def add_validation_plan_review(project: Project, content: str, plan_ref: ArtifactRef) -> Project:
    """Persist a strict review record only for the exact current plan."""
    plan = project.current(ArtifactKind.VALIDATION_PLAN)
    if plan is None or plan.ref != plan_ref:
        raise ValueError("validation-plan review requires the exact current plan")
    return _add_derived_artifact(
        project, ArtifactKind.VALIDATION_PLAN_REVIEW, content, (plan.ref,),
    )


def add_admitted_elaboration(project: Project, request: object, response: object, admission: object) -> Project:
    """Atomically construct the admitted Phase 2 interaction and both outputs."""
    from .elaboration_protocol import (
        elaboration_admission_to_dict,
        elaboration_request_hash,
        elaboration_request_to_dict,
        elaboration_response_hash,
        elaboration_response_to_dict,
        validate_elaboration_admission,
        validate_elaboration_request,
        validate_elaboration_response,
    )
    import json

    validate_elaboration_request(request)
    validate_elaboration_response(response, request)
    validate_elaboration_admission(admission)
    source = project.current(ArtifactKind.ORIGINAL_SPEC)
    if source is None or request.source != source.ref:
        raise ValueError("elaboration requires the exact current original spec")
    if admission.request_hash != elaboration_request_hash(request):
        raise ValueError("admission does not bind to the exact request")
    if admission.response_hash != elaboration_response_hash(response):
        raise ValueError("admission does not bind to the exact response")
    if not admission.admitted:
        raise ValueError("elaboration response did not pass validation admission")
    log_content = json.dumps({
        "schema": "plain2metta-elaboration-log/v1",
        "request": elaboration_request_to_dict(request),
        "response": elaboration_response_to_dict(response),
        "admission": elaboration_admission_to_dict(admission),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    project = _add_derived_artifact(project, ArtifactKind.ELABORATION_LOG, log_content, (source.ref,))
    log = project.current(ArtifactKind.ELABORATION_LOG)
    project = _add_derived_artifact(
        project, ArtifactKind.ELABORATED_SPEC, response.elaborated_spec, (source.ref, log.ref),
    )
    elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
    return _add_derived_artifact(
        project, ArtifactKind.TEST_SPEC, response.test_spec, (elaborated.ref, log.ref),
    )


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
    # Evidence is an append-only set: independent runtimes and tools must be
    # composable without one run invalidating an unrelated run.  Upstream
    # invalidation still walks every evidence artifact transitively.
    if previous is not None and kind is not ArtifactKind.RUNTIME_EVIDENCE:
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
    """Add a logical IR only from the exact current Phase 3 reviewed snapshots."""
    reviewed_elaborated = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
    reviewed_tests = project.current(ArtifactKind.REVIEWED_TEST_SPEC)
    if reviewed_elaborated is None or reviewed_tests is None:
        raise ValueError("logical IR requires exact current reviewed elaborated and test snapshots")
    return _add_derived_artifact(
        project, ArtifactKind.LOGICAL_IR, content,
        (reviewed_elaborated.ref, reviewed_tests.ref),
    )


def submit_phase3_review(project: Project, decisions: object) -> Project:
    """Persist exact-version Phase 3 decisions and approved reviewed snapshots."""
    from .phase3_review import canonical_phase3_review_log, validate_phase3_review_log

    elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
    tests = project.current(ArtifactKind.TEST_SPEC)
    if elaborated is None or tests is None:
        raise ValueError("Phase 3 review requires current elaborated and test specs")
    validate_phase3_review_log(decisions, elaborated.ref, tests.ref)
    project = _add_derived_artifact(
        project, ArtifactKind.REVIEW_LOG, canonical_phase3_review_log(decisions),
        (elaborated.ref, tests.ref),
    )
    for entry in decisions.decisions:
        if entry.target is None:
            project = decide(
                project, entry.artifact, entry.decision, entry.reviewer, entry.comment,
            )
        if entry.comment:
            project = annotate(
                project, entry.artifact, entry.reviewer, entry.comment, entry.target,
            )
    if not (_is_approved(project, elaborated) and _is_approved(project, tests)):
        return project
    review_log = project.current(ArtifactKind.REVIEW_LOG)
    reviewed_elaborated_content = decisions.reviewed_elaborated_spec
    reviewed_test_content = decisions.reviewed_test_spec
    if reviewed_elaborated_content is None:
        reviewed_elaborated_content = elaborated.content
        reviewed_test_content = tests.content
    project = _add_derived_artifact(
        project, ArtifactKind.REVIEWED_ELABORATED_SPEC, reviewed_elaborated_content,
        (elaborated.ref, review_log.ref),
    )
    return _add_derived_artifact(
        project, ArtifactKind.REVIEWED_TEST_SPEC, reviewed_test_content,
        (tests.ref, review_log.ref),
    )


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


def add_logical_ir_response(project: Project, request: object, response: object) -> Project:
    """Atomically construct the Phase 4 interaction log, logical IR, and review."""
    from .logical_ir import logical_ir_hash
    from .logical_ir_prompt import (
        LogicalIRRequest, LogicalIRResponse, logical_ir_request_hash,
        logical_ir_request_to_dict,
    )
    import json

    reviewed_spec = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
    reviewed_tests = project.current(ArtifactKind.REVIEWED_TEST_SPEC)
    if not isinstance(request, LogicalIRRequest) or not isinstance(response, LogicalIRResponse):
        raise ValueError("logical IR admission requires exact request and response messages")
    if (
        reviewed_spec is None or reviewed_tests is None
        or request.reviewed_spec != reviewed_spec.ref
        or request.reviewed_tests != reviewed_tests.ref
        or request.reviewed_spec_text != reviewed_spec.content
        or request.reviewed_tests_text != reviewed_tests.content
        or response.request_hash != logical_ir_request_hash(request)
    ):
        raise ValueError("logical IR response does not bind to exact current reviewed snapshots")
    provenance = response.provenance
    log = {
        "schema": "plain2metta-logical-ir-log/v1",
        "request": logical_ir_request_to_dict(request),
        "request_hash": response.request_hash,
        "logical_ir_hash": logical_ir_hash(response.logical_ir),
        "provenance": {
            "backend": provenance.backend, "model": provenance.model,
            "interaction_id": provenance.interaction_id,
            "input_tokens": provenance.input_tokens,
            "output_tokens": provenance.output_tokens,
            "timestamp": provenance.timestamp,
        },
    }
    content = json.dumps(log, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    project = _add_derived_artifact(
        project, ArtifactKind.LOGICAL_IR_LOG, content,
        (reviewed_spec.ref, reviewed_tests.ref),
    )
    return add_logical_ir_document(project, response.logical_ir)


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


def add_compilation_response(project: Project, request: object, response: object) -> Project:
    """Atomically construct the Phase 5 interaction log and inert output."""
    from .compilation_prompt import (
        CompilationRequest, CompilationResponse, build_compilation_request,
        compilation_request_hash, compilation_request_to_dict,
    )
    from .compiler_output import canonical_compiler_output
    import json

    if not isinstance(request, CompilationRequest) or not isinstance(response, CompilationResponse):
        raise ValueError("compilation admission requires exact request and response messages")
    expected = build_compilation_request(project, request.guidance)
    if expected != request or response.request_hash != compilation_request_hash(request):
        raise ValueError("compilation response does not bind to exact current approved inputs")
    provenance = response.provenance
    output_content = canonical_compiler_output(response.compiler_output)
    log_content = json.dumps({
        "schema": "plain2metta-compilation-log/v1",
        "request": compilation_request_to_dict(request),
        "request_hash": response.request_hash,
        "compiler_output_hash": content_sha256(output_content),
        "provenance": {
            "backend": provenance.backend, "model": provenance.model,
            "interaction_id": provenance.interaction_id,
            "input_tokens": provenance.input_tokens,
            "output_tokens": provenance.output_tokens,
            "timestamp": provenance.timestamp,
        },
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    project = _add_derived_artifact(
        project, ArtifactKind.COMPILATION_LOG, log_content,
        (request.reviewed_spec, request.reviewed_tests, request.logical_ir),
    )
    return add_compiler_output(project, response.compiler_output)


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
            ArtifactKind.REVIEWED_ELABORATED_SPEC, ArtifactKind.REVIEWED_TEST_SPEC,
            ArtifactKind.LOGICAL_IR, ArtifactKind.COMPILER_OUTPUT, ArtifactKind.SANDBOX_HANDOFF,
            ArtifactKind.TEST_RESULT,
        )
    )
    if any(artifact is None for artifact in required):
        raise ValueError("traceability report requires the exact complete current provenance chain")
    original, elaborated, tests, reviewed_elaborated, reviewed_tests, logical, output, handoff, result_artifact = required
    expected_links = (
        (elaborated, (original.ref,)),
        (tests, (elaborated.ref,)),
        (logical, (reviewed_elaborated.ref, reviewed_tests.ref)),
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
    semantic_kinds = {
        ArtifactKind.SEMANTIC_CONTRACT, ArtifactKind.VALIDATION_OBLIGATION,
        ArtifactKind.VALIDATION_PLAN, ArtifactKind.INPUT_GENERATOR,
        ArtifactKind.VALIDATION_ORACLE, ArtifactKind.RUNTIME_EVIDENCE,
        ArtifactKind.COUNTEREXAMPLE, ArtifactKind.VALIDATION_VERDICT,
    }
    from .semantic_artifacts import semantic_artifact_from_dict, validate_semantic_artifact
    import json
    for artifact in artifacts:
        if artifact.kind not in semantic_kinds:
            continue
        try:
            document = semantic_artifact_from_dict(json.loads(artifact.content))
            kind, refs = validate_semantic_artifact(document)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"malformed project state: invalid semantic artifact: {exc}") from exc
        if kind is not artifact.kind or refs != artifact.upstream:
            raise ValueError("malformed project state: semantic artifact envelope does not match stored ancestry")
    try:
        from .validation_plan import validate_plan_review_chain
        validate_plan_review_chain(project)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"malformed project state: invalid validation-plan review: {exc}") from exc
    elaboration_log = project.current(ArtifactKind.ELABORATION_LOG)
    if elaboration_log is not None:
        from .elaboration_protocol import (
            elaboration_admission_from_dict,
            elaboration_request_from_dict,
            elaboration_response_from_dict,
        )
        import json
        original = project.current(ArtifactKind.ORIGINAL_SPEC)
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        tests = project.current(ArtifactKind.TEST_SPEC)
        try:
            payload = json.loads(elaboration_log.content)
            if not isinstance(payload, dict) or set(payload) != {"schema", "request", "response", "admission"}:
                raise ValueError("interaction log has unknown or missing fields")
            if payload["schema"] != "plain2metta-elaboration-log/v1":
                raise ValueError("unsupported interaction-log schema")
            request = elaboration_request_from_dict(payload["request"])
            response = elaboration_response_from_dict(payload["response"])
            admission = elaboration_admission_from_dict(payload["admission"])
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"malformed project state: invalid elaboration log: {exc}") from exc
        if (
            original is None or elaborated is None or tests is None
            or elaboration_log.upstream != (original.ref,)
            or request.source != original.ref
            or elaborated.upstream != (original.ref, elaboration_log.ref)
            or tests.upstream != (elaborated.ref, elaboration_log.ref)
            or response.elaborated_spec != elaborated.content
            or response.test_spec != tests.content
            or not admission.admitted
        ):
            raise ValueError("malformed project state: elaboration chain does not match admitted interaction")
        try:
            add_admitted_elaboration(
                Project(project.project_id, project.name, (original,)), request, response, admission,
            )
        except ValueError as exc:
            raise ValueError(f"malformed project state: forged elaboration admission: {exc}") from exc
        from .elaboration_admission import validate_elaboration_outputs
        elaborated_validation, test_validation = validate_elaboration_outputs(
            response.elaborated_spec, response.test_spec, project.project_id,
        )
        if (
            elaborated_validation != admission.elaborated_validation
            or test_validation != admission.test_validation
        ):
            raise ValueError("malformed project state: elaboration validation evidence is forged")
    review_log = project.current(ArtifactKind.REVIEW_LOG)
    reviewed_elaborated = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
    reviewed_tests = project.current(ArtifactKind.REVIEWED_TEST_SPEC)
    if review_log is not None:
        from .phase3_review import phase3_review_log_from_dict, validate_phase3_review_log
        import json
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        tests = project.current(ArtifactKind.TEST_SPEC)
        if elaborated is None or tests is None or review_log.upstream != (elaborated.ref, tests.ref):
            raise ValueError("malformed project state: Phase 3 review log has invalid inputs")
        try:
            phase3_log = phase3_review_log_from_dict(json.loads(review_log.content))
            validate_phase3_review_log(phase3_log, elaborated.ref, tests.ref)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"malformed project state: invalid Phase 3 review log: {exc}") from exc
    if (reviewed_elaborated is None) != (reviewed_tests is None):
        raise ValueError("malformed project state: reviewed spec snapshots must be an exact pair")
    if reviewed_elaborated is not None:
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        tests = project.current(ArtifactKind.TEST_SPEC)
        if (
            review_log is None or elaborated is None or tests is None
            or reviewed_elaborated.upstream != (elaborated.ref, review_log.ref)
            or reviewed_tests.upstream != (tests.ref, review_log.ref)
            or reviewed_elaborated.content != (
                phase3_log.reviewed_elaborated_spec
                if phase3_log.reviewed_elaborated_spec is not None else elaborated.content
            )
            or reviewed_tests.content != (
                phase3_log.reviewed_test_spec
                if phase3_log.reviewed_test_spec is not None else tests.content
            )
            or not _is_approved(project, elaborated) or not _is_approved(project, tests)
        ):
            raise ValueError("malformed project state: reviewed snapshots do not match exact approved inputs")
    logical = project.current(ArtifactKind.LOGICAL_IR)
    logical_log = project.current(ArtifactKind.LOGICAL_IR_LOG)
    if logical_log is not None:
        from .logical_ir_prompt import LogicalIRRequest, logical_ir_request_hash, logical_ir_request_to_dict
        import json
        reviewed_elaborated = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
        reviewed_tests = project.current(ArtifactKind.REVIEWED_TEST_SPEC)
        try:
            value = json.loads(logical_log.content)
            if not isinstance(value, dict) or set(value) != {"schema", "request", "request_hash", "logical_ir_hash", "provenance"}:
                raise ValueError("invalid logical-IR interaction fields")
            if value["schema"] != "plain2metta-logical-ir-log/v1":
                raise ValueError("unsupported logical-IR interaction schema")
            raw = value["request"]
            if not isinstance(raw, dict) or set(raw) != {"schema", "reviewed_spec", "reviewed_spec_text", "reviewed_tests", "reviewed_tests_text", "guidance"}:
                raise ValueError("invalid logical-IR request")
            spec_ref = ArtifactRef(raw["reviewed_spec"]["artifact_id"], raw["reviewed_spec"]["content_hash"])
            test_ref = ArtifactRef(raw["reviewed_tests"]["artifact_id"], raw["reviewed_tests"]["content_hash"])
            request = LogicalIRRequest(spec_ref, raw["reviewed_spec_text"], test_ref, raw["reviewed_tests_text"], raw["guidance"])
            if logical_ir_request_to_dict(request) != raw or logical_ir_request_hash(request) != value["request_hash"]:
                raise ValueError("logical-IR request binding mismatch")
            provenance = value["provenance"]
            if not isinstance(provenance, dict) or set(provenance) != {"backend", "model", "interaction_id", "input_tokens", "output_tokens", "timestamp"}:
                raise ValueError("invalid logical-IR provenance")
            if any(not isinstance(provenance[x], str) or not provenance[x].strip() for x in ("backend", "model", "interaction_id", "timestamp")):
                raise ValueError("invalid logical-IR provenance text")
            if any(not isinstance(provenance[x], int) or isinstance(provenance[x], bool) or provenance[x] < 0 for x in ("input_tokens", "output_tokens")):
                raise ValueError("invalid logical-IR token counts")
        except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"malformed project state: invalid logical-IR interaction log: {exc}") from exc
        if (
            logical is None or reviewed_elaborated is None or reviewed_tests is None
            or logical_log.upstream != (reviewed_elaborated.ref, reviewed_tests.ref)
            or request.reviewed_spec != reviewed_elaborated.ref
            or request.reviewed_tests != reviewed_tests.ref
        ):
            raise ValueError("malformed project state: logical-IR log has invalid reviewed inputs")
    if logical is not None:
        reviewed_elaborated = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
        reviewed_tests = project.current(ArtifactKind.REVIEWED_TEST_SPEC)
        if (
            reviewed_elaborated is None or reviewed_tests is None
            or logical.upstream != (reviewed_elaborated.ref, reviewed_tests.ref)
        ):
            raise ValueError("malformed project state: logical IR has invalid reviewed inputs")
        if logical_log is not None and value["logical_ir_hash"] != logical.content_hash:
            raise ValueError("malformed project state: logical-IR log does not match logical IR")
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
    compilation_log = project.current(ArtifactKind.COMPILATION_LOG)
    compiler_output = project.current(ArtifactKind.COMPILER_OUTPUT)
    if compilation_log is not None and compiler_output is None:
        raise ValueError("malformed project state: compilation log lacks compiler output")
    if compilation_log is not None:
        from .compilation_prompt import (
            CompilationRequest, compilation_request_hash, compilation_request_to_dict,
        )
        import json
        reviewed_spec = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
        reviewed_tests = project.current(ArtifactKind.REVIEWED_TEST_SPEC)
        try:
            value = json.loads(compilation_log.content)
            if not isinstance(value, dict) or set(value) != {"schema", "request", "request_hash", "compiler_output_hash", "provenance"}:
                raise ValueError("invalid compilation interaction fields")
            if value["schema"] != "plain2metta-compilation-log/v1":
                raise ValueError("unsupported compilation interaction schema")
            raw = value["request"]
            required = {"schema", "reviewed_spec", "reviewed_spec_text", "reviewed_tests", "reviewed_tests_text", "logical_ir", "logical_ir_text", "guidance"}
            if not isinstance(raw, dict) or set(raw) != required:
                raise ValueError("invalid compilation request")
            spec_ref = ArtifactRef(raw["reviewed_spec"]["artifact_id"], raw["reviewed_spec"]["content_hash"])
            test_ref = ArtifactRef(raw["reviewed_tests"]["artifact_id"], raw["reviewed_tests"]["content_hash"])
            logical_ref = ArtifactRef(raw["logical_ir"]["artifact_id"], raw["logical_ir"]["content_hash"])
            request = CompilationRequest(
                spec_ref, raw["reviewed_spec_text"], test_ref, raw["reviewed_tests_text"],
                logical_ref, raw["logical_ir_text"], raw["guidance"],
            )
            if compilation_request_to_dict(request) != raw or compilation_request_hash(request) != value["request_hash"]:
                raise ValueError("compilation request binding mismatch")
            provenance = value["provenance"]
            if not isinstance(provenance, dict) or set(provenance) != {"backend", "model", "interaction_id", "input_tokens", "output_tokens", "timestamp"}:
                raise ValueError("invalid compilation provenance")
            if any(not isinstance(provenance[x], str) or not provenance[x].strip() for x in ("backend", "model", "interaction_id", "timestamp")):
                raise ValueError("invalid compilation provenance text")
            if any(not isinstance(provenance[x], int) or isinstance(provenance[x], bool) or provenance[x] < 0 for x in ("input_tokens", "output_tokens")):
                raise ValueError("invalid compilation token counts")
        except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"malformed project state: invalid compilation interaction log: {exc}") from exc
        if (
            logical is None or reviewed_spec is None or reviewed_tests is None
            or compilation_log.upstream != (reviewed_spec.ref, reviewed_tests.ref, logical.ref)
            or request.reviewed_spec != reviewed_spec.ref
            or request.reviewed_tests != reviewed_tests.ref
            or request.logical_ir != logical.ref
        ):
            raise ValueError("malformed project state: compilation log has invalid approved inputs")
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
        if compilation_log is not None and value["compiler_output_hash"] != compiler_output.content_hash:
            raise ValueError("malformed project state: compilation log does not match compiler output")
        if compilation_log is not None and (
            bundle.compiler != f'{provenance["backend"]}:{provenance["model"]}'
            or bundle.guidance != (request.guidance or None)
        ):
            raise ValueError("malformed project state: compiler output attribution does not match compilation log")
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
                ArtifactKind.REVIEWED_ELABORATED_SPEC, ArtifactKind.REVIEWED_TEST_SPEC,
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

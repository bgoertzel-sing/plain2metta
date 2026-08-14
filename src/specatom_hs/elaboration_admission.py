"""Adapter-independent validation and persistence for Phase 2 responses."""

from __future__ import annotations

from typing import Callable

from .elaboration_protocol import (
    ElaborationRequest,
    ElaborationResponse,
    ValidationSummary,
    admit_elaboration,
)
from .projects import ArtifactKind, Project, add_admitted_elaboration
from .schema import CheckStatus, Role, SpecDocument
from .passes import compile_source


Validator = Callable[[str, str, str], tuple[ValidationSummary, ValidationSummary]]


def validation_summary(document: SpecDocument) -> ValidationSummary:
    if not isinstance(document, SpecDocument):
        raise ValueError("validator must return a SpecDocument")
    counts = {status: 0 for status in CheckStatus}
    for check in document.checks:
        counts[check.status] += 1
    blocking = sum(
        obj.role is Role.QUESTION_OBJECT and any(fact and fact[0] == "Blocks" for fact in obj.facts)
        for obj in document.objects
    )
    return ValidationSummary(
        counts[CheckStatus.PASS], counts[CheckStatus.FAIL], counts[CheckStatus.UNKNOWN], blocking,
    )


def validate_elaboration_outputs(
    elaborated_spec: str, test_spec: str, project_id: str,
) -> tuple[ValidationSummary, ValidationSummary]:
    """Run the existing compiler over the complete Phase 2 review corpus."""
    combined = f"{elaborated_spec.rstrip()}\n\n{test_spec.lstrip()}"
    summary = validation_summary(compile_source(combined, f"{project_id}.phase2.plain"))
    return summary, summary


class ElaborationAdmissionService:
    """Validate returned text and persist one all-or-nothing project transition."""

    def __init__(self, repository, validator: Validator = validate_elaboration_outputs):
        self._repository = repository
        self._validator = validator

    def admit_and_persist(
        self, project_id: str, request: ElaborationRequest, response: ElaborationResponse,
    ) -> Project:
        project = self._repository.get(project_id)
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        if source is None or request.source != source.ref:
            raise ValueError("elaboration requires the exact current original spec")
        elaborated, tests = self._validator(response.elaborated_spec, response.test_spec, project_id)
        admission = admit_elaboration(
            request, response, elaborated, tests,
        )
        updated = add_admitted_elaboration(project, request, response, admission)
        self._repository.save(updated)
        return updated

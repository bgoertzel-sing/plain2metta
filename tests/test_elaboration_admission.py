import json
import tempfile
import unittest
from pathlib import Path

from specatom_hs.elaboration_admission import (
    ElaborationAdmissionService, ElaborationRequestService, validation_summary,
)
from specatom_hs.elaboration_protocol import (
    ElaborationRequest, ElaborationResponse, ProviderProvenance, elaboration_request_hash,
)
from specatom_hs.project_repository import FilesystemProjectRepository
from specatom_hs.projects import ArtifactKind, project_to_dict
from specatom_hs.schema import CheckRecord, CheckStatus, Role, SpecDocument, SpecObject, SemanticLevel


def document(*, status=CheckStatus.PASS, blocked=False):
    objects = []
    if blocked:
        objects.append(SpecObject("q", Role.QUESTION_OBJECT, SemanticLevel.TEMPLATE_PARSED, facts=[("Blocks", "q", "o")]))
    return SpecDocument(
        objects=objects,
        checks=[CheckRecord("c", "o", "p", "t", status, "evidence")],
    )


class ElaborationAdmissionServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repository = FilesystemProjectRepository(Path(self.temp.name) / "projects")
        project = self.repository.create(
            "demo", "Demo", "***notes***\n",
        )
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        self.request = ElaborationRequest(source.ref, source.content, "Reviewable English only.")
        self.response = ElaborationResponse(
            elaboration_request_hash(self.request),
            "***requirements***\n",
            "***acceptance tests***\n",
            ProviderProvenance("adapter", "model", "interaction-1", 10, 20, "2026-08-14T10:41:00Z"),
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_admitted_response_and_log_are_persisted_in_one_state_write(self):
        service = ElaborationAdmissionService(self.repository)
        updated = service.admit_and_persist("demo", self.request, self.response)
        stored = self.repository.get("demo")
        self.assertEqual(updated, stored)
        log = stored.current(ArtifactKind.ELABORATION_LOG)
        elaborated = stored.current(ArtifactKind.ELABORATED_SPEC)
        tests = stored.current(ArtifactKind.TEST_SPEC)
        self.assertEqual((self.request.source,), log.upstream)
        self.assertEqual((self.request.source, log.ref), elaborated.upstream)
        self.assertEqual((elaborated.ref, log.ref), tests.upstream)
        self.assertEqual("interaction-1", json.loads(log.content)["response"]["provenance"]["interaction_id"])

    def test_rejection_and_stale_request_leave_repository_unchanged(self):
        before = self.repository.get("demo")
        for validator in (
            lambda elaborated, tests, project_id: (
                validation_summary(document(status=CheckStatus.FAIL)), validation_summary(document())
            ),
            lambda elaborated, tests, project_id: (
                validation_summary(document(blocked=True)), validation_summary(document())
            ),
        ):
            with self.subTest(validator=validator), self.assertRaises(ValueError):
                ElaborationAdmissionService(self.repository, validator).admit_and_persist(
                    "demo", self.request, self.response,
                )
            self.assertEqual(before, self.repository.get("demo"))
        stale = ElaborationRequest(type(self.request.source)("missing", self.request.source.content_hash), self.request.source_text)
        with self.assertRaises(ValueError):
            ElaborationAdmissionService(self.repository, lambda elaborated, tests, project_id: (
                validation_summary(document()), validation_summary(document())
            )).admit_and_persist(
                "demo", stale, self.response,
            )
        self.assertEqual(before, self.repository.get("demo"))

    def test_forged_persisted_log_fails_closed(self):
        service = ElaborationAdmissionService(self.repository)
        updated = service.admit_and_persist("demo", self.request, self.response)
        data = project_to_dict(updated)
        log = next(item for item in data["artifacts"] if item["kind"] == "elaboration-log")
        payload = json.loads(log["content"])
        payload["response"]["provenance"]["interaction_id"] = "forged"
        log["content"] = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        from specatom_hs.projects import content_sha256, project_from_dict
        log["content_hash"] = content_sha256(log["content"])
        with self.assertRaises(ValueError):
            project_from_dict(data)

    def test_existing_compiler_summary_counts_failures_and_blockers(self):
        summary = validation_summary(document(status=CheckStatus.UNKNOWN, blocked=True))
        self.assertEqual((0, 0, 1, 1), (
            summary.pass_count, summary.fail_count, summary.unknown_count, summary.blocking_questions,
        ))

    def test_request_builder_exports_exact_current_source_and_guidance(self):
        request = ElaborationRequestService(self.repository).build_request(
            "demo", "Use only named dependencies.", "requirements",
        )
        source = self.repository.get("demo").current(ArtifactKind.ORIGINAL_SPEC)
        self.assertEqual(source.ref, request.source)
        self.assertEqual(source.content, request.source_text)
        self.assertEqual("Use only named dependencies.", request.guidance)
        self.assertEqual("requirements", request.section)
        self.assertEqual(request, ElaborationRequest(
            source.ref, source.content, "Use only named dependencies.", "requirements",
        ))

    def test_request_builder_tracks_source_replacement_and_rejects_bad_options(self):
        from specatom_hs.projects import replace_source
        old = ElaborationRequestService(self.repository).build_request("demo")
        changed = replace_source(self.repository.get("demo"), "***requirements***\n- changed\n")
        self.repository.save(changed)
        current = ElaborationRequestService(self.repository).build_request("demo")
        self.assertNotEqual(old.source, current.source)
        self.assertEqual(changed.current(ArtifactKind.ORIGINAL_SPEC).ref, current.source)
        with self.assertRaises(ValueError):
            ElaborationRequestService(self.repository).build_request("demo", section="")
        with self.assertRaises(ValueError):
            ElaborationRequestService(self.repository).build_request("demo", guidance=None)

    def test_request_builder_has_no_mutation_or_provider_capability(self):
        service = ElaborationRequestService(self.repository)
        before = self.repository.get("demo")
        service.build_request("demo")
        self.assertEqual(before, self.repository.get("demo"))
        for name in ("invoke", "call", "retry", "save", "persist", "execute"):
            self.assertFalse(hasattr(service, name))


if __name__ == "__main__":
    unittest.main()

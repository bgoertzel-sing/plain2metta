import io
import json
import tempfile
import unittest
from pathlib import Path

from specatom_hs.project_commands import ProjectCommandService
from specatom_hs.project_queries import ProjectQueryService
from specatom_hs.project_repository import FilesystemProjectRepository
from specatom_hs.project_transport import ProjectCommandApplication, ReadOnlyProjectApplication
from specatom_hs.phase3_review import Phase3Decision, Phase3ReviewLog, phase3_review_log_to_dict
from specatom_hs.elaboration_protocol import ProviderProvenance
from specatom_hs.logical_ir import (
    Contract, FindingDisposition, LogicalIRDocument, RequirementObligation,
    TypeDeclaration, logical_ir_to_dict,
)
from specatom_hs.logical_ir_backend import LogicalIRBackendConfig, LogicalIRCoordinator
from specatom_hs.logical_ir_prompt import ProviderCompletion, RESPONSE_SCHEMA
from specatom_hs.projects import (
    ApprovalDecision, ArtifactKind, add_artifact, replace_source, submit_phase3_review,
)

import tests.test_projects as project_fixtures


class ReadOnlyProjectApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        repository = FilesystemProjectRepository(Path(self.temporary.name) / "projects")
        self.repository = repository
        project = project_fixtures.ProjectModelTests().traceability_project()
        repository.create("demo", "Demo", "placeholder")
        repository.save(project_fixtures.add_traceability_report(project))
        review_project = repository.create("reviewed", "Reviewed", "sketch\n")
        source = review_project.current(ArtifactKind.ORIGINAL_SPEC)
        review_project = add_artifact(review_project, ArtifactKind.ELABORATED_SPEC, "detailed\n", (source.ref,))
        elaborated = review_project.current(ArtifactKind.ELABORATED_SPEC)
        review_project = add_artifact(review_project, ArtifactKind.TEST_SPEC, "verify\n", (elaborated.ref,))
        tests = review_project.current(ArtifactKind.TEST_SPEC)
        review_project = submit_phase3_review(review_project, Phase3ReviewLog(
            elaborated.ref, tests.ref, (
                Phase3Decision(elaborated.ref, ApprovalDecision.APPROVED, "reviewer", "2026-08-14T12:43:00Z"),
                Phase3Decision(tests.ref, ApprovalDecision.APPROVED, "reviewer", "2026-08-14T12:43:01Z"),
            ),
        ))
        repository.save(review_project)
        self.app = ReadOnlyProjectApplication(ProjectQueryService(repository))

    def tearDown(self):
        self.temporary.cleanup()

    def request(self, path, query="", method="GET"):
        response = {}

        def start_response(status, headers):
            response["status"] = status
            response["headers"] = dict(headers)

        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "wsgi.input": io.BytesIO(),
        }
        body = b"".join(self.app(environ, start_response))
        response["body"] = json.loads(body)
        return response

    def test_exact_get_routes_return_json_ready_read_models(self):
        projects = self.request("/api/projects")
        self.assertEqual("200 OK", projects["status"])
        self.assertEqual("demo", projects["body"]["projects"][0]["project_id"])
        self.assertEqual("demo", self.request("/api/projects/demo")["body"]["project_id"])
        versions = self.request("/api/versions/demo")["body"]
        self.assertEqual("demo", versions["project_id"])
        self.assertTrue(versions["versions"])
        self.assertTrue(all("content" not in item for item in versions["versions"]))
        trace = self.request("/api/trace/demo")["body"]
        spec_id = trace["entries"][0]["spec_id"]
        filtered = self.request("/api/trace/demo", f"spec_id={spec_id}")["body"]
        self.assertEqual([spec_id], [entry["spec_id"] for entry in filtered["entries"]])
        review = self.request("/api/review/demo")["body"]
        self.assertEqual("plain2metta-phase3-review-diff/v1", review["schema"])
        self.assertEqual(
            ["elaborated_spec", "original_spec", "test_spec"],
            sorted(review["inputs"]),
        )
        self.assertTrue(all("content" not in item for item in review["inputs"].values()))
        decisions = self.request("/api/review-decisions/reviewed")["body"]
        self.assertEqual("plain2metta-phase3-review-log/v2", decisions["review_log"]["schema"])
        self.assertEqual(2, len(decisions["review_log"]["decisions"]))
        self.assertNotIn("content", decisions)

    def test_transport_has_no_mutation_or_server_capability(self):
        self.assertFalse(hasattr(self.app, "run"))
        response = self.request("/api/projects", method="POST")
        self.assertEqual("405 Method Not Allowed", response["status"])
        self.assertEqual("GET", response["headers"]["Allow"])

    def test_review_route_recomputes_and_rejects_stale_artifact_chain(self):
        before = self.request("/api/review/demo")
        self.assertEqual("200 OK", before["status"])
        self.repository.save(replace_source(self.repository.get("demo"), "changed\n"))
        stale = self.request("/api/review/demo")
        self.assertEqual("400 Bad Request", stale["status"])
        self.assertEqual("invalid_request", stale["body"]["error"])

    def test_unknown_routes_projects_and_spec_ids_are_not_found(self):
        for path, query in (("/api/unknown/demo", ""), ("/api/projects/missing", ""),
                            ("/api/review/missing", ""), ("/api/review-decisions/missing", ""),
                            ("/api/trace/demo", "spec_id=missing")):
            with self.subTest(path=path, query=query):
                response = self.request(path, query)
                self.assertEqual("404 Not Found", response["status"])
                self.assertEqual({"error": "not_found"}, response["body"])

    def test_malformed_and_ambiguous_requests_fail_closed(self):
        cases = (
            ("/api/projects/../escape", ""),
            ("/api/projects/%2e%2e%2fescape", ""),
            ("/api/projects/demo/extra", ""),
            ("/api/projects", "unexpected=1"),
            ("/api/review/demo", "unexpected=1"),
            ("/api/review-decisions/reviewed", "unexpected=1"),
            ("/api/review/demo", "broken"),
            ("/api/trace/demo", "spec_id="),
            ("/api/trace/demo", "spec_id=REQ-1&spec_id=REQ-2"),
            ("/api/trace/demo", "broken"),
        )
        for path, query in cases:
            with self.subTest(path=path, query=query):
                self.assertNotEqual("200 OK", self.request(path, query)["status"])


class ProjectCommandApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = FilesystemProjectRepository(Path(self.temporary.name) / "projects")
        self.app = ProjectCommandApplication(ProjectCommandService(self.repository))

    def tearDown(self):
        self.temporary.cleanup()

    def request(self, path, payload=None, *, method="POST", content_type="application/json",
                raw_body=None, content_length=None, query="", transfer_encoding=None):
        response = {}

        def start_response(status, headers):
            response["status"] = status
            response["headers"] = dict(headers)

        body = raw_body if raw_body is not None else json.dumps(payload).encode("utf-8")
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "CONTENT_TYPE": content_type,
            "CONTENT_LENGTH": str(len(body)) if content_length is None else content_length,
            "wsgi.input": io.BytesIO(body),
        }
        if transfer_encoding is not None:
            environ["HTTP_TRANSFER_ENCODING"] = transfer_encoding
        response["body"] = json.loads(b"".join(self.app(environ, start_response)))
        return response

    def test_create_annotate_and_decide_exact_artifact(self):
        created = self.request("/api/projects", {"project_id": "demo", "name": "Demo", "source": "source"})
        self.assertEqual("201 Created", created["status"])
        source = self.repository.get("demo").current(project_fixtures.ArtifactKind.ORIGINAL_SPEC)
        annotation = self.request("/api/projects/demo/annotations", {
            "artifact_id": source.artifact_id, "content_hash": source.content_hash,
            "reviewer": "reviewer", "comment": "Clarify.", "target": "item:REQ-1",
        })
        self.assertEqual("200 OK", annotation["status"])
        decision = self.request("/api/projects/demo/decisions", {
            "artifact_id": source.artifact_id, "content_hash": source.content_hash,
            "decision": "approved", "reviewer": "reviewer", "rationale": "Exact bytes reviewed.",
        })
        self.assertEqual("200 OK", decision["status"])
        self.assertEqual(1, len(self.repository.get("demo").annotations))
        self.assertEqual(1, len(self.repository.get("demo").approvals))

    def test_submit_elaborated_and_test_specs_with_exact_upstreams(self):
        self.request("/api/projects", {"project_id": "demo", "name": "Demo", "source": "source"})
        source = self.repository.get("demo").current(project_fixtures.ArtifactKind.ORIGINAL_SPEC)
        elaborated_response = self.request("/api/projects/demo/elaborated-spec", {
            "upstream_artifact_id": source.artifact_id,
            "upstream_content_hash": source.content_hash,
            "content": "elaborated",
        })
        self.assertEqual("200 OK", elaborated_response["status"])
        elaborated = self.repository.get("demo").current(project_fixtures.ArtifactKind.ELABORATED_SPEC)
        test_response = self.request("/api/projects/demo/test-spec", {
            "upstream_artifact_id": elaborated.artifact_id,
            "upstream_content_hash": elaborated.content_hash,
            "content": "tests",
        })
        self.assertEqual("200 OK", test_response["status"])
        self.assertEqual(
            (elaborated.ref,),
            self.repository.get("demo").current(project_fixtures.ArtifactKind.TEST_SPEC).upstream,
        )

    def phase3_project_and_payload(self):
        self.repository.create("review-demo", "Review Demo", "source")
        project = self.repository.get("review-demo")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "elaborated", (source.ref,))
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = add_artifact(project, ArtifactKind.TEST_SPEC, "tests", (elaborated.ref,))
        self.repository.save(project)
        tests = project.current(ArtifactKind.TEST_SPEC)
        log = Phase3ReviewLog(elaborated.ref, tests.ref, (
            Phase3Decision(elaborated.ref, ApprovalDecision.APPROVED, "alice", "2026-08-14T12:36:00Z", None, "Reviewed."),
            Phase3Decision(tests.ref, ApprovalDecision.APPROVED, "bob", "2026-08-14T12:36:01Z", None, "Reviewed."),
        ))
        return project, phase3_review_log_to_dict(log)

    def logical_ir_app(self, *, failure=None):
        project, payload = self.phase3_project_and_payload()
        self.assertEqual("200 OK", self.request("/api/review/review-demo", payload)["status"])
        document = LogicalIRDocument(
            "review_demo", (TypeDeclaration("type.Value", "Value", ("R-1",)),),
            (Contract("contract.work", "work", ("Value",), "Value", (), (), (), ("R-1",), False),),
            (RequirementObligation("R-1", (), ("R-1",)),), (), (),
        )

        class Backend:
            calls = 0

            def generate_logical_ir(inner_self, prompt, config):
                inner_self.calls += 1
                if failure is not None:
                    raise failure
                text = json.dumps({"schema": RESPONSE_SCHEMA, "logical_ir": logical_ir_to_dict(document)})
                return ProviderCompletion(text, ProviderProvenance(
                    "fake", "model-a", "interaction-transport", 12, 24,
                    "2026-08-14T13:50:00Z",
                ))

        backend = Backend()
        coordinator = LogicalIRCoordinator(
            self.repository, backend, LogicalIRBackendConfig("fake", "model-a", 0.0, 4096),
        )
        return ProjectCommandApplication(ProjectCommandService(self.repository), coordinator), backend, project

    def test_generate_logical_ir_exact_route_persists_atomic_artifact_set(self):
        self.app, backend, _ = self.logical_ir_app()
        response = self.request("/api/logical-ir/review-demo", {"guidance": "Stay literal."})
        self.assertEqual("200 OK", response["status"])
        self.assertEqual("generate_logical_ir", response["body"]["command"])
        self.assertEqual(1, backend.calls)
        updated = self.repository.get("review-demo")
        for kind, prefix in (
            (ArtifactKind.LOGICAL_IR_LOG, "interaction_log"),
            (ArtifactKind.LOGICAL_IR, "logical_ir"),
            (ArtifactKind.LOGICAL_REVIEW, "logical_review"),
        ):
            artifact = updated.current(kind)
            self.assertEqual(artifact.artifact_id, response["body"][f"{prefix}_artifact_id"])
            self.assertEqual(artifact.content_hash, response["body"][f"{prefix}_content_hash"])

    def test_submit_exact_logical_finding_decision_and_read_current_review(self):
        self.app, _, _ = self.logical_ir_app()
        self.assertEqual("200 OK", self.request("/api/logical-ir/review-demo", {})["status"])
        project = self.repository.get("review-demo")
        logical = project.current(ArtifactKind.LOGICAL_IR)
        review = project.current(ArtifactKind.LOGICAL_REVIEW)
        finding_id = json.loads(review.content)["findings"][0]["finding_id"]
        payload = {
            "logical_ir_artifact_id": logical.artifact_id,
            "logical_ir_content_hash": logical.content_hash,
            "logical_review_artifact_id": review.artifact_id,
            "logical_review_content_hash": review.content_hash,
            "finding_id": finding_id,
            "disposition": FindingDisposition.WAIVED.value,
            "reviewer": "ben",
            "rationale": "Accepted for this bounded slice.",
        }
        response = self.request("/api/logical-review/review-demo", payload)
        self.assertEqual("200 OK", response["status"])
        self.assertEqual("submit_logical_finding_decision", response["body"]["command"])
        updated = self.repository.get("review-demo")
        self.assertEqual(2, updated.current(ArtifactKind.LOGICAL_REVIEW).version)

        read_app = ReadOnlyProjectApplication(ProjectQueryService(self.repository))
        original_app, self.app = self.app, read_app
        read = self.request("/api/logical-review/review-demo", method="GET", raw_body=b"")
        self.app = original_app
        self.assertEqual("200 OK", read["status"])
        self.assertFalse(read["body"]["logical_review"]["blocks_compilation"])
        self.assertNotIn("content", read["body"])

    def test_logical_finding_route_rejects_stale_expanded_and_alternate_requests_without_write(self):
        self.app, _, _ = self.logical_ir_app()
        self.request("/api/logical-ir/review-demo", {})
        project = self.repository.get("review-demo")
        logical = project.current(ArtifactKind.LOGICAL_IR)
        review = project.current(ArtifactKind.LOGICAL_REVIEW)
        base = {
            "logical_ir_artifact_id": logical.artifact_id,
            "logical_ir_content_hash": logical.content_hash,
            "logical_review_artifact_id": review.artifact_id,
            "logical_review_content_hash": review.content_hash,
            "finding_id": json.loads(review.content)["findings"][0]["finding_id"],
            "disposition": "waived", "reviewer": "ben", "rationale": "Accepted.",
        }
        stale = dict(base, logical_review_content_hash="sha256:" + "0" * 64)
        expanded = dict(base, authority="forged")
        for path, payload in (("/api/logical-review/review-demo", stale),
                              ("/api/logical-review/review-demo", expanded),
                              ("/api/logical-review/%72eview-demo", base)):
            with self.subTest(path=path):
                self.assertEqual("400 Bad Request", self.request(path, payload)["status"])
                self.assertEqual(project, self.repository.get("review-demo"))

    def test_logical_ir_route_rejects_malformed_alternate_and_unconfigured_requests(self):
        self.app, backend, before = self.logical_ir_app()
        for path, payload in (
            ("/api/logical-ir/%72eview-demo", {}),
            ("/api/logical-ir/review-demo", {"guidance": 7}),
            ("/api/logical-ir/review-demo", {"guidance": "x", "retry": True}),
        ):
            with self.subTest(path=path, payload=payload):
                self.assertEqual("400 Bad Request", self.request(path, payload)["status"])
        self.assertEqual(0, backend.calls)
        self.assertIsNone(self.repository.get("review-demo").current(ArtifactKind.LOGICAL_IR))
        self.app = ProjectCommandApplication(ProjectCommandService(self.repository))
        self.assertEqual("400 Bad Request", self.request("/api/logical-ir/review-demo", {})["status"])

    def test_logical_ir_backend_failure_returns_bad_gateway_without_write_or_retry(self):
        self.app, backend, _ = self.logical_ir_app(failure=TimeoutError("timed out"))
        response = self.request("/api/logical-ir/review-demo", {})
        self.assertEqual("502 Bad Gateway", response["status"])
        self.assertEqual(1, backend.calls)
        self.assertIsNone(self.repository.get("review-demo").current(ArtifactKind.LOGICAL_IR))

    def test_submit_exact_phase3_review_route_persists_log_and_snapshots(self):
        _, payload = self.phase3_project_and_payload()
        response = self.request("/api/review/review-demo", payload)
        self.assertEqual("200 OK", response["status"])
        self.assertEqual("submit_phase3_review", response["body"]["command"])
        updated = self.repository.get("review-demo")
        log = updated.current(ArtifactKind.REVIEW_LOG)
        self.assertEqual(log.artifact_id, response["body"]["review_log_artifact_id"])
        self.assertEqual(log.content_hash, response["body"]["review_log_content_hash"])
        self.assertIsNotNone(updated.current(ArtifactKind.REVIEWED_ELABORATED_SPEC))
        self.assertIsNotNone(updated.current(ArtifactKind.REVIEWED_TEST_SPEC))

    def test_phase3_review_route_rejects_stale_expanded_and_alternate_requests_without_write(self):
        project, payload = self.phase3_project_and_payload()
        cases = []
        expanded = dict(payload)
        expanded["authority"] = "forged"
        cases.append(("/api/review/review-demo", expanded))
        stale = json.loads(json.dumps(payload))
        stale["inputs"]["elaborated_spec"]["content_hash"] = "sha256:" + "0" * 64
        cases.append(("/api/review/review-demo", stale))
        cases.append(("/api/review/%72eview-demo", payload))
        for path, body in cases:
            with self.subTest(path=path, body=body):
                self.assertEqual("400 Bad Request", self.request(path, body)["status"])
                self.assertEqual(project, self.repository.get("review-demo"))

    def test_spec_submission_transport_rejects_forged_or_unknown_payloads_without_write(self):
        self.request("/api/projects", {"project_id": "demo", "name": "Demo", "source": "source"})
        source = self.repository.get("demo").current(project_fixtures.ArtifactKind.ORIGINAL_SPEC)
        before = self.repository.get("demo")
        payload = {"upstream_artifact_id": source.artifact_id,
                   "upstream_content_hash": "sha256:" + "0" * 64, "content": "x"}
        self.assertEqual("400 Bad Request", self.request("/api/projects/demo/elaborated-spec", payload)["status"])
        payload["upstream_content_hash"] = source.content_hash
        payload["artifact_id"] = source.artifact_id
        self.assertEqual("400 Bad Request", self.request("/api/projects/demo/elaborated-spec", payload)["status"])
        self.assertEqual(before, self.repository.get("demo"))

    def test_transport_exposes_only_post_command_routes(self):
        response = self.request("/api/projects", {}, method="GET")
        self.assertEqual("405 Method Not Allowed", response["status"])
        self.assertEqual("POST", response["headers"]["Allow"])
        self.assertFalse(hasattr(self.app, "run"))
        for path in ("/api/compile", "/api/execute", "/api/projects/demo/artifacts"):
            self.assertNotEqual("200 OK", self.request(path, {})["status"])

    def test_body_framing_media_type_and_size_fail_closed(self):
        valid = {"project_id": "demo", "name": "Demo", "source": "source"}
        cases = (
            {"content_type": "application/json; charset=utf-8"},
            {"content_length": ""},
            {"content_length": "00"},
            {"content_length": "1048577", "raw_body": b"{}"},
            {"content_length": "3", "raw_body": b"{}"},
            {"transfer_encoding": "chunked"},
        )
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                self.assertEqual("400 Bad Request", self.request("/api/projects", valid, **kwargs)["status"])

    def test_malformed_duplicate_and_noncanonical_json_fail_without_write(self):
        bodies = (
            b"{",
            b'{"project_id":"demo","project_id":"other","name":"Demo","source":"x"}',
            b'{"project_id":"demo","name":"Demo","source":"x","extra":true}',
            b'["not", "an", "object"]',
            b'{"project_id":"demo","name":"Demo","source":"\xff"}',
        )
        for body in bodies:
            with self.subTest(body=body):
                response = self.request("/api/projects", raw_body=body)
                self.assertEqual("400 Bad Request", response["status"])
        self.assertEqual((), self.repository.list_statuses())

    def test_query_encoded_identity_stale_hash_and_duplicate_create_fail_closed(self):
        self.request("/api/projects", {"project_id": "demo", "name": "Demo", "source": "source"})
        source = self.repository.get("demo").current(project_fixtures.ArtifactKind.ORIGINAL_SPEC)
        command = {"artifact_id": source.artifact_id, "content_hash": "sha256:" + "0" * 64,
                   "decision": "approved", "reviewer": "reviewer"}
        for path, kwargs in (
            ("/api/projects/%64emo/decisions", {}),
            ("/api/projects/demo/decisions", {"query": "force=1"}),
            ("/api/projects/demo/decisions", {}),
        ):
            with self.subTest(path=path, kwargs=kwargs):
                self.assertEqual("400 Bad Request", self.request(path, command, **kwargs)["status"])
        duplicate = self.request("/api/projects", {"project_id": "demo", "name": "Other", "source": "x"})
        self.assertEqual("409 Conflict", duplicate["status"])
        self.assertEqual(0, len(self.repository.get("demo").approvals))


if __name__ == "__main__":
    unittest.main()

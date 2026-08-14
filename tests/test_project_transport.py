import io
import json
import tempfile
import unittest
from pathlib import Path

from specatom_hs.project_commands import ProjectCommandService
from specatom_hs.project_queries import ProjectQueryService
from specatom_hs.project_repository import FilesystemProjectRepository
from specatom_hs.project_transport import ProjectCommandApplication, ReadOnlyProjectApplication

import tests.test_projects as project_fixtures


class ReadOnlyProjectApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        repository = FilesystemProjectRepository(Path(self.temporary.name) / "projects")
        project = project_fixtures.ProjectModelTests().traceability_project()
        repository.create("demo", "Demo", "placeholder")
        repository.save(project_fixtures.add_traceability_report(project))
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

    def test_transport_has_no_mutation_or_server_capability(self):
        self.assertFalse(hasattr(self.app, "run"))
        response = self.request("/api/projects", method="POST")
        self.assertEqual("405 Method Not Allowed", response["status"])
        self.assertEqual("GET", response["headers"]["Allow"])

    def test_unknown_routes_projects_and_spec_ids_are_not_found(self):
        for path, query in (("/api/unknown/demo", ""), ("/api/projects/missing", ""), ("/api/trace/demo", "spec_id=missing")):
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

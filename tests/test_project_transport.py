import io
import json
import tempfile
import unittest
from pathlib import Path

from specatom_hs.project_queries import ProjectQueryService
from specatom_hs.project_repository import FilesystemProjectRepository
from specatom_hs.project_transport import ReadOnlyProjectApplication

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


if __name__ == "__main__":
    unittest.main()

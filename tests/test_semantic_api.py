import io
import json
import unittest

from specatom_hs.semantic_api import SemanticValidationApplication
from webapp.app import app


class FakeService:
    def plan(self, project_id): return {"project_id": project_id, "plan": {"artifact_id":"a", "content_hash":"sha256:"+"1"*64}}
    def synthesize_plan(self, project_id): return self.plan(project_id)
    def review_plan(self, project_id, payload): return {"project_id":project_id,"review":payload}
    def execute(self, project_id, payload): return {"project_id":project_id,"request":payload}
    def results(self, project_id): return {"project_id":project_id,"artifacts":[],"grade_legend":{f"G{i}":str(i) for i in range(7)}}
    def trace(self, project_id, obligation): return {"project_id":project_id,"obligation":obligation,"nodes":[],"edges":[]}
    def artifact_body(self, project_id, artifact, digest): return {"project_id":project_id,"artifact_id":artifact,"content_hash":digest,"content":"immutable"}


def invoke(application, method, path, body=b"", query="", authorized=True):
    captured = {}
    environ = {"REQUEST_METHOD":method,"PATH_INFO":path,"QUERY_STRING":query,
               "CONTENT_LENGTH":str(len(body)),"wsgi.input":io.BytesIO(body),
               "HTTP_AUTHORIZATION":"Bearer review" if authorized else ""}
    data = b"".join(application(environ, lambda status, headers: captured.update(status=status, headers=headers)))
    return int(captured["status"].split()[0]), json.loads(data)


class SemanticApiTests(unittest.TestCase):
    def setUp(self):
        self.api = SemanticValidationApplication(FakeService(), lambda env: env.get("HTTP_AUTHORIZATION") == "Bearer review")

    def test_exact_narrow_metadata_routes(self):
        self.assertEqual(200, invoke(self.api,"GET","/api/validation-plan/demo")[0])
        result = invoke(self.api,"GET","/api/semantic-results/demo")[1]
        self.assertEqual([f"G{i}" for i in range(7)], sorted(result["grade_legend"]))
        trace = invoke(self.api,"GET","/api/semantic-trace/demo",query="obligation=OBL-1")[1]
        self.assertEqual("OBL-1", trace["obligation"])

    def test_commands_and_download_require_authorization(self):
        self.assertEqual(403, invoke(self.api,"POST","/api/validation-plan/demo",b"{}",authorized=False)[0])
        query="artifact=a&hash=sha256%3A"+"1"*64
        self.assertEqual(403, invoke(self.api,"GET","/api/semantic-results/demo",query=query,authorized=False)[0])
        status, payload = invoke(self.api,"GET","/api/semantic-results/demo",query=query)
        self.assertEqual(200, status); self.assertEqual("immutable", payload["content"])

    def test_duplicate_json_and_query_fails_closed(self):
        body=b'{"obligation":{},"obligation":{},"implementation":{}}'
        self.assertEqual(400, invoke(self.api,"POST","/api/semantic-test/demo",body)[0])
        self.assertEqual(400, invoke(self.api,"GET","/api/semantic-trace/demo",query="obligation=a&obligation=b")[0])

    def test_bounded_and_canonical_requests(self):
        self.assertEqual(400, invoke(self.api,"POST","/api/semantic-test/demo",b"x"*128001)[0])
        self.assertEqual(400, invoke(self.api,"GET","/api/semantic-results/demo%2Fother")[0])
        self.assertEqual(404, invoke(self.api,"GET","/api/semantic-verdict/demo")[0])

    def test_flask_routes_delegate_without_expanding_authority(self):
        app.config["SEMANTIC_VALIDATION_APPLICATION"] = self.api
        client = app.test_client()
        response = client.get("/api/semantic-results/demo")
        self.assertEqual(200, response.status_code)
        self.assertIn("G6", response.get_json()["grade_legend"])
        self.assertEqual(403, client.post("/api/validation-plan/demo", data="{}", content_type="application/json").status_code)
        app.config.pop("SEMANTIC_VALIDATION_APPLICATION", None)

    def test_browser_exposes_honest_evidence_views(self):
        body = app.test_client().get("/").data
        for marker in (b'evidence_graph', b'grade_vector', b'tool_details', b'counterexamples',
                       b'assumptions_and_holes', b'G6', b'not semantically validated'):
            self.assertIn(marker, body)


if __name__ == "__main__": unittest.main()

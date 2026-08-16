import unittest
from webapp.app import app


class EvaluationWebTests(unittest.TestCase):
    def setUp(self): self.client = app.test_client()
    def test_browser_and_api_smoke(self):
        browser = self.client.get("/")
        self.assertEqual(200, browser.status_code)
        self.assertIn(b'type="file"', browser.data)
        self.assertIn(b'accept=".plain,text/plain"', browser.data)
        self.assertIn(b'id="download"', browser.data)
        self.assertIn(b'plain2metta-evaluation-evidence.json', browser.data)
        health = self.client.get("/api/health")
        self.assertEqual(200, health.status_code)
        self.assertEqual("ready", health.get_json()["status"])
        response = self.client.post("/api/evaluate", json={"text": "***requirements***\n- [id:REQ-1] Reply.\n"})
        self.assertEqual(200, response.status_code)
        self.assertEqual(0, response.get_json()["sandbox"]["exit_code"])
        self.assertFalse(response.get_json()["claim_evidence"]["metta"]["executed"])
        self.assertTrue(response.get_json()["claim_evidence"]["python"]["tested"])
        self.assertFalse(response.get_json()["claim_evidence"]["python"]["runtime_validated"])
        self.assertIn("not independently validated", response.get_json()["labels"]["python"])
    def test_api_schema_fails_closed(self):
        self.assertEqual(400, self.client.post("/api/evaluate", json={"text":"x", "extra":1}).status_code)
        self.assertEqual(400, self.client.post("/api/evaluate", json={"text": 3}).status_code)

    def test_api_spec_size_fails_closed(self):
        response = self.client.post("/api/evaluate", json={"text": "x" * 128_001})
        self.assertEqual(413, response.status_code)
        self.assertIn("128 KiB", response.get_json()["error"])

    def test_examples_are_all_accepted_without_invented_requirement_ids(self):
        examples = self.client.get("/api/examples").get_json()
        self.assertGreaterEqual(len(examples), 3)
        for name, source in examples.items():
            with self.subTest(name=name):
                response = self.client.post("/api/evaluate", json={"text": source})
                self.assertEqual(200, response.status_code, response.get_json())
                requirement_ids = [item["requirement_id"] for item in response.get_json()["logical_ir"]["obligations"]]
                self.assertTrue(requirement_ids)
                self.assertTrue(all(f"[id:{item}]" in source for item in requirement_ids))

import unittest
from webapp.app import app


class EvaluationWebTests(unittest.TestCase):
    def setUp(self): self.client = app.test_client()
    def test_browser_and_api_smoke(self):
        self.assertEqual(200, self.client.get("/").status_code)
        health = self.client.get("/api/health")
        self.assertEqual(200, health.status_code)
        self.assertEqual("ready", health.get_json()["status"])
        response = self.client.post("/api/evaluate", json={"text": "***requirements***\n- [id:REQ-1] Reply.\n"})
        self.assertEqual(200, response.status_code)
        self.assertEqual(0, response.get_json()["sandbox"]["exit_code"])
        self.assertFalse(response.get_json()["claim_evidence"]["metta"]["executed"])
        self.assertTrue(response.get_json()["claim_evidence"]["python"]["tested"])
    def test_api_schema_fails_closed(self):
        self.assertEqual(400, self.client.post("/api/evaluate", json={"text":"x", "extra":1}).status_code)

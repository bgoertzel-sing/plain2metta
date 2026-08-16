import unittest
from pathlib import Path
from unittest.mock import patch
from webapp.app import app
from specatom_hs.evaluation import evaluate_plain


class EvaluationWebTests(unittest.TestCase):
    def setUp(self): self.client = app.test_client()
    def test_browser_and_api_smoke(self):
        browser = self.client.get("/")
        self.assertEqual(200, browser.status_code)
        self.assertIn(b'type="file"', browser.data)
        self.assertIn(b'accept=".plain,text/plain"', browser.data)
        self.assertIn(b'id="download"', browser.data)
        self.assertIn(b'id="download-metta"', browser.data)
        self.assertIn(b'id="download-python"', browser.data)
        self.assertIn(b'plain2metta-evaluation-evidence.json', browser.data)
        self.assertIn(b'evaluation.metta', browser.data)
        self.assertIn(b'evaluation.py', browser.data)
        health = self.client.get("/api/health")
        self.assertEqual(200, health.status_code)
        self.assertEqual("ready", health.get_json()["status"])
        source = (Path(__file__).resolve().parents[1] / "examples/evaluation/01_greeting.plain").read_text()
        response = self.client.post("/api/evaluate", json={"text": source})
        self.assertEqual(200, response.status_code)
        self.assertEqual(0, response.get_json()["sandbox"]["python"]["exit_code"])
        self.assertEqual(0, response.get_json()["sandbox"]["metta"]["exit_code"])
        self.assertTrue(response.get_json()["claim_evidence"]["metta"]["executed"])
        self.assertTrue(response.get_json()["claim_evidence"]["metta"]["runtime_validated"])
        self.assertTrue(response.get_json()["claim_evidence"]["python"]["tested"])
        self.assertTrue(response.get_json()["claim_evidence"]["python"]["runtime_validated"])
        self.assertTrue(response.get_json()["sandbox"]["metta"]["output_matches"])
        self.assertTrue(response.get_json()["sandbox"]["python"]["output_matches"])
    def test_api_schema_fails_closed(self):
        self.assertEqual(400, self.client.post("/api/evaluate", json={"text":"x", "extra":1}).status_code)
        self.assertEqual(400, self.client.post("/api/evaluate", json={"text": 3}).status_code)

    def test_api_spec_size_fails_closed(self):
        response = self.client.post("/api/evaluate", json={"text": "x" * 128_001})
        self.assertEqual(413, response.status_code)
        self.assertIn("128 KiB", response.get_json()["error"])

    def test_metta_expected_output_mismatch_fails_validation(self):
        mismatched = {"exit_code": 0, "stdout": '["WRONG"]\n', "stderr": "", "duration_ms": 1,
                      "runtime": "hyperon-cli", "runtime_version": "0.2.10",
                      "runtime_path": "metta", "limits": {}}
        with patch("specatom_hs.evaluation.run_metta_reference", return_value=mismatched):
            source = (Path(__file__).resolve().parents[1] / "examples/evaluation/01_greeting.plain").read_text()
            result = evaluate_plain(source)
        self.assertTrue(result["claim_evidence"]["metta"]["executed"])
        self.assertFalse(result["claim_evidence"]["metta"]["tested"])
        self.assertFalse(result["claim_evidence"]["metta"]["runtime_validated"])
        self.assertFalse(result["sandbox"]["metta"]["output_matches"])
        self.assertFalse(result["semantic_validation"]["passed"])

    def test_python_exit_zero_output_mismatch_fails_validation(self):
        mismatched = {"exit_code": 0, "stdout": "plausible-but-wrong\n", "stderr": "", "duration_ms": 1,
                      "limits": {}}
        source = (Path(__file__).resolve().parents[1] / "examples/evaluation/02_task_list.plain").read_text()
        with patch("specatom_hs.evaluation.run_python_reference", return_value=mismatched):
            result = evaluate_plain(source)
        self.assertTrue(result["claim_evidence"]["python"]["executed"])
        self.assertFalse(result["claim_evidence"]["python"]["expected_output_tested"])
        self.assertFalse(result["claim_evidence"]["python"]["semantically_validated"])
        self.assertFalse(result["semantic_validation"]["passed"])

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

import subprocess
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

    def test_supported_evaluation_returns_stage_1_through_8_ancestry_and_server_grades(self):
        source = (Path(__file__).resolve().parents[1] / "examples/evaluation/01_greeting.plain").read_text()
        response = self.client.post("/api/evaluate", json={"text": source})
        self.assertEqual(200, response.status_code, response.get_json())
        payload = response.get_json()

        self.assertEqual(list(range(1, 9)), payload["ancestry"]["stages"])
        nodes = payload["ancestry"]["nodes"]
        self.assertTrue(nodes)
        self.assertEqual(set(range(1, 9)), {node["stage"] for node in nodes})
        for node in nodes:
            self.assertEqual(
                {"stage", "kind", "artifact_id", "content_hash", "state", "upstream"},
                set(node),
            )
            self.assertTrue(node["artifact_id"])
            self.assertTrue(node["content_hash"].startswith("sha256:"))

        self.assertTrue(payload["verdicts"])
        for verdict in payload["verdicts"]:
            self.assertEqual(
                {f"G{index}" for index in range(7)},
                set(verdict["grade_achieved"]["vector"]),
            )
            self.assertTrue(all(isinstance(value, bool) for value in verdict["grade_achieved"]["vector"].values()))
            self.assertTrue(verdict["validation_plan_ref"])
            self.assertTrue(verdict["runtime_evidence_refs"])

        stage10 = payload["release_metadata"]["stage10"]
        self.assertEqual("plain2metta-vertical-acceptance/v1", stage10["schema"])
        self.assertTrue(stage10["content_hash"].startswith("sha256:"))
        self.assertTrue(stage10["release_id"])

    def test_supported_evaluation_builds_exact_approved_stage_1_through_3_slice(self):
        source = (Path(__file__).resolve().parents[1] / "examples/evaluation/01_greeting.plain").read_text()
        response = self.client.post("/api/evaluate", json={"text": source})
        self.assertEqual(200, response.status_code, response.get_json())
        ancestry = response.get_json()["ancestry"]
        self.assertEqual([1, 2, 3], ancestry["stages"][:3])
        self.assertTrue({1, 2, 3}.issubset({node["stage"] for node in ancestry["nodes"]}))
        self.assertEqual("approved", ancestry["plan_approval"])
        self.assertIn("contract-calculus-interpretation", {node["kind"] for node in ancestry["nodes"]})

    def test_supported_evaluation_runs_approved_stage_4_hypothesis_plan(self):
        source = (Path(__file__).resolve().parents[1] / "examples/evaluation/01_greeting.plain").read_text()
        response = self.client.post("/api/evaluate", json={"text": source})
        self.assertEqual(200, response.status_code, response.get_json())
        ancestry = response.get_json()["ancestry"]
        self.assertEqual([1, 2, 3, 4], ancestry["stages"][:4])
        stage4 = [node for node in ancestry["nodes"] if node["stage"] == 4]
        self.assertEqual(1, len(stage4))
        self.assertEqual("runtime-evidence", stage4[0]["kind"])
        self.assertEqual("hypothesis-backend", ancestry["stage4_backend"]["name"])
        self.assertEqual("6.138.15", ancestry["stage4_backend"]["version"])
        self.assertTrue(ancestry["stage4_backend"]["observations_passed"])

    def test_supported_evaluation_runs_approved_stage_5_tlc_plan(self):
        source = (Path(__file__).resolve().parents[1] / "examples/evaluation/01_greeting.plain").read_text()
        response = self.client.post("/api/evaluate", json={"text": source})
        self.assertEqual(200, response.status_code, response.get_json())
        ancestry = response.get_json()["ancestry"]
        self.assertEqual([1, 2, 3, 4, 5], ancestry["stages"][:5])
        stage5 = [node for node in ancestry["nodes"] if node["stage"] == 5]
        self.assertEqual(1, len(stage5))
        self.assertEqual("formal-evidence", stage5[0]["kind"])
        self.assertEqual("tlc-backend", ancestry["stage5_backend"]["name"])
        self.assertEqual("1.7.4", ancestry["stage5_backend"]["version"])
        self.assertTrue(ancestry["stage5_backend"]["invariant_satisfied"])

    def test_supported_evaluation_runs_approved_stage_6_z3_plan(self):
        source = (Path(__file__).resolve().parents[1] / "examples/evaluation/01_greeting.plain").read_text()
        response = self.client.post("/api/evaluate", json={"text": source})
        self.assertEqual(200, response.status_code, response.get_json())
        ancestry = response.get_json()["ancestry"]
        self.assertEqual([1, 2, 3, 4, 5, 6], ancestry["stages"][:6])
        stage6 = [node for node in ancestry["nodes"] if node["stage"] == 6]
        self.assertEqual(1, len(stage6))
        self.assertEqual("formal-evidence", stage6[0]["kind"])
        self.assertEqual("z3-backend", ancestry["stage6_backend"]["name"])
        self.assertEqual("4.15.3", ancestry["stage6_backend"]["version"])
        self.assertTrue(ancestry["stage6_backend"]["postcondition_proved"])

    def test_supported_evaluation_runs_approved_stage_7_lean_plan(self):
        source = (Path(__file__).resolve().parents[1] / "examples/evaluation/01_greeting.plain").read_text()
        response = self.client.post("/api/evaluate", json={"text": source})
        self.assertEqual(200, response.status_code, response.get_json())
        ancestry = response.get_json()["ancestry"]
        self.assertEqual([1, 2, 3, 4, 5, 6, 7], ancestry["stages"][:7])
        stage7 = [node for node in ancestry["nodes"] if node["stage"] == 7]
        self.assertEqual(1, len(stage7))
        self.assertEqual("formal-evidence", stage7[0]["kind"])
        self.assertEqual("lean-backend", ancestry["stage7_backend"]["name"])
        self.assertEqual("4.33.0", ancestry["stage7_backend"]["version"])
        self.assertTrue(ancestry["stage7_backend"]["kernel_checked"])

    def test_supported_evaluation_composes_stage_8_verdict(self):
        source = (Path(__file__).resolve().parents[1] / "examples/evaluation/01_greeting.plain").read_text()
        response = self.client.post("/api/evaluate", json={"text": source})
        self.assertEqual(200, response.status_code, response.get_json())
        payload = response.get_json()
        ancestry = payload["ancestry"]
        self.assertEqual(list(range(1, 9)), ancestry["stages"])
        stage8 = [node for node in ancestry["nodes"] if node["stage"] == 8]
        self.assertEqual(1, len(stage8))
        self.assertEqual("validation-verdict", stage8[0]["kind"])
        self.assertEqual(1, len(payload["verdicts"]))
        verdict = payload["verdicts"][0]
        self.assertEqual(stage8[0]["artifact_id"], verdict["artifact_id"])
        self.assertEqual(stage8[0]["content_hash"], verdict["content_hash"])
        self.assertEqual({f"G{index}" for index in range(7)}, set(verdict["grade_achieved"]["vector"]))
        self.assertEqual("unknown", verdict["status"])
        self.assertIn("missing dual-runtime evidence", verdict["residual_risk"])

    def test_supported_evaluation_projects_stage_9_server_evidence(self):
        source = (Path(__file__).resolve().parents[1] / "examples/evaluation/01_greeting.plain").read_text()
        response = self.client.post("/api/evaluate", json={"text": source})
        self.assertEqual(200, response.status_code, response.get_json())
        payload = response.get_json()
        projection = payload["evidence_projection"]

        self.assertEqual("plain2metta-evaluation-evidence/v1", projection["schema"])
        self.assertEqual(payload["ancestry"], projection["ancestry"])
        self.assertEqual(payload["verdicts"], projection["verdicts"])
        self.assertEqual("approved", projection["plan_review"]["decision"])
        self.assertEqual(
            {"hypothesis-backend", "tlc-backend", "z3-backend", "lean-backend"},
            {backend["name"] for backend in projection["backends"]},
        )
        self.assertEqual([], projection["counterexamples"])
        self.assertEqual([], projection["assumptions"])
        self.assertEqual([], projection["unresolved_holes"])
        self.assertEqual(payload["verdicts"][0]["residual_risk"], projection["residual_risk"])

    def test_source_byte_mutation_is_rejected_before_legacy_or_stage_4_execution(self):
        source = (Path(__file__).resolve().parents[1] / "examples/evaluation/01_greeting.plain").read_text() + "\n"
        with patch("webapp.app.evaluate_plain") as legacy, patch(
            "specatom_hs.evaluation_vertical.HypothesisCoordinator.run"
        ) as stage4:
            response = self.client.post("/api/evaluate", json={"text": source})
        self.assertEqual(422, response.status_code)
        self.assertIn("unsupported or reworded", response.get_json()["error"])
        legacy.assert_not_called()
        stage4.assert_not_called()

    def test_missing_plan_approval_fails_atomically_before_backend_execution(self):
        source = (Path(__file__).resolve().parents[1] / "examples/evaluation/01_greeting.plain").read_text()

        def omit_review(project, review):
            return project

        with patch("specatom_hs.evaluation_vertical.submit_plan_review", side_effect=omit_review), \
             patch("specatom_hs.evaluation_vertical.execute_hypothesis_request") as stage4, \
             patch("specatom_hs.evaluation_vertical.TLCCoordinator.run") as stage5, \
             patch("specatom_hs.evaluation_vertical.SMTCoordinator.run") as stage6, \
             patch("specatom_hs.evaluation_vertical.LeanCoordinator.run") as stage7, \
             patch("webapp.app.evaluate_plain") as legacy:
            response = self.client.post("/api/evaluate", json={"text": source})

        self.assertEqual(422, response.status_code)
        self.assertEqual({"error"}, set(response.get_json()))
        self.assertIn("approved reviewed plan", response.get_json()["error"].lower())
        stage4.assert_not_called()
        stage5.assert_not_called()
        stage6.assert_not_called()
        stage7.assert_not_called()
        legacy.assert_not_called()

    def test_stage_4_request_hash_mismatch_fails_atomically_before_later_execution(self):
        source = (Path(__file__).resolve().parents[1] / "examples/evaluation/01_greeting.plain").read_text()

        from specatom_hs.hypothesis_backend import execute_hypothesis_request

        def misattribute_result(request, python_executable):
            result = execute_hypothesis_request(request, python_executable)
            result["request_hash"] = "sha256:" + "0" * 64
            return result

        with patch(
            "specatom_hs.evaluation_vertical.execute_hypothesis_request",
            side_effect=misattribute_result,
        ) as stage4, \
             patch("specatom_hs.evaluation_vertical.TLCCoordinator.run") as stage5, \
             patch("specatom_hs.evaluation_vertical.SMTCoordinator.run") as stage6, \
             patch("specatom_hs.evaluation_vertical.LeanCoordinator.run") as stage7, \
             patch("webapp.app.evaluate_plain") as legacy:
            response = self.client.post("/api/evaluate", json={"text": source})

        self.assertEqual(422, response.status_code)
        self.assertEqual({"error"}, set(response.get_json()))
        self.assertIn("misattributed", response.get_json()["error"].lower())
        stage4.assert_called_once()
        stage5.assert_not_called()
        stage6.assert_not_called()
        stage7.assert_not_called()
        legacy.assert_not_called()

    def test_stage_4_timeout_fails_atomically_before_later_execution(self):
        source = (Path(__file__).resolve().parents[1] / "examples/evaluation/01_greeting.plain").read_text()

        with patch(
            "specatom_hs.evaluation_vertical.execute_hypothesis_request",
            side_effect=subprocess.TimeoutExpired(("python", "generated_hypothesis.py"), 3),
        ) as stage4, \
             patch("specatom_hs.evaluation_vertical.TLCCoordinator.run") as stage5, \
             patch("specatom_hs.evaluation_vertical.SMTCoordinator.run") as stage6, \
             patch("specatom_hs.evaluation_vertical.LeanCoordinator.run") as stage7, \
             patch("webapp.app.evaluate_plain") as legacy:
            response = self.client.post("/api/evaluate", json={"text": source})

        self.assertEqual(422, response.status_code)
        self.assertEqual({"error": "evaluation backend timed out"}, response.get_json())
        stage4.assert_called_once()
        stage5.assert_not_called()
        stage6.assert_not_called()
        stage7.assert_not_called()
        legacy.assert_not_called()

    def test_malformed_stage_4_evidence_fails_atomically_before_later_execution(self):
        source = (Path(__file__).resolve().parents[1] / "examples/evaluation/01_greeting.plain").read_text()

        from specatom_hs.hypothesis_backend import execute_hypothesis_request

        def add_unknown_field(request, python_executable):
            result = execute_hypothesis_request(request, python_executable)
            result["unreviewed_claim"] = True
            return result

        with patch(
            "specatom_hs.evaluation_vertical.execute_hypothesis_request",
            side_effect=add_unknown_field,
        ) as stage4, \
             patch("specatom_hs.evaluation_vertical.TLCCoordinator.run") as stage5, \
             patch("specatom_hs.evaluation_vertical.SMTCoordinator.run") as stage6, \
             patch("specatom_hs.evaluation_vertical.LeanCoordinator.run") as stage7, \
             patch("webapp.app.evaluate_plain") as legacy:
            response = self.client.post("/api/evaluate", json={"text": source})

        self.assertEqual(422, response.status_code)
        self.assertEqual({"error"}, set(response.get_json()))
        self.assertIn("unknown or missing fields", response.get_json()["error"].lower())
        stage4.assert_called_once()
        stage5.assert_not_called()
        stage6.assert_not_called()
        stage7.assert_not_called()
        legacy.assert_not_called()

    def test_cross_runtime_disagreement_is_not_promoted_into_vertical_evidence(self):
        source = (Path(__file__).resolve().parents[1] / "examples/evaluation/01_greeting.plain").read_text()
        mismatched = {
            "exit_code": 0,
            "stdout": '["WRONG"]\n',
            "stderr": "",
            "duration_ms": 1,
            "runtime": "hyperon-cli",
            "runtime_version": "0.2.10",
            "runtime_path": "metta",
            "limits": {},
        }

        with patch("specatom_hs.evaluation.run_metta_reference", return_value=mismatched):
            response = self.client.post("/api/evaluate", json={"text": source})

        self.assertEqual(200, response.status_code, response.get_json())
        payload = response.get_json()
        self.assertFalse(payload["semantic_validation"]["passed"])
        self.assertFalse(payload["sandbox"]["metta"]["output_matches"])
        self.assertEqual("unknown", payload["verdicts"][0]["status"])
        self.assertEqual("missing dual-runtime evidence", payload["verdicts"][0]["residual_risk"])
        self.assertFalse(payload["verdicts"][0]["grade_achieved"]["vector"]["G2"])
        self.assertFalse(payload["verdicts"][0]["grade_achieved"]["vector"]["G3"])
        self.assertEqual(payload["verdicts"], payload["evidence_projection"]["verdicts"])
        self.assertEqual(
            4,
            len(payload["verdicts"][0]["runtime_evidence_refs"]),
            "legacy dual-runtime output must not be fabricated into canonical evidence",
        )

    def test_failing_stage_4_property_projects_conservative_counterexample(self):
        source = (Path(__file__).resolve().parents[1] / "examples/evaluation/01_greeting.plain").read_text()

        from specatom_hs.hypothesis_backend import execute_hypothesis_request

        def fail_property(request, python_executable):
            result = execute_hypothesis_request(request, python_executable)
            counterexample = dict(result["observations"][0])
            counterexample["matched"] = False
            result["observations"] = [counterexample]
            result["minimal_counterexamples"] = [counterexample]
            result["shrinking"] = ["Falsifying example: exact supported bytes"]
            result["exit_status"] = 1
            return result

        with patch(
            "specatom_hs.evaluation_vertical.execute_hypothesis_request",
            side_effect=fail_property,
        ) as stage4:
            response = self.client.post("/api/evaluate", json={"text": source})

        self.assertEqual(200, response.status_code, response.get_json())
        stage4.assert_called_once()
        payload = response.get_json()
        verdict = payload["verdicts"][0]
        self.assertEqual("fail", verdict["status"])
        self.assertFalse(verdict["grade_achieved"]["vector"]["G4"])
        self.assertIn("property evidence contains a counterexample", verdict["residual_risk"])
        self.assertEqual(1, len(verdict["counterexample_refs"]))
        self.assertEqual(verdict["counterexample_refs"], payload["evidence_projection"]["counterexamples"])

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

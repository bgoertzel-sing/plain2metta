import copy
import json
import os
import unittest

from specatom_hs.hypothesis_backend import (
    HYPOTHESIS_VERSION, PROFILE, SCHEMA, render_hypothesis_module,
    execute_hypothesis_request, request_hash, run_hypothesis_module,
)


PYTHON = "/home/openclaw/research-agent/projects/specatom-hs/experiments/20260817T035226Z-plain2metta-general-semantic-validation-stage0/tools-venv/bin/python"


def request(cases, seed=417):
    return {
        "schema": SCHEMA, "hypothesis_version": HYPOTHESIS_VERSION,
        "profile": PROFILE, "seed": seed,
        "plan": {"artifact_id": "plan-1", "content_hash": "sha256:" + "1" * 64},
        "review": {"artifact_id": "review-1", "content_hash": "sha256:" + "2" * 64},
        "ancestry": [{"artifact_id": "source-1", "content_hash": "sha256:" + "3" * 64}, {"artifact_id": "contract-1", "content_hash": "sha256:" + "4" * 64}, {"artifact_id": "plan-1", "content_hash": "sha256:" + "1" * 64}, {"artifact_id": "review-1", "content_hash": "sha256:" + "2" * 64}],
        "examples": cases, "properties": [], "metamorphic_relations": [], "state_machine": [],
    }


class HypothesisBackendGoldTests(unittest.TestCase):
    def test_numerical_authentication_and_idempotency_gold(self):
        cases = [
            {"case_id": "numerical", "input": {"operation": "numeric-add", "args": [2, 3, -1]}, "expected": 4},
            {"case_id": "authentication", "input": {"operation": "authenticate", "args": ["alice", "correct-horse"]}, "expected": True},
            {"case_id": "idempotency", "input": {"operation": "idempotent-append", "args": ["a", "a", "b"]}, "expected": ["a", "b"]},
        ]
        first = render_hypothesis_module(request(cases))
        self.assertEqual(first, render_hypothesis_module(request(cases)))
        self.assertIn(request_hash(request(cases)), first)
        if os.path.exists(PYTHON):
            result = run_hypothesis_module(request(cases), PYTHON)
            self.assertEqual(0, result["exit_status"], result["stderr"])
            self.assertTrue(json.loads(result["stdout"].splitlines()[-1])["matched"])
            normalized = execute_hypothesis_request(request(cases), PYTHON)
            self.assertEqual(0, normalized["exit_status"])
            self.assertTrue(all(x["matched"] for x in normalized["observations"]))
            self.assertEqual([], normalized["minimal_counterexamples"])

    def test_seeded_mutant_fails_and_replays_exactly(self):
        mutant = request([{"case_id": "numeric-mutant", "input": {"operation": "numeric-add", "args": [1, 1]}, "expected": 3}], 9)
        if not os.path.exists(PYTHON):
            self.skipTest("pinned Stage-0 Hypothesis environment unavailable")
        a = run_hypothesis_module(mutant, PYTHON)
        b = run_hypothesis_module(mutant, PYTHON)
        self.assertNotEqual(0, a["exit_status"])
        self.assertEqual(a["module_hash"], b["module_hash"])
        self.assertIn("numeric-mutant", a["stderr"])
        self.assertIn("numeric-mutant", b["stderr"])
        normalized = execute_hypothesis_request(mutant, PYTHON)
        self.assertNotEqual(0, normalized["exit_status"])
        self.assertEqual("numeric-mutant", normalized["minimal_counterexamples"][0]["case_id"])

    def test_free_prose_unknown_operation_and_path_confusion_fail_closed(self):
        invalid = [
            [{"case_id": "prose", "input": "execute this prose", "expected": True}],
            [{"case_id": "unknown", "input": {"operation": "shell", "args": []}, "expected": True}],
            [{"case_id": "../confused", "input": {"operation": "numeric-add", "args": []}, "expected": 0}],
        ]
        for cases in invalid[:2]:
            with self.assertRaises(ValueError):
                render_hypothesis_module(request(cases))
        # Case identifiers remain inert data and cannot influence the path.
        module = render_hypothesis_module(request(invalid[2]))
        self.assertNotIn("open(", module)

    def test_unknown_version_and_binary_float_fail(self):
        good = request([{"case_id": "n", "input": {"operation": "numeric-add", "args": [1]}, "expected": 1}])
        bad = copy.deepcopy(good); bad["schema"] = "unknown/v9"
        with self.assertRaises(ValueError): render_hypothesis_module(bad)
        bad = copy.deepcopy(good); bad["examples"][0]["expected"] = 1.0
        with self.assertRaises(ValueError): render_hypothesis_module(bad)

    def test_exact_equality_is_a_closed_non_code_operation(self):
        exact = request([{"case_id": "source-bytes", "input": {
            "operation": "exact-equality", "args": ["sha256:abc", "sha256:abc"]},
            "expected": True}])
        module = render_hypothesis_module(exact)
        self.assertIn('if op == "exact-equality"', module)


if __name__ == "__main__": unittest.main()

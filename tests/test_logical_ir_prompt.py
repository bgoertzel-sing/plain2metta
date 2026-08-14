import json
import unittest
from dataclasses import replace

from specatom_hs.elaboration_protocol import ProviderProvenance
from specatom_hs.logical_ir import LogicalIRDocument, TypeDeclaration, logical_ir_to_dict
from specatom_hs.logical_ir_prompt import (
    ProviderCompletion, RESPONSE_SCHEMA, LogicalIRRequest, build_logical_ir_prompt,
    logical_ir_prompt_to_dict, parse_logical_ir_completion,
)
from specatom_hs.projects import ArtifactRef, content_sha256


class LogicalIRPromptTests(unittest.TestCase):
    def setUp(self):
        spec, tests = "[id:R-1] Work.", "[covers:R-1] Verify."
        self.request = LogicalIRRequest(
            ArtifactRef("reviewed-spec:v1", content_sha256(spec)), spec,
            ArtifactRef("reviewed-tests:v1", content_sha256(tests)), tests,
        )
        self.provenance = ProviderProvenance("fake", "model-a", "i-1", 1, 2, "2026-08-14T13:24:00Z")
        self.document = LogicalIRDocument("Demo", (TypeDeclaration("type.Value", "Value", ("R-1",)),), (), (), (), ())

    def test_prompt_binds_both_exact_reviewed_snapshots(self):
        encoded = logical_ir_prompt_to_dict(build_logical_ir_prompt(self.request))
        self.assertEqual("plain2metta-logical-ir-prompt/v1", encoded["schema"])
        self.assertIn("reviewed-spec:v1", encoded["messages"][1]["content"])
        self.assertIn("reviewed-tests:v1", encoded["messages"][1]["content"])
        self.assertFalse(encoded["response_schema"]["additionalProperties"])

    def test_valid_completion_is_strict_ir_and_request_bound(self):
        text = json.dumps({"schema": RESPONSE_SCHEMA, "logical_ir": logical_ir_to_dict(self.document)})
        response = parse_logical_ir_completion(self.request, ProviderCompletion(text, self.provenance))
        self.assertEqual(self.document, response.logical_ir)
        self.assertEqual(self.provenance, response.provenance)

    def test_mutated_snapshot_or_prompt_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "exact artifact hash"):
            build_logical_ir_prompt(replace(self.request, reviewed_spec_text="changed"))
        prompt = build_logical_ir_prompt(self.request)
        with self.assertRaises(ValueError):
            logical_ir_prompt_to_dict(replace(prompt, request_hash="sha256:" + "0" * 64))

    def test_malformed_expanded_executable_and_duplicate_json_fail_closed(self):
        valid = logical_ir_to_dict(self.document)
        bad = [
            "not json",
            json.dumps({"schema": RESPONSE_SCHEMA}),
            json.dumps({"schema": RESPONSE_SCHEMA, "logical_ir": valid, "extra": 1}),
            json.dumps({"schema": RESPONSE_SCHEMA, "logical_ir": {**valid, "executable": True}}),
            '{"schema":"%s","schema":"%s","logical_ir":{}}' % (RESPONSE_SCHEMA, RESPONSE_SCHEMA),
        ]
        for text in bad:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_logical_ir_completion(self.request, ProviderCompletion(text, self.provenance))


if __name__ == "__main__":
    unittest.main()

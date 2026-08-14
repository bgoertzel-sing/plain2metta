import json
import unittest
from dataclasses import replace

from specatom_hs.elaboration_prompt import (
    ProviderCompletion, RESPONSE_SCHEMA, build_elaboration_prompt,
    elaboration_prompt_to_dict, parse_elaboration_completion,
)
from specatom_hs.elaboration_protocol import ElaborationRequest, ProviderProvenance
from specatom_hs.projects import ArtifactRef, content_sha256


class ElaborationPromptTests(unittest.TestCase):
    def setUp(self):
        source = "***requirements***\n- [id:R-1] :Thing: works.\n"
        self.request = ElaborationRequest(ArtifactRef("original-spec:v1", content_sha256(source)), source, "No dependencies.")
        self.provenance = ProviderProvenance("fake", "model-a", "i-1", 12, 24, "2026-08-14T11:22:00Z")

    def test_canonical_prompt_carries_exact_request_and_constraints(self):
        prompt = build_elaboration_prompt(self.request)
        encoded = elaboration_prompt_to_dict(prompt)
        self.assertEqual("plain2metta-elaboration-prompt/v1", encoded["schema"])
        self.assertEqual(["system", "user"], [message["role"] for message in encoded["messages"]])
        self.assertIn("not code, MeTTa, or JSON", encoded["messages"][0]["content"])
        self.assertIn("[id:R-1]", encoded["messages"][1]["content"])
        self.assertFalse(encoded["response_schema"]["additionalProperties"])

    def test_strict_completion_becomes_exact_bound_response(self):
        text = json.dumps({"schema": RESPONSE_SCHEMA, "elaborated_spec": "***requirements***\n- [id:R-1] Detail.", "test_spec": "***tests***\n- [covers:R-1] Verify."})
        response = parse_elaboration_completion(self.request, ProviderCompletion(text, self.provenance))
        self.assertEqual(self.provenance, response.provenance)
        self.assertIn("[covers:R-1]", response.test_spec)

    def test_malformed_or_expanded_completion_fails_closed(self):
        bad = (
            "not json",
            json.dumps({"schema": RESPONSE_SCHEMA, "elaborated_spec": "x"}),
            json.dumps({"schema": RESPONSE_SCHEMA, "elaborated_spec": "x", "test_spec": "y", "extra": 1}),
            json.dumps({"schema": "wrong", "elaborated_spec": "x", "test_spec": "y"}),
            json.dumps({"schema": RESPONSE_SCHEMA, "elaborated_spec": " ", "test_spec": "y"}),
        )
        for text in bad:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_elaboration_completion(self.request, ProviderCompletion(text, self.provenance))

    def test_prompt_mutation_is_rejected(self):
        prompt = build_elaboration_prompt(self.request)
        with self.assertRaises(ValueError):
            elaboration_prompt_to_dict(replace(prompt, messages=prompt.messages[:1]))
        with self.assertRaises(ValueError):
            elaboration_prompt_to_dict(replace(prompt, request_hash="sha256:" + "0" * 64))


if __name__ == "__main__":
    unittest.main()

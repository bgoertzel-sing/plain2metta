import copy
import unittest

from specatom_hs.elaboration_protocol import (
    ElaborationRequest, ElaborationResponse, ProviderProvenance, ValidationSummary,
    admit_elaboration, elaboration_admission_from_dict, elaboration_admission_to_dict, elaboration_request_from_dict,
    elaboration_request_hash, elaboration_request_to_dict, elaboration_response_from_dict,
    elaboration_response_hash, elaboration_response_to_dict, validate_elaboration_response,
)
from specatom_hs.projects import ArtifactRef, content_sha256


class ElaborationProtocolTests(unittest.TestCase):
    def setUp(self):
        self.source = "***requirements***\n- [id:R-1] A :User: signs in.\n"
        self.request = ElaborationRequest(
            ArtifactRef("artifact-source", content_sha256(self.source)), self.source,
            "Use reviewable English only.",
        )
        self.response = ElaborationResponse(
            elaboration_request_hash(self.request),
            "***requirements***\n- [id:R-1] A :User: signs in with a valid session.\n",
            "***acceptance tests***\n- [covers:R-1] A valid user can sign in.\n",
            ProviderProvenance("openclaw", "model-x", "interaction-1", 20, 30, "2026-08-14T10:30:00Z"),
        )
        self.clean = ValidationSummary(10, 0, 2, 0)

    def test_messages_round_trip_canonically_and_bind_exact_bytes(self):
        self.assertEqual(self.request, elaboration_request_from_dict(elaboration_request_to_dict(self.request)))
        self.assertEqual(self.response, elaboration_response_from_dict(elaboration_response_to_dict(self.response)))
        validate_elaboration_response(self.response, self.request)
        self.assertRegex(elaboration_request_hash(self.request), r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(elaboration_response_hash(self.response), r"^sha256:[0-9a-f]{64}$")

    def test_admission_requires_marker_preservation_and_clean_validation(self):
        admission = admit_elaboration(self.request, self.response, self.clean, self.clean)
        self.assertTrue(admission.admitted)
        self.assertEqual(("[id:R-1]", ":User:"), admission.preserved_markers)
        encoded = elaboration_admission_to_dict(admission)
        self.assertEqual(admission, elaboration_admission_from_dict(encoded))

        missing = ElaborationResponse(
            self.response.request_hash, "No identifiers here.", "No coverage here.", self.response.provenance
        )
        self.assertFalse(admit_elaboration(self.request, missing, self.clean, self.clean).admitted)
        blocked = ValidationSummary(9, 0, 3, 1)
        self.assertFalse(admit_elaboration(self.request, self.response, blocked, self.clean).admitted)
        encoded["admitted"] = False
        with self.assertRaises(ValueError):
            elaboration_admission_from_dict(encoded)

    def test_forged_stale_and_malformed_messages_fail_closed(self):
        stale = ElaborationResponse("sha256:" + "0" * 64, self.response.elaborated_spec, self.response.test_spec, self.response.provenance)
        with self.assertRaises(ValueError):
            validate_elaboration_response(stale, self.request)
        request_data = elaboration_request_to_dict(self.request)
        request_data["source_text"] += "changed"
        with self.assertRaises(ValueError):
            elaboration_request_from_dict(request_data)
        response_data = elaboration_response_to_dict(self.response)
        response_data["provenance"]["input_tokens"] = -1
        with self.assertRaises(ValueError):
            elaboration_response_from_dict(response_data)

    def test_unknown_fields_and_incomplete_provenance_fail_closed(self):
        for target in (elaboration_request_to_dict(self.request), elaboration_response_to_dict(self.response)):
            with self.subTest(keys=tuple(target)):
                expanded = copy.deepcopy(target)
                expanded["execute"] = True
                parser = elaboration_request_from_dict if "source" in expanded else elaboration_response_from_dict
                with self.assertRaises(ValueError):
                    parser(expanded)
        incomplete = elaboration_response_to_dict(self.response)
        del incomplete["provenance"]["model"]
        with self.assertRaises(ValueError):
            elaboration_response_from_dict(incomplete)

    def test_protocol_has_no_provider_invocation_capability(self):
        import specatom_hs.elaboration_protocol as protocol
        for name in ("invoke", "call", "retry", "execute", "persist", "elaborate"):
            self.assertFalse(hasattr(protocol, name))


if __name__ == "__main__":
    unittest.main()

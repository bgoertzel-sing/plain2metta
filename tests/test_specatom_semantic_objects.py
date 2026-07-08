import unittest

from specatom_hs.backends.petta import emit_reified_atoms
from specatom_hs.passes import compile_source
from specatom_hs.schema import CheckStatus, Role


class SemanticObjectTests(unittest.TestCase):
    def test_explicit_semantic_objects_are_created_with_provenance(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R1] User login works. Scope: authenticated browser users. "
            "Evidence: product requirement R1. "
            "Interpretation: login means credential verification succeeds. "
            "Epistemic status: observed. Bridge: SUMO.Authentication as related.\n"
            "***acceptance tests***\n"
            "- [covers:R1] Login succeeds for a valid user.\n",
            "semantic.plain",
        )
        roles = {obj.role for obj in doc.objects}
        self.assertIn(Role.SCOPE_OBJECT, roles)
        self.assertIn(Role.EPISTEMIC_STATUS_OBJECT, roles)
        self.assertIn(Role.EVIDENCE_OBJECT, roles)
        self.assertIn(Role.INTERPRETATION_OBJECT, roles)
        self.assertIn(Role.BRIDGE_OBJECT, roles)

        for role in [Role.SCOPE_OBJECT, Role.EPISTEMIC_STATUS_OBJECT, Role.EVIDENCE_OBJECT, Role.INTERPRETATION_OBJECT, Role.BRIDGE_OBJECT]:
            obj = next(obj for obj in doc.objects if obj.role == role)
            self.assertIsNotNone(obj.source_span_id)
            self.assertTrue(any(fact[0] == "SourceItem" for fact in obj.facts))

        interpretation = next(obj for obj in doc.objects if obj.role == Role.INTERPRETATION_OBJECT)
        self.assertTrue(any(fact[0] == "InterpretationEvidence" for fact in interpretation.facts))
        self.assertTrue(any(check.property == "interpretation-has-explicit-evidence" and check.status == CheckStatus.PASS for check in doc.checks))
        self.assertTrue(any(check.property == "bridge-profile-supported" and check.status == CheckStatus.PASS for check in doc.checks))

    def test_incomplete_semantic_support_becomes_unknown_questions(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R2] Export data. Interpretation: export means sending all records. "
            "Epistemic status: speculative. Bridge: OpenCog.AtomSpace as identical.\n"
            "***acceptance tests***\n"
            "- [covers:R2] Export job completes.\n",
            "semantic_unknown.plain",
        )
        checks = {(check.property, check.status, check.evidence) for check in doc.checks}
        self.assertTrue(any(prop == "interpretation-has-explicit-evidence" and status == CheckStatus.UNKNOWN for prop, status, _ in checks))
        self.assertTrue(any(prop == "epistemic-status-supported" and status == CheckStatus.UNKNOWN for prop, status, evidence in checks if "speculative" in evidence))
        self.assertTrue(any(prop == "bridge-profile-supported" and status == CheckStatus.UNKNOWN for prop, status, evidence in checks if "opencog" in evidence))
        question_predicates = {fact[0] for obj in doc.objects if obj.role == Role.QUESTION_OBJECT for fact in obj.facts}
        self.assertIn("MissingInterpretationEvidence", question_predicates)
        self.assertIn("UnsupportedEpistemicStatus", question_predicates)
        self.assertIn("UnsupportedBridgeOntology", question_predicates)

    def test_arbitrary_unsupported_bridge_ontology_still_becomes_reviewable_object(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R6] Export atoms. Evidence: design note. Bridge: OpenCog.AtomSpace as analogy.\n"
            "***acceptance tests***\n"
            "- [covers:R6] Atom export completes.\n",
            "semantic_bridge_unknown.plain",
        )
        bridge = next(obj for obj in doc.objects if obj.role == Role.BRIDGE_OBJECT)
        bridge_facts = {fact[0]: fact for fact in bridge.facts}

        self.assertEqual(bridge_facts["BridgeOntology"][2], "opencog")
        self.assertEqual(bridge_facts["BridgeTarget"][2], "AtomSpace")
        self.assertTrue(any(check.property == "bridge-profile-supported" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(
            any(
                obj.role == Role.QUESTION_OBJECT and any(fact == ("UnsupportedBridgeOntology", obj.id, "opencog") for fact in obj.facts)
                for obj in doc.objects
            )
        )

    def test_identity_bridge_relation_becomes_review_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R9] Model session state. Evidence: design note. Bridge: SUMO.Process as identical.\n"
            "***acceptance tests***\n"
            "- [covers:R9] Session state can be inspected.\n",
            "semantic_bridge_relation_unknown.plain",
        )
        bridge = next(obj for obj in doc.objects if obj.role == Role.BRIDGE_OBJECT)
        bridge_facts = {fact[0]: fact for fact in bridge.facts}

        self.assertEqual(bridge_facts["BridgeRelation"][2], "identical")
        self.assertTrue(any(check.property == "bridge-relation-conservative" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(
            any(
                obj.role == Role.QUESTION_OBJECT and any(fact == ("UnsupportedBridgeRelation", obj.id, "identical") for fact in obj.facts)
                for obj in doc.objects
            )
        )
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(UnsupportedBridgeRelation ", "\n".join(atoms))
        self.assertFalse(any("UnsupportedBridgeRelation" in refusal.reason for refusal in refusals))

    def test_explicit_revision_marker_becomes_source_spanned_object(self):
        source = (
            "***requirements***\n"
            "- [id:R11] Keep the schema stable. Evidence: migration note. "
            "Revision: replaces the old event payload wording.\n"
            "***acceptance tests***\n"
            "- [covers:R11] Existing payload examples still compile.\n"
        )
        doc = compile_source(source, "semantic_revision.plain")
        revision = next(obj for obj in doc.objects if obj.role == Role.REVISION_OBJECT)
        facts = {fact[0]: fact for fact in revision.facts}
        span = next(span for span in doc.spans if span.id == revision.source_span_id)

        self.assertEqual(facts["Revision"][2], facts["Revises"][2])
        self.assertEqual(facts["RevisionText"][2], "replaces the old event payload wording")
        self.assertEqual(doc.files[0].text[span.start_byte:span.end_byte], "Revision: replaces the old event payload wording")
        self.assertTrue(any(check.property == "revision-has-source-provenance" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Revision ", joined)
        self.assertIn("(RevisionText ", joined)
        self.assertFalse(any("Revision" in refusal.reason for refusal in refusals))

    def test_petta_profile_exports_supported_semantic_facts(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R3] Store audit events. Scope: audit administrators. Evidence: audit policy. "
            "Interpretation: audit events are review records. Bridge: EXPO.ValidationExperiment via analogy.\n"
            "***acceptance tests***\n"
            "- [covers:R3] Audit events can be queried.\n",
            "semantic_petta.plain",
        )
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Scope ", joined)
        self.assertIn("(Evidence ", joined)
        self.assertIn("(Interpretation ", joined)
        self.assertIn("(Bridge ", joined)
        self.assertIn(" bridge-profile-supported ", joined)
        self.assertFalse(any("Scope" in refusal.reason or "Evidence" in refusal.reason or "Bridge" in refusal.reason for refusal in refusals))

    def test_explicit_confidence_marker_normalizes_and_exports(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R7] Recommend a reviewer. Evidence: calibration run. Confidence: 83%. "
            "Interpretation: reviewer score is a heuristic ranking.\n"
            "***acceptance tests***\n"
            "- [covers:R7] Recommendation includes a reviewer id.\n",
            "semantic_confidence.plain",
        )
        confidence = next(obj for obj in doc.objects if any(fact[0] == "Confidence" for fact in obj.facts))
        facts = {fact[0]: fact for fact in confidence.facts}

        self.assertEqual(facts["ConfidenceValue"][2], "0.83")
        self.assertTrue(any(check.property == "confidence-value-in-unit-interval" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Confidence ", joined)
        self.assertIn("(ConfidenceValue ", joined)
        self.assertFalse(any("Confidence" in refusal.reason for refusal in refusals))

    def test_out_of_range_confidence_becomes_review_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R8] Rank candidates. Confidence: 120%. Evidence: informal guess.\n"
            "***acceptance tests***\n"
            "- [covers:R8] Ranking returns candidates.\n",
            "semantic_confidence_unknown.plain",
        )

        self.assertTrue(any(check.property == "confidence-value-in-unit-interval" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(
            any(
                obj.role == Role.QUESTION_OBJECT and any(fact == ("UnsupportedConfidenceValue", obj.id, "120%") for fact in obj.facts)
                for obj in doc.objects
            )
        )

    def test_non_numeric_confidence_becomes_reviewable_object_and_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R10] Triage alerts. Confidence: high. Evidence: operator note.\n"
            "***acceptance tests***\n"
            "- [covers:R10] Alert includes triage reason.\n",
            "semantic_confidence_nonnumeric.plain",
        )
        confidence = next(obj for obj in doc.objects if any(fact[0] == "Confidence" for fact in obj.facts))

        self.assertFalse(any(fact[0] == "ConfidenceValue" for fact in confidence.facts))
        self.assertTrue(
            any(
                check.property == "confidence-value-in-unit-interval"
                and check.status == CheckStatus.UNKNOWN
                and "non-numeric confidence scale: high" in check.evidence
                for check in doc.checks
            )
        )
        self.assertTrue(
            any(
                obj.role == Role.QUESTION_OBJECT and any(fact == ("UnsupportedConfidenceValue", obj.id, "high") for fact in obj.facts)
                for obj in doc.objects
            )
        )
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(UnsupportedConfidenceValue ", "\n".join(atoms))
        self.assertFalse(any("UnsupportedConfidenceValue" in refusal.reason for refusal in refusals))

    def test_semantic_marker_spans_follow_repeated_raw_text_occurrences(self):
        source = (
            "***requirements***\n"
            "- [id:R4] Explain release gate. Evidence: release checklist. "
            "Evidence: QA signoff. Interpretation: release gate means checklist plus signoff.\n"
            "***acceptance tests***\n"
            "- [covers:R4] Release gate rejects missing signoff.\n"
        )
        doc = compile_source(source, "semantic_repeated.plain")
        file_text = doc.files[0].text
        evidence_slices = []
        for obj in doc.objects:
            if obj.role != Role.EVIDENCE_OBJECT:
                continue
            span = next(span for span in doc.spans if span.id == obj.source_span_id)
            evidence_slices.append(file_text[span.start_byte:span.end_byte])

        self.assertEqual(evidence_slices, ["Evidence: release checklist", "Evidence: QA signoff"])

    def test_semantic_marker_spans_align_on_continuation_lines(self):
        source = (
            "***requirements***\n"
            "- [id:R5] Explain delayed review.\n"
            "  Evidence: second-line review note. Interpretation: delayed review is explicit.\n"
            "***acceptance tests***\n"
            "- [covers:R5] Review note appears.\n"
        )
        doc = compile_source(source, "semantic_continuation.plain")
        file_text = doc.files[0].text
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT)
        span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(file_text[span.start_byte:span.end_byte], "Evidence: second-line review note")
        self.assertEqual(span.start_line, 3)


if __name__ == "__main__":
    unittest.main()

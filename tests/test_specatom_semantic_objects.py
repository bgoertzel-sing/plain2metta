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

    def test_interpretation_marker_preserves_file_path_before_following_marker(self):
        source = (
            "***requirements***\n"
            "- [id:R29] Keep interpretation references inspectable. "
            "Evidence: reviewer note. "
            "Interpretation: see docs/interpretation.v1.md and out/semantic-map.metta. "
            "Bridge: Hyperseed.Concept via related.\n"
            "***acceptance tests***\n"
            "- [covers:R29] Interpretation references are exported.\n"
        )
        doc = compile_source(source, "semantic_interpretation_boundary.plain")
        interpretation = next(obj for obj in doc.objects if obj.role == Role.INTERPRETATION_OBJECT)
        bridge = next(obj for obj in doc.objects if obj.role == Role.BRIDGE_OBJECT)
        interp_facts = {fact[0]: fact for fact in interpretation.facts}
        interp_span = next(span for span in doc.spans if span.id == interpretation.source_span_id)
        bridge_span = next(span for span in doc.spans if span.id == bridge.source_span_id)

        self.assertEqual(interp_facts["InterpretationText"][2], "see docs/interpretation.v1.md and out/semantic-map.metta")
        self.assertEqual(doc.files[0].text[interp_span.start_byte:interp_span.end_byte], "Interpretation: see docs/interpretation.v1.md and out/semantic-map.metta")
        self.assertEqual(doc.files[0].text[bridge_span.start_byte:bridge_span.end_byte], "Bridge: Hyperseed.Concept via related")
        self.assertLess(interp_span.end_byte, bridge_span.start_byte)
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(InterpretationText ", joined)
        self.assertIn("(BridgeTarget ", joined)
        self.assertFalse(any("Interpretation" in refusal.reason or "Bridge" in refusal.reason for refusal in refusals))

    def test_scope_and_confidence_markers_preserve_periods_before_following_marker(self):
        source = (
            "***requirements***\n"
            "- [id:R30] Keep scoped profile notes inspectable. "
            "Scope: profile docs/v0.2.review.md and out/profile-scope.metta. "
            "Confidence: 83%. Evidence: profile review.\n"
            "***acceptance tests***\n"
            "- [covers:R30] Scope and confidence atoms are exported.\n"
        )
        doc = compile_source(source, "semantic_scope_confidence_boundary.plain")
        scope = next(obj for obj in doc.objects if obj.role == Role.SCOPE_OBJECT)
        confidence = next(
            obj
            for obj in doc.objects
            if obj.role == Role.EPISTEMIC_STATUS_OBJECT and any(fact[0] == "Confidence" for fact in obj.facts)
        )
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT)
        scope_facts = {fact[0]: fact for fact in scope.facts}
        confidence_facts = {fact[0]: fact for fact in confidence.facts}
        scope_span = next(span for span in doc.spans if span.id == scope.source_span_id)
        confidence_span = next(span for span in doc.spans if span.id == confidence.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(scope_facts["ScopeText"][2], "profile docs/v0.2.review.md and out/profile-scope.metta")
        self.assertEqual(confidence_facts["ConfidenceValue"][2], "0.83")
        self.assertEqual(doc.files[0].text[scope_span.start_byte:scope_span.end_byte], "Scope: profile docs/v0.2.review.md and out/profile-scope.metta")
        self.assertEqual(doc.files[0].text[confidence_span.start_byte:confidence_span.end_byte], "Confidence: 83%")
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: profile review")
        self.assertLess(scope_span.end_byte, confidence_span.start_byte)
        self.assertLess(confidence_span.end_byte, evidence_span.start_byte)
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(ScopeText ", joined)
        self.assertIn("(ConfidenceValue ", joined)
        self.assertFalse(any("Scope" in refusal.reason or "Confidence" in refusal.reason for refusal in refusals))

    def test_epistemic_status_marker_stops_before_following_evidence_marker(self):
        source = (
            "***requirements***\n"
            "- [id:R31] Keep epistemic statuses separate from review evidence. "
            "Epistemic status: verified. Evidence: docs/status.v1.md.\n"
            "***acceptance tests***\n"
            "- [covers:R31] Epistemic status and evidence atoms are exported separately.\n"
        )
        doc = compile_source(source, "semantic_epistemic_boundary.plain")
        epistemic = next(
            obj
            for obj in doc.objects
            if obj.role == Role.EPISTEMIC_STATUS_OBJECT and any(fact[0] == "EpistemicStatus" for fact in obj.facts)
        )
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT)
        epistemic_facts = {fact[0]: fact for fact in epistemic.facts}
        epistemic_span = next(span for span in doc.spans if span.id == epistemic.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(epistemic_facts["EpistemicStatus"][2], "verified")
        self.assertEqual(doc.files[0].text[epistemic_span.start_byte:epistemic_span.end_byte], "Epistemic status: verified")
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: docs/status.v1.md")
        self.assertLess(epistemic_span.end_byte, evidence_span.start_byte)
        self.assertTrue(any(check.property == "epistemic-status-supported" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(EpistemicStatus ", "\n".join(atoms))
        self.assertFalse(any("EpistemicStatus" in refusal.reason for refusal in refusals))

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

    def test_explicit_decision_marker_becomes_source_spanned_proposition(self):
        source = (
            "***requirements***\n"
            "- [id:R23] Keep exports conservative. Decision: emit reified atoms only, not executable skeletons. "
            "Evidence: backend profile note.\n"
            "***acceptance tests***\n"
            "- [covers:R23] RawTextOnly objects are refused by executable skeleton export.\n"
        )
        doc = compile_source(source, "semantic_decision.plain")
        decision = next(obj for obj in doc.objects if any(fact[0] == "Decision" for fact in obj.facts))
        facts = {fact[0]: fact for fact in decision.facts}
        span = next(span for span in doc.spans if span.id == decision.source_span_id)

        self.assertEqual(decision.role, Role.PROPOSITION_OBJECT)
        self.assertEqual(facts["DecisionText"][2], "emit reified atoms only, not executable skeletons")
        self.assertEqual(facts["Decision"][2], facts["DecidesFor"][2])
        self.assertEqual(doc.files[0].text[span.start_byte:span.end_byte], "Decision: emit reified atoms only, not executable skeletons")
        self.assertTrue(any(check.property == "decision-has-source-provenance" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Decision ", joined)
        self.assertIn("(DecisionText ", joined)
        self.assertFalse(any("Decision" in refusal.reason for refusal in refusals))

    def test_explicit_outcome_marker_becomes_source_spanned_proposition(self):
        source = (
            "***requirements***\n"
            "- [id:R24] Keep diagnostics inspectable. Decision: emit grouped review atoms. "
            "Outcome: reviewers can compare the validation summary without executing code. "
            "Evidence: diagnostics fixture.\n"
            "***acceptance tests***\n"
            "- [covers:R24] Diagnostics include Pass Unknown and question counts.\n"
        )
        doc = compile_source(source, "semantic_outcome.plain")
        outcome = next(obj for obj in doc.objects if any(fact[0] == "Outcome" for fact in obj.facts))
        facts = {fact[0]: fact for fact in outcome.facts}
        span = next(span for span in doc.spans if span.id == outcome.source_span_id)

        self.assertEqual(outcome.role, Role.PROPOSITION_OBJECT)
        self.assertEqual(facts["OutcomeText"][2], "reviewers can compare the validation summary without executing code")
        self.assertEqual(facts["Outcome"][2], facts["OutcomeFor"][2])
        self.assertEqual(doc.files[0].text[span.start_byte:span.end_byte], "Outcome: reviewers can compare the validation summary without executing code")
        self.assertTrue(any(check.property == "outcome-has-source-provenance" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Outcome ", joined)
        self.assertIn("(OutcomeText ", joined)
        self.assertFalse(any("Outcome" in refusal.reason for refusal in refusals))

    def test_explicit_counterexample_marker_becomes_source_spanned_validation_object(self):
        source = (
            "***requirements***\n"
            "- [id:R39] Preserve falsification examples. "
            "Counterexample: empty input produces no atoms. "
            "Evidence: tests/test_counterexample.py::test_empty_input. "
            "Outcome: reviewer sees the counterexample separately from evidence.\n"
            "***acceptance tests***\n"
            "- [covers:R39] Counterexample atoms are exported.\n"
        )
        doc = compile_source(source, "semantic_counterexample.plain")
        counterexample = next(obj for obj in doc.objects if any(fact[0] == "Counterexample" for fact in obj.facts))
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT)
        facts = {fact[0]: fact for fact in counterexample.facts}
        span = next(span for span in doc.spans if span.id == counterexample.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(counterexample.role, Role.VALIDATION_OBJECT)
        self.assertEqual(facts["CounterexampleText"][2], "empty input produces no atoms")
        self.assertEqual(facts["Counterexample"][2], facts["CounterexampleFor"][2])
        self.assertEqual(doc.files[0].text[span.start_byte:span.end_byte], "Counterexample: empty input produces no atoms")
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: tests/test_counterexample.py::test_empty_input")
        self.assertLess(span.end_byte, evidence_span.start_byte)
        self.assertTrue(any(check.property == "counterexample-has-source-provenance" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Counterexample ", joined)
        self.assertIn("(CounterexampleText ", joined)
        self.assertFalse(any("Counterexample" in refusal.reason for refusal in refusals))

    def test_explicit_witness_marker_becomes_reviewable_backend_artifact(self):
        source = (
            "***requirements***\n"
            "- [id:R12] Keep CLI output reproducible. Evidence: demo run. "
            "Witness: tests/test_cli.py::CliTests and out/demo.metta.\n"
            "***acceptance tests***\n"
            "- [covers:R12] Demo output regenerates.\n"
        )
        doc = compile_source(source, "semantic_witness.plain")
        witness = next(obj for obj in doc.objects if obj.role == Role.BACKEND_ARTIFACT)
        facts = {fact[0]: fact for fact in witness.facts}
        span = next(span for span in doc.spans if span.id == witness.source_span_id)

        self.assertEqual(facts["Witness"][2], facts["WitnessFor"][2])
        self.assertEqual(facts["WitnessText"][2], "tests/test_cli.py::CliTests and out/demo.metta")
        self.assertEqual(doc.files[0].text[span.start_byte:span.end_byte], "Witness: tests/test_cli.py::CliTests and out/demo.metta")
        self.assertTrue(any(check.property == "witness-artifact-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Witness ", joined)
        self.assertIn("(WitnessText ", joined)
        self.assertFalse(any("Witness" in refusal.reason for refusal in refusals))

    def test_witness_marker_stops_before_following_semantic_marker(self):
        source = (
            "***requirements***\n"
            "- [id:R25] Keep audit evidence inspectable. "
            "Witness: tests/test_cli.py::CliTests and out/demo.metta. "
            "Outcome: reviewer sees the generated atoms.\n"
            "***acceptance tests***\n"
            "- [covers:R25] Audit evidence is listed.\n"
        )
        doc = compile_source(source, "semantic_witness_boundary.plain")
        witness = next(obj for obj in doc.objects if obj.role == Role.BACKEND_ARTIFACT)
        outcome = next(obj for obj in doc.objects if any(fact[0] == "Outcome" for fact in obj.facts))
        witness_facts = {fact[0]: fact for fact in witness.facts}
        witness_span = next(span for span in doc.spans if span.id == witness.source_span_id)
        outcome_span = next(span for span in doc.spans if span.id == outcome.source_span_id)

        self.assertEqual(witness_facts["WitnessText"][2], "tests/test_cli.py::CliTests and out/demo.metta")
        self.assertEqual(doc.files[0].text[witness_span.start_byte:witness_span.end_byte], "Witness: tests/test_cli.py::CliTests and out/demo.metta")
        self.assertEqual(doc.files[0].text[outcome_span.start_byte:outcome_span.end_byte], "Outcome: reviewer sees the generated atoms")
        self.assertLess(witness_span.end_byte, outcome_span.start_byte)
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(WitnessText ", joined)
        self.assertIn("(OutcomeText ", joined)
        self.assertFalse(any("Witness" in refusal.reason or "Outcome" in refusal.reason for refusal in refusals))

    def test_witness_marker_accepts_yaml_and_shell_artifact_paths(self):
        source = (
            "***requirements***\n"
            "- [id:R33] Preserve operational witness artifacts. "
            "Witness: scripts/demo.sh and docs/capacity.v1.yaml. "
            "Outcome: reviewer sees the artifact manifest.\n"
            "***acceptance tests***\n"
            "- [covers:R33] Witness artifact paths are exported.\n"
        )
        doc = compile_source(source, "semantic_witness_yaml_shell.plain")
        witness = next(obj for obj in doc.objects if obj.role == Role.BACKEND_ARTIFACT)
        witness_facts = {fact[0]: fact for fact in witness.facts}
        witness_span = next(span for span in doc.spans if span.id == witness.source_span_id)

        self.assertEqual(witness_facts["WitnessText"][2], "scripts/demo.sh and docs/capacity.v1.yaml")
        self.assertEqual(doc.files[0].text[witness_span.start_byte:witness_span.end_byte], "Witness: scripts/demo.sh and docs/capacity.v1.yaml")
        self.assertTrue(any(check.property == "witness-artifact-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        self.assertFalse(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingWitnessArtifact" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(WitnessText ", joined)
        self.assertFalse(any("Witness" in refusal.reason for refusal in refusals))

    def test_witness_marker_accepts_extensionless_build_artifacts(self):
        source = (
            "***requirements***\n"
            "- [id:R35] Preserve extensionless build artifacts. "
            "Witness: Dockerfile and Makefile. "
            "Outcome: reviewer sees build entrypoints.\n"
            "***acceptance tests***\n"
            "- [covers:R35] Extensionless build artifacts are exported.\n"
        )
        doc = compile_source(source, "semantic_witness_extensionless_build.plain")
        witness = next(obj for obj in doc.objects if obj.role == Role.BACKEND_ARTIFACT)
        witness_facts = {fact[0]: fact for fact in witness.facts}
        witness_span = next(span for span in doc.spans if span.id == witness.source_span_id)

        self.assertEqual(witness_facts["WitnessText"][2], "Dockerfile and Makefile")
        self.assertEqual(doc.files[0].text[witness_span.start_byte:witness_span.end_byte], "Witness: Dockerfile and Makefile")
        self.assertTrue(any(check.property == "witness-artifact-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        self.assertFalse(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingWitnessArtifact" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(WitnessText ", joined)
        self.assertFalse(any("Witness" in refusal.reason for refusal in refusals))

    def test_todo_witness_marker_becomes_blocking_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R13] Generate a worker skeleton. Witness: TODO generate code later.\n"
            "***acceptance tests***\n"
            "- [covers:R13] Skeleton path is listed.\n",
            "semantic_witness_unknown.plain",
        )

        self.assertTrue(any(check.property == "witness-artifact-reviewable" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(
            any(
                obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingWitnessArtifact" for fact in obj.facts)
                for obj in doc.objects
            )
        )
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(MissingWitnessArtifact ", "\n".join(atoms))
        self.assertFalse(any("MissingWitnessArtifact" in refusal.reason for refusal in refusals))

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

    def test_explicit_rationale_marker_becomes_source_spanned_explanation(self):
        source = (
            "***requirements***\n"
            "- [id:R14] Keep review gates conservative. Rationale: prevents raw text from being treated as executable semantics. "
            "Evidence: design review note.\n"
            "***acceptance tests***\n"
            "- [covers:R14] RawTextOnly objects are refused by executable skeleton export.\n"
        )
        doc = compile_source(source, "semantic_rationale.plain")
        rationale = next(obj for obj in doc.objects if any(fact[0] == "Rationale" for fact in obj.facts))
        facts = {fact[0]: fact for fact in rationale.facts}
        span = next(span for span in doc.spans if span.id == rationale.source_span_id)

        self.assertEqual(facts["RationaleText"][2], "prevents raw text from being treated as executable semantics")
        self.assertEqual(doc.files[0].text[span.start_byte:span.end_byte], "Rationale: prevents raw text from being treated as executable semantics")
        self.assertTrue(any(check.property == "rationale-has-source-provenance" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Rationale ", joined)
        self.assertIn("(RationaleText ", joined)
        self.assertFalse(any("Rationale" in refusal.reason for refusal in refusals))

    def test_rationale_marker_preserves_file_path_before_following_marker(self):
        source = (
            "***requirements***\n"
            "- [id:R28] Keep design reasons inspectable. "
            "Rationale: see docs/v01-profile.md and out/design-note.metta. "
            "Evidence: architecture review.\n"
            "***acceptance tests***\n"
            "- [covers:R28] Rationale text is exported.\n"
        )
        doc = compile_source(source, "semantic_rationale_boundary.plain")
        rationale = next(obj for obj in doc.objects if any(fact[0] == "Rationale" for fact in obj.facts))
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT)
        rationale_facts = {fact[0]: fact for fact in rationale.facts}
        rationale_span = next(span for span in doc.spans if span.id == rationale.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(rationale_facts["RationaleText"][2], "see docs/v01-profile.md and out/design-note.metta")
        self.assertEqual(doc.files[0].text[rationale_span.start_byte:rationale_span.end_byte], "Rationale: see docs/v01-profile.md and out/design-note.metta")
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: architecture review")
        self.assertLess(rationale_span.end_byte, evidence_span.start_byte)
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(RationaleText ", joined)
        self.assertIn("(EvidenceText ", joined)
        self.assertFalse(any("Rationale" in refusal.reason or "Evidence" in refusal.reason for refusal in refusals))

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

    def test_evidence_marker_preserves_file_path_before_following_marker(self):
        source = (
            "***requirements***\n"
            "- [id:R27] Keep audit evidence inspectable. "
            "Evidence: tests/test_cli.py::CliTests and out/demo.metta. "
            "Outcome: reviewer sees the generated atoms.\n"
            "***acceptance tests***\n"
            "- [covers:R27] Audit evidence is listed.\n"
        )
        doc = compile_source(source, "semantic_evidence_boundary.plain")
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT)
        outcome = next(obj for obj in doc.objects if any(fact[0] == "Outcome" for fact in obj.facts))
        evidence_facts = {fact[0]: fact for fact in evidence.facts}
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)
        outcome_span = next(span for span in doc.spans if span.id == outcome.source_span_id)

        self.assertEqual(evidence_facts["EvidenceText"][2], "tests/test_cli.py::CliTests and out/demo.metta")
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: tests/test_cli.py::CliTests and out/demo.metta")
        self.assertEqual(doc.files[0].text[outcome_span.start_byte:outcome_span.end_byte], "Outcome: reviewer sees the generated atoms")
        self.assertLess(evidence_span.end_byte, outcome_span.start_byte)
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(EvidenceText ", joined)
        self.assertIn("(OutcomeText ", joined)
        self.assertFalse(any("Evidence" in refusal.reason or "Outcome" in refusal.reason for refusal in refusals))

    def test_explicit_process_and_resource_markers_export_when_reviewable(self):
        source = (
            "***requirements***\n"
            "- [id:R14] Run the nightly import. Process: scheduled cron validates the batch before deploy. "
            "Resource: 2 CPUs, 4GB memory, and dataset snapshot path.\n"
            "***acceptance tests***\n"
            "- [covers:R14] Import job reports validation status.\n"
        )
        doc = compile_source(source, "semantic_process_resource.plain")
        process = next(obj for obj in doc.objects if obj.role == Role.PROCESS_OBJECT)
        resource = next(obj for obj in doc.objects if obj.role == Role.RESOURCE_OBJECT)
        process_facts = {fact[0]: fact for fact in process.facts}
        resource_facts = {fact[0]: fact for fact in resource.facts}

        self.assertEqual(process_facts["ProcessText"][2], "scheduled cron validates the batch before deploy")
        self.assertEqual(resource_facts["ResourceText"][2], "2 CPUs, 4GB memory, and dataset snapshot path")
        self.assertTrue(any(check.property == "process-definition-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        self.assertTrue(any(check.property == "resource-requirement-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Process ", joined)
        self.assertIn("(Resource ", joined)
        self.assertFalse(any("Process" in refusal.reason or "Resource" in refusal.reason for refusal in refusals))

    def test_process_and_resource_markers_preserve_file_paths_before_following_marker(self):
        source = (
            "***requirements***\n"
            "- [id:R32] Keep operational references inspectable. "
            "Process: run scripts/demo.sh and publish out/review.metta. "
            "Resource: file docs/capacity.v1.yaml and 4GB memory. "
            "Evidence: operations review.\n"
            "***acceptance tests***\n"
            "- [covers:R32] Process and resource references are exported.\n"
        )
        doc = compile_source(source, "semantic_process_resource_boundary.plain")
        process = next(obj for obj in doc.objects if obj.role == Role.PROCESS_OBJECT)
        resource = next(obj for obj in doc.objects if obj.role == Role.RESOURCE_OBJECT)
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT)
        process_facts = {fact[0]: fact for fact in process.facts}
        resource_facts = {fact[0]: fact for fact in resource.facts}
        process_span = next(span for span in doc.spans if span.id == process.source_span_id)
        resource_span = next(span for span in doc.spans if span.id == resource.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(process_facts["ProcessText"][2], "run scripts/demo.sh and publish out/review.metta")
        self.assertEqual(resource_facts["ResourceText"][2], "file docs/capacity.v1.yaml and 4GB memory")
        self.assertEqual(doc.files[0].text[process_span.start_byte:process_span.end_byte], "Process: run scripts/demo.sh and publish out/review.metta")
        self.assertEqual(doc.files[0].text[resource_span.start_byte:resource_span.end_byte], "Resource: file docs/capacity.v1.yaml and 4GB memory")
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: operations review")
        self.assertLess(process_span.end_byte, resource_span.start_byte)
        self.assertLess(resource_span.end_byte, evidence_span.start_byte)
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(ProcessText ", joined)
        self.assertIn("(ResourceText ", joined)
        self.assertFalse(any("Process" in refusal.reason or "Resource" in refusal.reason for refusal in refusals))

    def test_process_marker_accepts_script_artifact_without_action_verb(self):
        source = (
            "***requirements***\n"
            "- [id:R37] Keep script-only process declarations reviewable. "
            "Process: scripts/deploy.sh and Makefile. "
            "Evidence: operations review.\n"
            "***acceptance tests***\n"
            "- [covers:R37] Process artifact paths are exported.\n"
        )
        doc = compile_source(source, "semantic_process_artifact_only.plain")
        process = next(obj for obj in doc.objects if obj.role == Role.PROCESS_OBJECT)
        facts = {fact[0]: fact for fact in process.facts}
        span = next(span for span in doc.spans if span.id == process.source_span_id)

        self.assertEqual(facts["ProcessText"][2], "scripts/deploy.sh and Makefile")
        self.assertEqual(doc.files[0].text[span.start_byte:span.end_byte], "Process: scripts/deploy.sh and Makefile")
        self.assertTrue(any(check.property == "process-definition-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        self.assertFalse(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingProcessDefinition" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(ProcessText ", joined)
        self.assertFalse(any("Process" in refusal.reason for refusal in refusals))

    def test_resource_marker_accepts_artifact_paths_without_resource_keyword(self):
        source = (
            "***requirements***\n"
            "- [id:R38] Keep capacity artifact declarations reviewable. "
            "Resource: docs/capacity.v1.yaml and infra/limits.toml. "
            "Evidence: operations review.\n"
            "***acceptance tests***\n"
            "- [covers:R38] Resource artifact paths are exported.\n"
        )
        doc = compile_source(source, "semantic_resource_artifact_only.plain")
        resource = next(obj for obj in doc.objects if obj.role == Role.RESOURCE_OBJECT)
        facts = {fact[0]: fact for fact in resource.facts}
        span = next(span for span in doc.spans if span.id == resource.source_span_id)

        self.assertEqual(facts["ResourceText"][2], "docs/capacity.v1.yaml and infra/limits.toml")
        self.assertEqual(doc.files[0].text[span.start_byte:span.end_byte], "Resource: docs/capacity.v1.yaml and infra/limits.toml")
        self.assertTrue(any(check.property == "resource-requirement-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        self.assertFalse(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingResourceRequirement" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(ResourceText ", joined)
        self.assertFalse(any("Resource" in refusal.reason for refusal in refusals))

    def test_process_and_resource_placeholders_become_blocking_questions(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R15] Provision the reviewer. Process: TODO decide later. Resource: unknown capacity.\n"
            "***acceptance tests***\n"
            "- [covers:R15] Reviewer provisioning is reported.\n",
            "semantic_process_resource_unknown.plain",
        )

        self.assertTrue(any(check.property == "process-definition-reviewable" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(check.property == "resource-requirement-reviewable" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(
            any(
                obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingProcessDefinition" for fact in obj.facts)
                for obj in doc.objects
            )
        )
        self.assertTrue(
            any(
                obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingResourceRequirement" for fact in obj.facts)
                for obj in doc.objects
            )
        )
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(MissingProcessDefinition ", joined)
        self.assertIn("(MissingResourceRequirement ", joined)
        self.assertFalse(any("MissingProcessDefinition" in refusal.reason or "MissingResourceRequirement" in refusal.reason for refusal in refusals))

    def test_explicit_dependency_marker_exports_when_reviewable(self):
        source = (
            "***requirements***\n"
            "- [id:R25] Load reviewer context. Dependency: Redis cache service and config/context.yaml. "
            "Outcome: context load is deterministic.\n"
            "***acceptance tests***\n"
            "- [covers:R25] Context loader reports dependency status.\n"
        )
        doc = compile_source(source, "semantic_dependency.plain")
        dependency = next(obj for obj in doc.objects if any(fact[0] == "Dependency" for fact in obj.facts))
        facts = {fact[0]: fact for fact in dependency.facts}
        span = next(span for span in doc.spans if span.id == dependency.source_span_id)

        self.assertEqual(dependency.role, Role.RESOURCE_OBJECT)
        self.assertEqual(facts["DependencyText"][2], "Redis cache service and config/context.yaml")
        self.assertEqual(facts["Dependency"][2], facts["DependencyFor"][2])
        self.assertEqual(doc.files[0].text[span.start_byte:span.end_byte], "Dependency: Redis cache service and config/context.yaml")
        self.assertTrue(any(check.property == "dependency-requirement-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Dependency ", joined)
        self.assertIn("(DependencyText ", joined)
        self.assertFalse(any("Dependency" in refusal.reason for refusal in refusals))

    def test_dependency_marker_accepts_script_and_config_artifact_paths(self):
        source = (
            "***requirements***\n"
            "- [id:R34] Load deployment helper artifacts. "
            "Dependency: scripts/bootstrap.sh and pyproject.toml. "
            "Outcome: dependency manifest remains reviewable.\n"
            "***acceptance tests***\n"
            "- [covers:R34] Dependency artifact paths are exported.\n"
        )
        doc = compile_source(source, "semantic_dependency_script_config.plain")
        dependency = next(obj for obj in doc.objects if any(fact[0] == "Dependency" for fact in obj.facts))
        facts = {fact[0]: fact for fact in dependency.facts}
        span = next(span for span in doc.spans if span.id == dependency.source_span_id)

        self.assertEqual(facts["DependencyText"][2], "scripts/bootstrap.sh and pyproject.toml")
        self.assertEqual(doc.files[0].text[span.start_byte:span.end_byte], "Dependency: scripts/bootstrap.sh and pyproject.toml")
        self.assertTrue(any(check.property == "dependency-requirement-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        self.assertFalse(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingDependencyDetail" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(DependencyText ", joined)
        self.assertFalse(any("Dependency" in refusal.reason for refusal in refusals))

    def test_dependency_marker_accepts_extensionless_build_artifacts(self):
        source = (
            "***requirements***\n"
            "- [id:R36] Declare container build dependencies. "
            "Dependency: Dockerfile and Makefile. "
            "Outcome: dependency manifest remains reviewable.\n"
            "***acceptance tests***\n"
            "- [covers:R36] Extensionless build dependencies are exported.\n"
        )
        doc = compile_source(source, "semantic_dependency_extensionless_build.plain")
        dependency = next(obj for obj in doc.objects if any(fact[0] == "Dependency" for fact in obj.facts))
        facts = {fact[0]: fact for fact in dependency.facts}
        span = next(span for span in doc.spans if span.id == dependency.source_span_id)

        self.assertEqual(facts["DependencyText"][2], "Dockerfile and Makefile")
        self.assertEqual(doc.files[0].text[span.start_byte:span.end_byte], "Dependency: Dockerfile and Makefile")
        self.assertTrue(any(check.property == "dependency-requirement-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        self.assertFalse(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingDependencyDetail" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(DependencyText ", joined)
        self.assertFalse(any("Dependency" in refusal.reason for refusal in refusals))

    def test_vague_dependency_marker_becomes_blocking_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R26] Load reviewer context. Dependency: TODO decide integration later.\n"
            "***acceptance tests***\n"
            "- [covers:R26] Context loader reports dependency status.\n",
            "semantic_dependency_unknown.plain",
        )

        self.assertTrue(any(check.property == "dependency-requirement-reviewable" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(
            any(
                obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingDependencyDetail" for fact in obj.facts)
                for obj in doc.objects
            )
        )
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(MissingDependencyDetail ", "\n".join(atoms))
        self.assertFalse(any("MissingDependencyDetail" in refusal.reason for refusal in refusals))

    def test_explicit_question_marker_becomes_blocking_review_item(self):
        source = (
            "***requirements***\n"
            "- [id:R16] Gate risky deployments. Question: Who approves emergency rollback? Evidence: runbook draft.\n"
            "***acceptance tests***\n"
            "- [covers:R16] Deployment gate lists an approver.\n"
        )
        doc = compile_source(source, "semantic_question.plain")
        explicit_question = next(
            obj for obj in doc.objects
            if obj.role == Role.QUESTION_OBJECT and any(fact[0] == "ExplicitQuestion" for fact in obj.facts)
        )
        facts = {fact[0]: fact for fact in explicit_question.facts}
        span = next(span for span in doc.spans if span.id == explicit_question.source_span_id)

        self.assertEqual(facts["QuestionText"][2], "Who approves emergency rollback?")
        self.assertEqual(facts["ExplicitQuestion"][2], facts["QuestionsObject"][2])
        self.assertEqual(doc.files[0].text[span.start_byte:span.end_byte], "Question: Who approves emergency rollback?")
        self.assertTrue(any(check.property == "explicit-question-needs-answer" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(fact[0] == "Blocks" for fact in explicit_question.facts))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(ExplicitQuestion ", joined)
        self.assertIn("(QuestionsObject ", joined)
        self.assertFalse(any("ExplicitQuestion" in refusal.reason or "QuestionsObject" in refusal.reason for refusal in refusals))

    def test_explicit_assumption_marker_links_same_item_evidence_and_exports(self):
        source = (
            "***requirements***\n"
            "- [id:R17] Cache reviewer hints. Evidence: product note. "
            "Assumption: reviewer ids are stable for one release. Question: When do ids rotate?\n"
            "***acceptance tests***\n"
            "- [covers:R17] Cached hints include a release id.\n"
        )
        doc = compile_source(source, "semantic_assumption.plain")
        assumption = next(obj for obj in doc.objects if obj.role == Role.ASSUMPTION_OBJECT)
        facts = {fact[0]: fact for fact in assumption.facts}
        span = next(span for span in doc.spans if span.id == assumption.source_span_id)

        self.assertEqual(facts["AssumptionText"][2], "reviewer ids are stable for one release")
        self.assertEqual(doc.files[0].text[span.start_byte:span.end_byte], "Assumption: reviewer ids are stable for one release")
        self.assertTrue(any(fact[0] == "AssumptionEvidence" for fact in assumption.facts))
        self.assertTrue(any(check.property == "assumption-has-explicit-evidence" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Assumption ", joined)
        self.assertIn("(AssumptionEvidence ", joined)
        self.assertFalse(any("Assumption" in refusal.reason for refusal in refusals))

    def test_assumption_without_evidence_becomes_blocking_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R18] Cache reviewer hints. Assumption: reviewer ids never rotate.\n"
            "***acceptance tests***\n"
            "- [covers:R18] Cached hints include a reviewer id.\n",
            "semantic_assumption_unknown.plain",
        )

        self.assertTrue(any(check.property == "assumption-has-explicit-evidence" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(
            any(
                obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingAssumptionEvidence" for fact in obj.facts)
                for obj in doc.objects
            )
        )
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(MissingAssumptionEvidence ", "\n".join(atoms))
        self.assertFalse(any("MissingAssumptionEvidence" in refusal.reason for refusal in refusals))

    def test_explicit_invariant_marker_links_same_item_evidence_and_exports(self):
        source = (
            "***requirements***\n"
            "- [id:R19] Maintain account totals. Evidence: ledger design note. "
            "Invariant: debits and credits balance after every posted transaction. Question: Who audits exceptions?\n"
            "***acceptance tests***\n"
            "- [covers:R19] Posting a transaction preserves total balance.\n"
        )
        doc = compile_source(source, "semantic_invariant.plain")
        invariant = next(obj for obj in doc.objects if any(fact[0] == "Invariant" for fact in obj.facts))
        facts = {fact[0]: fact for fact in invariant.facts}
        span = next(span for span in doc.spans if span.id == invariant.source_span_id)

        self.assertEqual(invariant.role, Role.PROPOSITION_OBJECT)
        self.assertEqual(facts["InvariantText"][2], "debits and credits balance after every posted transaction")
        self.assertEqual(doc.files[0].text[span.start_byte:span.end_byte], "Invariant: debits and credits balance after every posted transaction")
        self.assertTrue(any(fact[0] == "InvariantEvidence" for fact in invariant.facts))
        self.assertTrue(any(check.property == "invariant-has-explicit-evidence" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Invariant ", joined)
        self.assertIn("(InvariantEvidence ", joined)
        self.assertFalse(any("Invariant" in refusal.reason for refusal in refusals))

    def test_invariant_without_evidence_becomes_blocking_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R20] Maintain account totals. Invariant: debits and credits balance after every posted transaction.\n"
            "***acceptance tests***\n"
            "- [covers:R20] Posting a transaction preserves total balance.\n",
            "semantic_invariant_unknown.plain",
        )

        self.assertTrue(any(check.property == "invariant-has-explicit-evidence" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(
            any(
                obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingInvariantEvidence" for fact in obj.facts)
                for obj in doc.objects
            )
        )
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(MissingInvariantEvidence ", "\n".join(atoms))
        self.assertFalse(any("MissingInvariantEvidence" in refusal.reason for refusal in refusals))

    def test_explicit_constraint_marker_links_same_item_evidence_and_exports(self):
        source = (
            "***requirements***\n"
            "- [id:R21] Limit export size. Evidence: platform quota. "
            "Constraint: exports must stay below 100MB per request. Question: Is the quota tenant-specific?\n"
            "***acceptance tests***\n"
            "- [covers:R21] Oversized exports are rejected.\n"
        )
        doc = compile_source(source, "semantic_constraint.plain")
        constraint = next(obj for obj in doc.objects if any(fact[0] == "Constraint" for fact in obj.facts))
        facts = {fact[0]: fact for fact in constraint.facts}
        span = next(span for span in doc.spans if span.id == constraint.source_span_id)

        self.assertEqual(constraint.role, Role.OBLIGATION_OBJECT)
        self.assertEqual(facts["ConstraintText"][2], "exports must stay below 100MB per request")
        self.assertEqual(doc.files[0].text[span.start_byte:span.end_byte], "Constraint: exports must stay below 100MB per request")
        self.assertTrue(any(fact[0] == "ConstraintEvidence" for fact in constraint.facts))
        self.assertTrue(any(check.property == "constraint-has-explicit-evidence" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Constraint ", joined)
        self.assertIn("(ConstraintEvidence ", joined)
        self.assertFalse(any("Constraint" in refusal.reason for refusal in refusals))

    def test_constraint_without_evidence_becomes_blocking_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R22] Limit export size. Constraint: exports must stay below 100MB per request.\n"
            "***acceptance tests***\n"
            "- [covers:R22] Oversized exports are rejected.\n",
            "semantic_constraint_unknown.plain",
        )

        self.assertTrue(any(check.property == "constraint-has-explicit-evidence" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(
            any(
                obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingConstraintEvidence" for fact in obj.facts)
                for obj in doc.objects
            )
        )
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(MissingConstraintEvidence ", "\n".join(atoms))
        self.assertFalse(any("MissingConstraintEvidence" in refusal.reason for refusal in refusals))

    def test_explicit_owner_marker_exports_reviewable_assignment(self):
        source = (
            "***requirements***\n"
            "- [id:R48] Keep ownership reviewable. Owner: platform-team. "
            "Evidence: ops rota.\n"
            "***acceptance tests***\n"
            "- [covers:R48] Ownership is exported.\n"
        )
        doc = compile_source(source, "semantic_owner_assignment.plain")
        owner = next(obj for obj in doc.objects if any(fact[0] == "Owner" for fact in obj.facts))
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT)
        facts = {fact[0]: fact for fact in owner.facts}
        owner_span = next(span for span in doc.spans if span.id == owner.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(facts["OwnerText"][2], "platform-team")
        self.assertEqual(doc.files[0].text[owner_span.start_byte:owner_span.end_byte], "Owner: platform-team")
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: ops rota")
        self.assertLess(owner_span.end_byte, evidence_span.start_byte)
        self.assertTrue(any(check.property == "owner-assignment-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        self.assertFalse(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingOwnerAssignment" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Owner ", joined)
        self.assertIn("(OwnerText ", joined)
        self.assertFalse(any("Owner" in refusal.reason for refusal in refusals))

    def test_explicit_priority_marker_exports_reviewable_value(self):
        source = (
            "***requirements***\n"
            "- [id:R50] Keep priority reviewable. Priority: P1. "
            "Owner: platform-team.\n"
            "***acceptance tests***\n"
            "- [covers:R50] Priority is exported.\n"
        )
        doc = compile_source(source, "semantic_priority_value.plain")
        priority = next(obj for obj in doc.objects if any(fact[0] == "Priority" for fact in obj.facts))
        owner = next(obj for obj in doc.objects if any(fact[0] == "Owner" for fact in obj.facts))
        facts = {fact[0]: fact for fact in priority.facts}
        priority_span = next(span for span in doc.spans if span.id == priority.source_span_id)
        owner_span = next(span for span in doc.spans if span.id == owner.source_span_id)

        self.assertEqual(facts["PriorityText"][2], "P1")
        self.assertEqual(facts["PriorityValue"][2], "p1")
        self.assertEqual(doc.files[0].text[priority_span.start_byte:priority_span.end_byte], "Priority: P1")
        self.assertEqual(doc.files[0].text[owner_span.start_byte:owner_span.end_byte], "Owner: platform-team")
        self.assertLess(priority_span.end_byte, owner_span.start_byte)
        self.assertTrue(any(check.property == "priority-value-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        self.assertFalse(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "UnsupportedPriorityValue" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Priority ", joined)
        self.assertIn("(PriorityValue ", joined)
        self.assertFalse(any("Priority" in refusal.reason for refusal in refusals))

    def test_priority_placeholder_becomes_blocking_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R51] Keep missing priority explicit. Priority: TBD.\n"
            "***acceptance tests***\n"
            "- [covers:R51] Missing priority creates review question.\n",
            "semantic_priority_missing.plain",
        )
        priority = next(obj for obj in doc.objects if any(fact[0] == "Priority" for fact in obj.facts))
        facts = {fact[0]: fact for fact in priority.facts}

        self.assertEqual(facts["PriorityText"][2], "TBD")
        self.assertTrue(any(check.property == "priority-value-reviewable" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "UnsupportedPriorityValue" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(UnsupportedPriorityValue ", "\n".join(atoms))
        self.assertFalse(any("UnsupportedPriorityValue" in refusal.reason for refusal in refusals))

    def test_explicit_deadline_marker_exports_reviewable_value(self):
        source = (
            "***requirements***\n"
            "- [id:R52] Keep timing reviewable. Deadline: 2026-08-15. "
            "Owner: platform-team.\n"
            "***acceptance tests***\n"
            "- [covers:R52] Deadline is exported.\n"
        )
        doc = compile_source(source, "semantic_deadline_value.plain")
        deadline = next(obj for obj in doc.objects if any(fact[0] == "Deadline" for fact in obj.facts))
        owner = next(obj for obj in doc.objects if any(fact[0] == "Owner" for fact in obj.facts))
        facts = {fact[0]: fact for fact in deadline.facts}
        deadline_span = next(span for span in doc.spans if span.id == deadline.source_span_id)
        owner_span = next(span for span in doc.spans if span.id == owner.source_span_id)

        self.assertEqual(facts["DeadlineText"][2], "2026-08-15")
        self.assertEqual(facts["DeadlineValue"][2], "2026-08-15")
        self.assertEqual(doc.files[0].text[deadline_span.start_byte:deadline_span.end_byte], "Deadline: 2026-08-15")
        self.assertEqual(doc.files[0].text[owner_span.start_byte:owner_span.end_byte], "Owner: platform-team")
        self.assertLess(deadline_span.end_byte, owner_span.start_byte)
        self.assertTrue(any(check.property == "deadline-value-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        self.assertFalse(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "UnsupportedDeadlineValue" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Deadline ", joined)
        self.assertIn("(DeadlineValue ", joined)
        self.assertFalse(any("Deadline" in refusal.reason for refusal in refusals))

    def test_deadline_placeholder_becomes_blocking_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R53] Keep missing timing explicit. Due: ASAP.\n"
            "***acceptance tests***\n"
            "- [covers:R53] Missing deadline creates review question.\n",
            "semantic_deadline_missing.plain",
        )
        deadline = next(obj for obj in doc.objects if any(fact[0] == "Deadline" for fact in obj.facts))
        facts = {fact[0]: fact for fact in deadline.facts}

        self.assertEqual(facts["DeadlineText"][2], "ASAP")
        self.assertTrue(any(check.property == "deadline-value-reviewable" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "UnsupportedDeadlineValue" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(UnsupportedDeadlineValue ", "\n".join(atoms))
        self.assertFalse(any("UnsupportedDeadlineValue" in refusal.reason for refusal in refusals))

    def test_owner_placeholder_becomes_blocking_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R49] Keep missing ownership explicit. Assignee: TBD.\n"
            "***acceptance tests***\n"
            "- [covers:R49] Missing owner creates review question.\n",
            "semantic_owner_missing.plain",
        )
        owner = next(obj for obj in doc.objects if any(fact[0] == "Owner" for fact in obj.facts))
        facts = {fact[0]: fact for fact in owner.facts}

        self.assertEqual(facts["OwnerText"][2], "TBD")
        self.assertTrue(any(check.property == "owner-assignment-reviewable" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingOwnerAssignment" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(MissingOwnerAssignment ", "\n".join(atoms))
        self.assertFalse(any("MissingOwnerAssignment" in refusal.reason for refusal in refusals))

    def test_explicit_limitation_marker_requires_review_disposition(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R39] Export reports. Limitation: PDF export is not supported in v0.1.\n"
            "***acceptance tests***\n"
            "- [covers:R39] Unsupported formats return a clear diagnostic.\n",
            "semantic_limitation_unknown.plain",
        )

        limitation = next(obj for obj in doc.objects if any(fact[0] == "Limitation" for fact in obj.facts))
        facts = {fact[0]: fact for fact in limitation.facts}
        self.assertEqual(facts["LimitationText"][2], "PDF export is not supported in v0.1")
        self.assertTrue(any(check.property == "limitation-has-review-disposition" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(
            any(
                obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingLimitationDisposition" for fact in obj.facts)
                for obj in doc.objects
            )
        )
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(MissingLimitationDisposition ", "\n".join(atoms))
        self.assertFalse(any("Limitation" in refusal.reason for refusal in refusals))

    def test_explicit_limitation_marker_links_same_item_mitigation(self):
        source = (
            "***requirements***\n"
            "- [id:R40] Export reports. Limitation: CSV only in v0.1. "
            "Mitigation: document unsupported formats and return a clear fallback message.\n"
            "***acceptance tests***\n"
            "- [covers:R40] Unsupported format requests receive a fallback diagnostic.\n"
        )
        doc = compile_source(source, "semantic_limitation_mitigated.plain")
        limitation = next(obj for obj in doc.objects if any(fact[0] == "Limitation" for fact in obj.facts))
        mitigation = next(obj for obj in doc.objects if any(fact[0] == "RiskMitigation" for fact in obj.facts))
        limitation_facts = {fact[0]: fact for fact in limitation.facts}
        mitigation_facts = {fact[0]: fact for fact in mitigation.facts}
        limitation_span = next(span for span in doc.spans if span.id == limitation.source_span_id)
        mitigation_span = next(span for span in doc.spans if span.id == mitigation.source_span_id)

        self.assertEqual(limitation_facts["LimitationText"][2], "CSV only in v0.1")
        self.assertEqual(mitigation_facts["RiskMitigationText"][2], "document unsupported formats and return a clear fallback message")
        self.assertEqual(doc.files[0].text[limitation_span.start_byte:limitation_span.end_byte], "Limitation: CSV only in v0.1")
        self.assertEqual(doc.files[0].text[mitigation_span.start_byte:mitigation_span.end_byte], "Mitigation: document unsupported formats and return a clear fallback message")
        self.assertTrue(any(fact == ("LimitationMitigatedBy", limitation.id, mitigation.id) for fact in limitation.facts))
        self.assertTrue(any(check.property == "limitation-has-review-disposition" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Limitation ", joined)
        self.assertIn("(LimitationMitigatedBy ", joined)
        self.assertFalse(any("Limitation" in refusal.reason for refusal in refusals))

    def test_explicit_non_goal_marker_preserves_exclusion_without_question(self):
        source = (
            "***requirements***\n"
            "- [id:R41] Export reports. Non-goal: PDF rendering in v0.1. "
            "Evidence: docs/export-scope.md.\n"
            "***acceptance tests***\n"
            "- [covers:R41] CSV export remains supported.\n"
        )
        doc = compile_source(source, "semantic_non_goal.plain")
        non_goal = next(obj for obj in doc.objects if any(fact[0] == "NonGoal" for fact in obj.facts))
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT)
        facts = {fact[0]: fact for fact in non_goal.facts}
        non_goal_span = next(span for span in doc.spans if span.id == non_goal.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(facts["NonGoalText"][2], "PDF rendering in v0.1")
        self.assertEqual(doc.files[0].text[non_goal_span.start_byte:non_goal_span.end_byte], "Non-goal: PDF rendering in v0.1")
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: docs/export-scope.md")
        self.assertLess(non_goal_span.end_byte, evidence_span.start_byte)
        self.assertTrue(any(check.property == "non-goal-has-source-provenance" and check.status == CheckStatus.PASS for check in doc.checks))
        self.assertFalse(any(obj.role == Role.QUESTION_OBJECT and any(fact[0].startswith("MissingNonGoal") for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(NonGoal ", joined)
        self.assertIn("(NonGoalText ", joined)
        self.assertFalse(any("NonGoal" in refusal.reason for refusal in refusals))

    def test_explicit_open_issue_marker_becomes_blocking_question_and_preserves_boundary(self):
        source = (
            "***requirements***\n"
            "- [id:R42] Export reports. Open issue: choose CSV delimiter for EU locales. "
            "Evidence: product review notes.\n"
            "***acceptance tests***\n"
            "- [covers:R42] Locale export behavior is documented.\n"
        )
        doc = compile_source(source, "semantic_open_issue.plain")
        issue = next(obj for obj in doc.objects if obj.role == Role.QUESTION_OBJECT and any(fact[0] == "OpenIssue" for fact in obj.facts))
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT)
        facts = {fact[0]: fact for fact in issue.facts}
        issue_span = next(span for span in doc.spans if span.id == issue.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(facts["OpenIssueText"][2], "choose CSV delimiter for EU locales")
        self.assertEqual(facts["QuestionText"][2], "choose CSV delimiter for EU locales")
        self.assertEqual(doc.files[0].text[issue_span.start_byte:issue_span.end_byte], "Open issue: choose CSV delimiter for EU locales")
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: product review notes")
        self.assertLess(issue_span.end_byte, evidence_span.start_byte)
        self.assertTrue(any(check.property == "open-issue-needs-resolution" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(fact[0] == "Blocks" for fact in issue.facts))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(OpenIssue ", joined)
        self.assertIn("(OpenIssueText ", joined)
        self.assertFalse(any("OpenIssue" in refusal.reason or "IssueFor" in refusal.reason for refusal in refusals))

    def test_deprecated_marker_requires_replacement_or_disposition(self):
        source = (
            "***requirements***\n"
            "- [id:R46] Keep API changes reviewable. Deprecated: v1 export endpoint. "
            "Evidence: api review notes.\n"
            "***acceptance tests***\n"
            "- [covers:R46] Deprecated endpoints emit review diagnostics.\n"
        )
        doc = compile_source(source, "semantic_deprecated_unknown.plain")
        deprecated = next(obj for obj in doc.objects if any(fact[0] == "Deprecated" for fact in obj.facts))
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT)
        facts = {fact[0]: fact for fact in deprecated.facts}
        deprecated_span = next(span for span in doc.spans if span.id == deprecated.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(facts["DeprecatedText"][2], "v1 export endpoint")
        self.assertEqual(doc.files[0].text[deprecated_span.start_byte:deprecated_span.end_byte], "Deprecated: v1 export endpoint")
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: api review notes")
        self.assertLess(deprecated_span.end_byte, evidence_span.start_byte)
        self.assertTrue(any(check.property == "deprecated-item-has-replacement-or-disposition" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingDeprecationDisposition" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Deprecated ", joined)
        self.assertIn("(MissingDeprecationDisposition ", joined)
        self.assertFalse(any("Deprecated" in refusal.reason or "MissingDeprecationDisposition" in refusal.reason for refusal in refusals))

    def test_deprecated_marker_links_same_item_replacement(self):
        source = (
            "***requirements***\n"
            "- [id:R47] Keep API migration reviewable. Deprecated: v1 export endpoint. "
            "Replacement: v2 export endpoint. Evidence: api migration review.\n"
            "***acceptance tests***\n"
            "- [covers:R47] Replacement endpoint is exported.\n"
        )
        doc = compile_source(source, "semantic_deprecated_replacement.plain")
        deprecated = next(obj for obj in doc.objects if any(fact[0] == "Deprecated" for fact in obj.facts))
        replacement = next(obj for obj in doc.objects if any(fact[0] == "Replacement" for fact in obj.facts))
        deprecated_facts = {fact[0]: fact for fact in deprecated.facts}
        replacement_facts = {fact[0]: fact for fact in replacement.facts}
        deprecated_span = next(span for span in doc.spans if span.id == deprecated.source_span_id)
        replacement_span = next(span for span in doc.spans if span.id == replacement.source_span_id)

        self.assertEqual(deprecated_facts["DeprecatedText"][2], "v1 export endpoint")
        self.assertEqual(replacement_facts["ReplacementText"][2], "v2 export endpoint")
        self.assertEqual(doc.files[0].text[deprecated_span.start_byte:deprecated_span.end_byte], "Deprecated: v1 export endpoint")
        self.assertEqual(doc.files[0].text[replacement_span.start_byte:replacement_span.end_byte], "Replacement: v2 export endpoint")
        self.assertTrue(any(fact == ("DeprecatedReplacedBy", deprecated.id, replacement.id) for fact in deprecated.facts))
        self.assertTrue(any(check.property == "deprecated-item-has-replacement-or-disposition" and check.status == CheckStatus.PASS for check in doc.checks))
        self.assertFalse(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingDeprecationDisposition" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(DeprecatedReplacedBy ", joined)
        self.assertIn("(ReplacementText ", joined)
        self.assertFalse(any("Deprecated" in refusal.reason or "Replacement" in refusal.reason for refusal in refusals))

    def test_issue_marker_stops_before_question_marker(self):
        source = (
            "***requirements***\n"
            "- [id:R43] Export reports. Issue: delimiter is unsettled. "
            "Question: Who signs off the delimiter?\n"
            "***acceptance tests***\n"
            "- [covers:R43] Locale export behavior is documented.\n"
        )
        doc = compile_source(source, "semantic_issue_question_boundary.plain")
        issue = next(obj for obj in doc.objects if any(fact[0] == "OpenIssue" for fact in obj.facts))
        question = next(obj for obj in doc.objects if any(fact[0] == "ExplicitQuestion" for fact in obj.facts))
        issue_facts = {fact[0]: fact for fact in issue.facts}
        question_facts = {fact[0]: fact for fact in question.facts}
        issue_span = next(span for span in doc.spans if span.id == issue.source_span_id)
        question_span = next(span for span in doc.spans if span.id == question.source_span_id)

        self.assertEqual(issue_facts["OpenIssueText"][2], "delimiter is unsettled")
        self.assertEqual(question_facts["QuestionText"][2], "Who signs off the delimiter?")
        self.assertEqual(doc.files[0].text[issue_span.start_byte:issue_span.end_byte], "Issue: delimiter is unsettled")
        self.assertEqual(doc.files[0].text[question_span.start_byte:question_span.end_byte], "Question: Who signs off the delimiter?")
        self.assertLess(issue_span.end_byte, question_span.start_byte)

    def test_explicit_todo_marker_becomes_blocking_question_and_preserves_boundary(self):
        source = (
            "***requirements***\n"
            "- [id:R44] Export reports. TODO: define CSV delimiter policy. "
            "Evidence: product review notes.\n"
            "***acceptance tests***\n"
            "- [covers:R44] Locale export behavior is documented.\n"
        )
        doc = compile_source(source, "semantic_todo.plain")
        todo = next(obj for obj in doc.objects if obj.role == Role.QUESTION_OBJECT and any(fact[0] == "TodoItem" for fact in obj.facts))
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT)
        facts = {fact[0]: fact for fact in todo.facts}
        todo_span = next(span for span in doc.spans if span.id == todo.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(facts["TodoText"][2], "define CSV delimiter policy")
        self.assertEqual(facts["QuestionText"][2], "define CSV delimiter policy")
        self.assertEqual(doc.files[0].text[todo_span.start_byte:todo_span.end_byte], "TODO: define CSV delimiter policy")
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: product review notes")
        self.assertLess(todo_span.end_byte, evidence_span.start_byte)
        self.assertTrue(any(check.property == "todo-item-needs-resolution" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(fact[0] == "Blocks" for fact in todo.facts))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(TodoItem ", joined)
        self.assertIn("(TodoText ", joined)
        self.assertFalse(any("Todo" in refusal.reason for refusal in refusals))

    def test_todo_marker_stops_before_open_issue_marker(self):
        source = (
            "***requirements***\n"
            "- [id:R45] Export reports. To-do: decide fallback format. "
            "Open issue: product has not ranked PDF support.\n"
            "***acceptance tests***\n"
            "- [covers:R45] Unsupported export requests stay reviewable.\n"
        )
        doc = compile_source(source, "semantic_todo_issue_boundary.plain")
        todo = next(obj for obj in doc.objects if any(fact[0] == "TodoItem" for fact in obj.facts))
        issue = next(obj for obj in doc.objects if any(fact[0] == "OpenIssue" for fact in obj.facts))
        todo_facts = {fact[0]: fact for fact in todo.facts}
        issue_facts = {fact[0]: fact for fact in issue.facts}
        todo_span = next(span for span in doc.spans if span.id == todo.source_span_id)
        issue_span = next(span for span in doc.spans if span.id == issue.source_span_id)

        self.assertEqual(todo_facts["TodoText"][2], "decide fallback format")
        self.assertEqual(issue_facts["OpenIssueText"][2], "product has not ranked PDF support")
        self.assertEqual(doc.files[0].text[todo_span.start_byte:todo_span.end_byte], "To-do: decide fallback format")
        self.assertEqual(doc.files[0].text[issue_span.start_byte:issue_span.end_byte], "Open issue: product has not ranked PDF support")
        self.assertLess(todo_span.end_byte, issue_span.start_byte)

    def test_explicit_risk_marker_requires_mitigation(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R18] Import partner files. Risk: malformed uploads exhaust parser memory.\n"
            "***acceptance tests***\n"
            "- [covers:R18] Large malformed upload is rejected.\n",
            "semantic_risk_unknown.plain",
        )

        risk = next(obj for obj in doc.objects if any(fact[0] == "Risk" for fact in obj.facts))
        facts = {fact[0]: fact for fact in risk.facts}
        self.assertEqual(facts["RiskText"][2], "malformed uploads exhaust parser memory")
        self.assertTrue(any(check.property == "risk-has-explicit-mitigation" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(
            any(
                obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingRiskMitigation" for fact in obj.facts)
                for obj in doc.objects
            )
        )
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(MissingRiskMitigation ", "\n".join(atoms))
        self.assertFalse(any("Risk" in refusal.reason for refusal in refusals))

    def test_explicit_risk_marker_links_same_item_mitigation(self):
        source = (
            "***requirements***\n"
            "- [id:R19] Run batch import. Risk: queue backlog delays user reports. "
            "Mitigation: monitor backlog alerts and apply worker backpressure.\n"
            "***acceptance tests***\n"
            "- [covers:R19] Backlog alert appears before the SLA window expires.\n"
        )
        doc = compile_source(source, "semantic_risk_mitigated.plain")
        risk = next(obj for obj in doc.objects if any(fact[0] == "Risk" for fact in obj.facts))
        mitigation = next(obj for obj in doc.objects if any(fact[0] == "RiskMitigation" for fact in obj.facts))
        risk_facts = {fact[0]: fact for fact in risk.facts}
        mitigation_facts = {fact[0]: fact for fact in mitigation.facts}
        risk_span = next(span for span in doc.spans if span.id == risk.source_span_id)
        mitigation_span = next(span for span in doc.spans if span.id == mitigation.source_span_id)

        self.assertEqual(risk_facts["RiskText"][2], "queue backlog delays user reports")
        self.assertEqual(mitigation_facts["RiskMitigationText"][2], "monitor backlog alerts and apply worker backpressure")
        self.assertEqual(doc.files[0].text[risk_span.start_byte:risk_span.end_byte], "Risk: queue backlog delays user reports")
        self.assertEqual(doc.files[0].text[mitigation_span.start_byte:mitigation_span.end_byte], "Mitigation: monitor backlog alerts and apply worker backpressure")
        self.assertTrue(any(fact == ("RiskMitigatedBy", risk.id, mitigation.id) for fact in risk.facts))
        self.assertTrue(any(check.property == "risk-has-explicit-mitigation" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Risk ", joined)
        self.assertIn("(RiskMitigation ", joined)
        self.assertFalse(any("Risk" in refusal.reason for refusal in refusals))

    def test_explicit_acceptance_criterion_marker_exports_reviewable_criterion(self):
        source = (
            "***requirements***\n"
            "- [id:R53] Preserve diagnostics. "
            "Acceptance Criterion: CLI exits nonzero and writes diagnostics.md when validation fails. "
            "Evidence: tests/test_cli.py::CliTests.\n"
            "***acceptance tests***\n"
            "- [covers:R53] Failing validation writes a diagnostics report.\n"
        )
        doc = compile_source(source, "semantic_acceptance_criterion.plain")
        criterion = next(obj for obj in doc.objects if any(fact[0] == "AcceptanceCriterion" for fact in obj.facts))
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT)
        facts = {fact[0]: fact for fact in criterion.facts}
        criterion_span = next(span for span in doc.spans if span.id == criterion.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(facts["AcceptanceCriterionText"][2], "CLI exits nonzero and writes diagnostics.md when validation fails")
        self.assertEqual(
            doc.files[0].text[criterion_span.start_byte:criterion_span.end_byte],
            "Acceptance Criterion: CLI exits nonzero and writes diagnostics.md when validation fails",
        )
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: tests/test_cli.py::CliTests")
        self.assertLess(criterion_span.end_byte, evidence_span.start_byte)
        self.assertTrue(any(check.property == "acceptance-criterion-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        self.assertFalse(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingAcceptanceCriterionDetail" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(AcceptanceCriterion ", joined)
        self.assertIn("(AcceptanceCriterionText ", joined)
        self.assertFalse(any("AcceptanceCriterion" in refusal.reason for refusal in refusals))

    def test_acceptance_criterion_placeholder_becomes_blocking_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R54] Define export quality. Acceptance criteria: TBD.\n"
            "***acceptance tests***\n"
            "- [covers:R54] Export criteria are reviewable.\n",
            "semantic_acceptance_criterion_placeholder.plain",
        )

        criterion = next(obj for obj in doc.objects if any(fact[0] == "AcceptanceCriterion" for fact in obj.facts))
        facts = {fact[0]: fact for fact in criterion.facts}
        self.assertEqual(facts["AcceptanceCriterionText"][2], "TBD")
        self.assertTrue(any(check.property == "acceptance-criterion-reviewable" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingAcceptanceCriterionDetail" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(MissingAcceptanceCriterionDetail ", "\n".join(atoms))
        self.assertFalse(any("MissingAcceptanceCriterionDetail" in refusal.reason for refusal in refusals))

    def test_explicit_example_marker_exports_reviewable_source_spanned_example(self):
        source = (
            "***requirements***\n"
            "- [id:R55] Preserve review examples. "
            "Example: request A produces diagnostic B in docs/example.v1.md. "
            "Evidence: examples/review-fixture.plain.\n"
            "***acceptance tests***\n"
            "- [covers:R55] Example atoms are exported without executable claims.\n"
        )
        doc = compile_source(source, "semantic_example.plain")
        example = next(obj for obj in doc.objects if any(fact[0] == "Example" for fact in obj.facts))
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT and any(fact[0] == "Evidence" for fact in obj.facts))
        facts = {fact[0]: fact for fact in example.facts}
        example_span = next(span for span in doc.spans if span.id == example.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(facts["ExampleText"][2], "request A produces diagnostic B in docs/example.v1.md")
        self.assertEqual(
            doc.files[0].text[example_span.start_byte:example_span.end_byte],
            "Example: request A produces diagnostic B in docs/example.v1.md",
        )
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: examples/review-fixture.plain")
        self.assertLess(example_span.end_byte, evidence_span.start_byte)
        self.assertTrue(any(check.property == "example-detail-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Example ", joined)
        self.assertIn("(ExampleText ", joined)
        self.assertFalse(any("Example" in refusal.reason for refusal in refusals))

    def test_example_placeholder_becomes_blocking_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R56] Preserve unresolved examples. Example: placeholder.\n"
            "***acceptance tests***\n"
            "- [covers:R56] Placeholder examples remain blocking questions.\n",
            "semantic_example_placeholder.plain",
        )

        example = next(obj for obj in doc.objects if any(fact[0] == "Example" for fact in obj.facts))
        facts = {fact[0]: fact for fact in example.facts}
        self.assertEqual(facts["ExampleText"][2], "placeholder")
        self.assertTrue(any(check.property == "example-detail-reviewable" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingExampleDetail" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(MissingExampleDetail ", "\n".join(atoms))
        self.assertFalse(any("MissingExampleDetail" in refusal.reason for refusal in refusals))

    def test_explicit_citation_marker_exports_reviewable_reference(self):
        source = (
            "***requirements***\n"
            "- [id:R57] Preserve bibliography provenance. "
            "Citation: doi:10.1234/specatom.v1 and docs/design-note.bib. "
            "Evidence: literature review.\n"
            "***acceptance tests***\n"
            "- [covers:R57] Citation atoms are exported without truth inference.\n"
        )
        doc = compile_source(source, "semantic_citation.plain")
        citation = next(obj for obj in doc.objects if any(fact[0] == "Citation" for fact in obj.facts))
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT and any(fact[0] == "Evidence" for fact in obj.facts))
        facts = {fact[0]: fact for fact in citation.facts}
        citation_span = next(span for span in doc.spans if span.id == citation.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(facts["CitationText"][2], "doi:10.1234/specatom.v1 and docs/design-note.bib")
        self.assertEqual(
            doc.files[0].text[citation_span.start_byte:citation_span.end_byte],
            "Citation: doi:10.1234/specatom.v1 and docs/design-note.bib",
        )
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: literature review")
        self.assertLess(citation_span.end_byte, evidence_span.start_byte)
        self.assertTrue(any(check.property == "citation-reference-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Citation ", joined)
        self.assertIn("(CitationText ", joined)
        self.assertFalse(any("Citation" in refusal.reason for refusal in refusals))

    def test_citation_placeholder_becomes_blocking_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R58] Preserve missing bibliography links. Reference: citation needed.\n"
            "***acceptance tests***\n"
            "- [covers:R58] Placeholder citations remain blocking questions.\n",
            "semantic_citation_placeholder.plain",
        )

        citation = next(obj for obj in doc.objects if any(fact[0] == "Citation" for fact in obj.facts))
        facts = {fact[0]: fact for fact in citation.facts}
        self.assertEqual(facts["CitationText"][2], "citation needed")
        self.assertTrue(any(check.property == "citation-reference-reviewable" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingCitationReference" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(MissingCitationReference ", "\n".join(atoms))
        self.assertFalse(any("MissingCitationReference" in refusal.reason for refusal in refusals))

    def test_explicit_metric_marker_exports_reviewable_validation_criterion(self):
        source = (
            "***requirements***\n"
            "- [id:R59] Preserve empirical validation thresholds. "
            "Metric: p95 latency <= 200 ms and success rate >= 99%. "
            "Evidence: tests/perf_report.md.\n"
            "***acceptance tests***\n"
            "- [covers:R59] Metric atoms are exported without claiming the threshold passed.\n"
        )
        doc = compile_source(source, "semantic_metric.plain")
        metric = next(obj for obj in doc.objects if any(fact[0] == "Metric" for fact in obj.facts))
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT and any(fact[0] == "Evidence" for fact in obj.facts))
        facts = {fact[0]: fact for fact in metric.facts}
        metric_span = next(span for span in doc.spans if span.id == metric.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(facts["MetricText"][2], "p95 latency <= 200 ms and success rate >= 99%")
        self.assertEqual(
            doc.files[0].text[metric_span.start_byte:metric_span.end_byte],
            "Metric: p95 latency <= 200 ms and success rate >= 99%",
        )
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: tests/perf_report.md")
        self.assertLess(metric_span.end_byte, evidence_span.start_byte)
        self.assertTrue(any(check.property == "metric-definition-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Metric ", joined)
        self.assertIn("(MetricText ", joined)
        self.assertFalse(any("Metric" in refusal.reason for refusal in refusals))

    def test_metric_placeholder_becomes_blocking_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R60] Preserve unresolved validation metrics. Metric: TBD.\n"
            "***acceptance tests***\n"
            "- [covers:R60] Placeholder metrics remain blocking questions.\n",
            "semantic_metric_placeholder.plain",
        )

        metric = next(obj for obj in doc.objects if any(fact[0] == "Metric" for fact in obj.facts))
        facts = {fact[0]: fact for fact in metric.facts}
        self.assertEqual(facts["MetricText"][2], "TBD")
        self.assertTrue(any(check.property == "metric-definition-reviewable" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingMetricDefinition" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(MissingMetricDefinition ", "\n".join(atoms))
        self.assertFalse(any("MissingMetricDefinition" in refusal.reason for refusal in refusals))

    def test_explicit_validation_marker_exports_reviewable_check_procedure(self):
        source = (
            "***requirements***\n"
            "- [id:R61] Preserve explicit validation procedures. "
            "Validation: compare generated atoms to tests/ground_truth/auth_service.metta. "
            "Evidence: tests/test_auth_service_ground_truth.py.\n"
            "***acceptance tests***\n"
            "- [covers:R61] Validation procedure atoms are exported.\n"
        )
        doc = compile_source(source, "semantic_validation_marker.plain")
        validation = next(obj for obj in doc.objects if any(fact[0] == "Validation" for fact in obj.facts))
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT and any(fact[0] == "Evidence" for fact in obj.facts))
        facts = {fact[0]: fact for fact in validation.facts}
        validation_span = next(span for span in doc.spans if span.id == validation.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(facts["ValidationText"][2], "compare generated atoms to tests/ground_truth/auth_service.metta")
        self.assertEqual(
            doc.files[0].text[validation_span.start_byte:validation_span.end_byte],
            "Validation: compare generated atoms to tests/ground_truth/auth_service.metta",
        )
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: tests/test_auth_service_ground_truth.py")
        self.assertLess(validation_span.end_byte, evidence_span.start_byte)
        self.assertTrue(any(check.property == "validation-marker-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Validation ", joined)
        self.assertIn("(ValidationText ", joined)
        self.assertFalse(any("Validation" in refusal.reason for refusal in refusals))

    def test_validation_placeholder_becomes_blocking_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R62] Preserve unresolved validation procedures. Check: validate later.\n"
            "***acceptance tests***\n"
            "- [covers:R62] Placeholder validation procedures remain blocking questions.\n",
            "semantic_validation_placeholder.plain",
        )

        validation = next(obj for obj in doc.objects if any(fact[0] == "Validation" for fact in obj.facts))
        facts = {fact[0]: fact for fact in validation.facts}
        self.assertEqual(facts["ValidationText"][2], "validate later")
        self.assertTrue(any(check.property == "validation-marker-reviewable" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingValidationDetail" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(MissingValidationDetail ", "\n".join(atoms))
        self.assertFalse(any("MissingValidationDetail" in refusal.reason for refusal in refusals))

    def test_verification_marker_alias_preserves_exact_span_before_evidence(self):
        source = (
            "***requirements***\n"
            "- [id:R65] Preserve verification procedure aliases. "
            "Verification: golden atoms match examples/minimal.expected.metta. "
            "Evidence: tests/test_compiler.py::CompilerTests.\n"
            "***acceptance tests***\n"
            "- [covers:R65] Verification aliases export as validation atoms.\n"
        )
        doc = compile_source(source, "semantic_verification_alias.plain")
        validation = next(obj for obj in doc.objects if any(fact[0] == "Validation" for fact in obj.facts))
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT and any(fact[0] == "Evidence" for fact in obj.facts))
        facts = {fact[0]: fact for fact in validation.facts}
        validation_span = next(span for span in doc.spans if span.id == validation.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(facts["ValidationText"][2], "golden atoms match examples/minimal.expected.metta")
        self.assertEqual(
            doc.files[0].text[validation_span.start_byte:validation_span.end_byte],
            "Verification: golden atoms match examples/minimal.expected.metta",
        )
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: tests/test_compiler.py::CompilerTests")
        self.assertLess(validation_span.end_byte, evidence_span.start_byte)
        self.assertTrue(any(check.property == "validation-marker-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Validation ", joined)
        self.assertIn("(ValidationText ", joined)
        self.assertFalse(any("Validation" in refusal.reason for refusal in refusals))

    def test_explicit_observation_marker_preserves_source_without_claiming_validation(self):
        source = (
            "***requirements***\n"
            "- [id:R69] Preserve reported operational observations. "
            "Observation: queue latency rose during the fixture replay. "
            "Evidence: tests/replay_latency.log.\n"
            "***acceptance tests***\n"
            "- [covers:R69] Observation atoms are exported.\n"
        )
        doc = compile_source(source, "semantic_observation.plain")
        observation = next(obj for obj in doc.objects if any(fact[0] == "Observation" for fact in obj.facts))
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT and any(fact[0] == "Evidence" for fact in obj.facts))
        facts = {fact[0]: fact for fact in observation.facts}
        observation_span = next(span for span in doc.spans if span.id == observation.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(facts["ObservationText"][2], "queue latency rose during the fixture replay")
        self.assertEqual(
            doc.files[0].text[observation_span.start_byte:observation_span.end_byte],
            "Observation: queue latency rose during the fixture replay",
        )
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: tests/replay_latency.log")
        self.assertLess(observation_span.end_byte, evidence_span.start_byte)
        self.assertTrue(any(check.property == "observation-has-source-provenance" and check.status == CheckStatus.PASS for check in doc.checks))
        self.assertFalse(any(check.property == "validation-marker-reviewable" and check.target_id == observation.id for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Observation ", joined)
        self.assertIn("(ObservationText ", joined)
        self.assertFalse(any("Observation" in refusal.reason for refusal in refusals))

    def test_explicit_hypothesis_marker_links_same_item_evidence_and_exports(self):
        source = (
            "***requirements***\n"
            "- [id:R66] Preserve hypothesis markers. "
            "Evidence: docs/hypothesis-review.md. "
            "Hypothesis: latency spikes come from queue contention.\n"
            "***acceptance tests***\n"
            "- [covers:R66] Hypothesis atoms are exported.\n"
        )
        doc = compile_source(source, "semantic_hypothesis.plain")
        hypothesis = next(obj for obj in doc.objects if any(fact[0] == "Hypothesis" for fact in obj.facts))
        facts = {fact[0]: fact for fact in hypothesis.facts}
        span = next(span for span in doc.spans if span.id == hypothesis.source_span_id)

        self.assertEqual(facts["HypothesisText"][2], "latency spikes come from queue contention")
        self.assertEqual(doc.files[0].text[span.start_byte:span.end_byte], "Hypothesis: latency spikes come from queue contention")
        self.assertTrue(any(fact[0] == "HypothesisEvidence" for fact in hypothesis.facts))
        self.assertTrue(any(check.property == "hypothesis-has-explicit-evidence" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Hypothesis ", joined)
        self.assertIn("(HypothesisText ", joined)
        self.assertFalse(any("Hypothesis" in refusal.reason for refusal in refusals))

    def test_hypothesis_without_evidence_becomes_blocking_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R67] Preserve unresolved hypotheses. "
            "Hypothesis: TODO validate the causal mechanism.\n"
            "***acceptance tests***\n"
            "- [covers:R67] Missing hypothesis evidence remains reviewable.\n",
            "semantic_hypothesis_question.plain",
        )

        self.assertTrue(any(check.property == "hypothesis-has-explicit-evidence" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingHypothesisEvidence" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(MissingHypothesisEvidence ", "\n".join(atoms))
        self.assertFalse(any("MissingHypothesisEvidence" in refusal.reason for refusal in refusals))

    def test_explicit_claim_marker_links_same_item_evidence_and_exports(self):
        source = (
            "***requirements***\n"
            "- [id:R70] Preserve explicit claim markers. "
            "Claim: the export is deterministic across repeated runs. "
            "Evidence: tests/test_cli.py::CliTests.\n"
            "***acceptance tests***\n"
            "- [covers:R70] Claim atoms are exported.\n"
        )
        doc = compile_source(source, "semantic_claim.plain")
        claim = next(obj for obj in doc.objects if any(fact[0] == "Claim" for fact in obj.facts))
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT and any(fact[0] == "Evidence" for fact in obj.facts))
        facts = {fact[0]: fact for fact in claim.facts}
        claim_span = next(span for span in doc.spans if span.id == claim.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(facts["ClaimText"][2], "the export is deterministic across repeated runs")
        self.assertEqual(doc.files[0].text[claim_span.start_byte:claim_span.end_byte], "Claim: the export is deterministic across repeated runs")
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: tests/test_cli.py::CliTests")
        self.assertLess(claim_span.end_byte, evidence_span.start_byte)
        self.assertTrue(any(fact[0] == "ClaimEvidence" for fact in claim.facts))
        self.assertTrue(any(check.property == "claim-has-explicit-evidence" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Claim ", joined)
        self.assertIn("(ClaimText ", joined)
        self.assertFalse(any("Claim" in refusal.reason for refusal in refusals))

    def test_claim_without_evidence_becomes_blocking_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R71] Preserve unsupported claims. "
            "Claim: raw text only implies executable behavior.\n"
            "***acceptance tests***\n"
            "- [covers:R71] Missing claim evidence remains reviewable.\n",
            "semantic_claim_question.plain",
        )

        self.assertTrue(any(check.property == "claim-has-explicit-evidence" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingClaimEvidence" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(MissingClaimEvidence ", "\n".join(atoms))
        self.assertFalse(any("MissingClaimEvidence" in refusal.reason for refusal in refusals))

    def test_explicit_axiom_marker_links_same_item_proof_and_exports(self):
        source = (
            "***requirements***\n"
            "- [id:R74] Preserve formalization axioms. "
            "Axiom: every exported object has a stable source span. "
            "Proof: specs/proofs/source_span_axiom.lean checks the invariant.\n"
            "***acceptance tests***\n"
            "- [covers:R74] Axiom atoms are exported.\n"
        )
        doc = compile_source(source, "semantic_axiom.plain")
        axiom = next(obj for obj in doc.objects if any(fact[0] == "Axiom" for fact in obj.facts))
        proof = next(obj for obj in doc.objects if any(fact[0] == "Proof" for fact in obj.facts))
        facts = {fact[0]: fact for fact in axiom.facts}
        axiom_span = next(span for span in doc.spans if span.id == axiom.source_span_id)
        proof_span = next(span for span in doc.spans if span.id == proof.source_span_id)

        self.assertEqual(facts["AxiomText"][2], "every exported object has a stable source span")
        self.assertEqual(doc.files[0].text[axiom_span.start_byte:axiom_span.end_byte], "Axiom: every exported object has a stable source span")
        self.assertEqual(doc.files[0].text[proof_span.start_byte:proof_span.end_byte], "Proof: specs/proofs/source_span_axiom.lean checks the invariant")
        self.assertLess(axiom_span.end_byte, proof_span.start_byte)
        self.assertTrue(any(fact[0] == "AxiomEvidence" and fact[2] == proof.id for fact in axiom.facts))
        self.assertTrue(any(check.property == "axiom-has-explicit-justification" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Axiom ", joined)
        self.assertIn("(AxiomText ", joined)
        self.assertFalse(any("Axiom" in refusal.reason for refusal in refusals))

    def test_axiom_without_justification_becomes_blocking_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R75] Preserve unsupported axioms. "
            "Axiom: raw text can be treated as verified executable behavior.\n"
            "***acceptance tests***\n"
            "- [covers:R75] Missing axiom justification remains reviewable.\n",
            "semantic_axiom_question.plain",
        )

        self.assertTrue(any(check.property == "axiom-has-explicit-justification" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingAxiomJustification" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(MissingAxiomJustification ", "\n".join(atoms))
        self.assertFalse(any("MissingAxiomJustification" in refusal.reason for refusal in refusals))

    def test_placeholder_proof_does_not_justify_axiom(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R76] Refuse unsupported axiom justification. "
            "Axiom: generated atoms are semantically complete. Proof: TODO prove later.\n"
            "***acceptance tests***\n"
            "- [covers:R76] Placeholder proof cannot justify an axiom.\n",
            "semantic_axiom_placeholder_proof.plain",
        )
        axiom = next(obj for obj in doc.objects if any(fact[0] == "Axiom" for fact in obj.facts))

        self.assertFalse(any(fact[0] == "AxiomEvidence" for fact in axiom.facts))
        self.assertTrue(any(check.property == "proof-marker-reviewable" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(check.property == "axiom-has-explicit-justification" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingAxiomJustification" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(MissingProofDetail ", joined)
        self.assertIn("(MissingAxiomJustification ", joined)
        self.assertFalse(any("Axiom" in refusal.reason or "Proof" in refusal.reason for refusal in refusals))

    def test_explicit_proof_marker_exports_reviewable_proof_artifact(self):
        source = (
            "***requirements***\n"
            "- [id:R72] Preserve formal proof markers. "
            "Proof: Lean theorem specs/proofs/AuthDeterminism.lean verifies determinism. "
            "Evidence: proof replay log out/auth-proof.log.\n"
            "***acceptance tests***\n"
            "- [covers:R72] Proof atoms are exported.\n"
        )
        doc = compile_source(source, "semantic_proof.plain")
        proof = next(obj for obj in doc.objects if any(fact[0] == "Proof" for fact in obj.facts))
        evidence = next(obj for obj in doc.objects if obj.role == Role.EVIDENCE_OBJECT and any(fact[0] == "Evidence" for fact in obj.facts))
        facts = {fact[0]: fact for fact in proof.facts}
        proof_span = next(span for span in doc.spans if span.id == proof.source_span_id)
        evidence_span = next(span for span in doc.spans if span.id == evidence.source_span_id)

        self.assertEqual(facts["ProofText"][2], "Lean theorem specs/proofs/AuthDeterminism.lean verifies determinism")
        self.assertEqual(doc.files[0].text[proof_span.start_byte:proof_span.end_byte], "Proof: Lean theorem specs/proofs/AuthDeterminism.lean verifies determinism")
        self.assertEqual(doc.files[0].text[evidence_span.start_byte:evidence_span.end_byte], "Evidence: proof replay log out/auth-proof.log")
        self.assertLess(proof_span.end_byte, evidence_span.start_byte)
        self.assertTrue(any(check.property == "proof-marker-reviewable" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Proof ", joined)
        self.assertIn("(ProofText ", joined)
        self.assertFalse(any("Proof" in refusal.reason for refusal in refusals))

    def test_proof_placeholder_becomes_blocking_question(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R73] Preserve unresolved proof markers. "
            "Proof: TODO prove later.\n"
            "***acceptance tests***\n"
            "- [covers:R73] Missing proof detail remains reviewable.\n",
            "semantic_proof_question.plain",
        )

        self.assertTrue(any(check.property == "proof-marker-reviewable" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingProofDetail" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn("(MissingProofDetail ", "\n".join(atoms))
        self.assertFalse(any("MissingProofDetail" in refusal.reason for refusal in refusals))

    def test_explicit_precondition_and_postcondition_markers_link_same_item_evidence(self):
        source = (
            "***requirements***\n"
            "- [id:R63] Preserve formal condition markers. "
            "Evidence: tests/test_conditions.py::ConditionTests. "
            "Precondition: request is authenticated before mutation. "
            "Postcondition: audit event is appended after mutation.\n"
            "***acceptance tests***\n"
            "- [covers:R63] Precondition and postcondition atoms are exported.\n"
        )
        doc = compile_source(source, "semantic_conditions.plain")
        precondition = next(obj for obj in doc.objects if any(fact[0] == "Precondition" for fact in obj.facts))
        postcondition = next(obj for obj in doc.objects if any(fact[0] == "Postcondition" for fact in obj.facts))
        pre_facts = {fact[0]: fact for fact in precondition.facts}
        post_facts = {fact[0]: fact for fact in postcondition.facts}
        pre_span = next(span for span in doc.spans if span.id == precondition.source_span_id)
        post_span = next(span for span in doc.spans if span.id == postcondition.source_span_id)

        self.assertEqual(pre_facts["PreconditionText"][2], "request is authenticated before mutation")
        self.assertEqual(post_facts["PostconditionText"][2], "audit event is appended after mutation")
        self.assertIn("Precondition: request is authenticated before mutation", doc.files[0].text[pre_span.start_byte:pre_span.end_byte])
        self.assertIn("Postcondition: audit event is appended after mutation", doc.files[0].text[post_span.start_byte:post_span.end_byte])
        self.assertTrue(any(fact[0] == "PreconditionEvidence" for fact in precondition.facts))
        self.assertTrue(any(fact[0] == "PostconditionEvidence" for fact in postcondition.facts))
        self.assertTrue(any(check.property == "precondition-has-explicit-evidence" and check.status == CheckStatus.PASS for check in doc.checks))
        self.assertTrue(any(check.property == "postcondition-has-explicit-evidence" and check.status == CheckStatus.PASS for check in doc.checks))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Precondition ", joined)
        self.assertIn("(Postcondition ", joined)
        self.assertFalse(any("Precondition" in refusal.reason or "Postcondition" in refusal.reason for refusal in refusals))

    def test_precondition_and_postcondition_without_evidence_become_blocking_questions(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R64] Preserve unresolved conditions. "
            "Precondition: caller has tenant access. Postcondition: cache is invalidated.\n"
            "***acceptance tests***\n"
            "- [covers:R64] Missing condition evidence remains reviewable.\n",
            "semantic_condition_questions.plain",
        )

        self.assertTrue(any(check.property == "precondition-has-explicit-evidence" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(check.property == "postcondition-has-explicit-evidence" and check.status == CheckStatus.UNKNOWN for check in doc.checks))
        self.assertTrue(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingPreconditionEvidence" for fact in obj.facts) for obj in doc.objects))
        self.assertTrue(any(obj.role == Role.QUESTION_OBJECT and any(fact[0] == "MissingPostconditionEvidence" for fact in obj.facts) for obj in doc.objects))
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(MissingPreconditionEvidence ", joined)
        self.assertIn("(MissingPostconditionEvidence ", joined)
        self.assertFalse(any("MissingPreconditionEvidence" in refusal.reason or "MissingPostconditionEvidence" in refusal.reason for refusal in refusals))


if __name__ == "__main__":
    unittest.main()

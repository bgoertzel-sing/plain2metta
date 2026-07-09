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


if __name__ == "__main__":
    unittest.main()

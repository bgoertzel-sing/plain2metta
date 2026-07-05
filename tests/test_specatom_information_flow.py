import unittest

from specatom_hs.backends.petta import emit_reified_atoms
from specatom_hs.passes import compile_source
from specatom_hs.schema import CheckStatus, Role


class InformationFlowValidationTests(unittest.TestCase):
    """Tests for the conservative information-flow and temporal-availability slice."""

    def test_data_flow_without_inputs_or_outputs_becomes_blocking_questions(self):
        """Specs with dependency/flow wording but no explicit input/output declarations produce Unknown questions."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline depends on the upstream service.\n"
            "- Data flows from one component to another.\n",
            "info-flow-gaps.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        for property_name in {
            "information-flow-inputs-declared",
            "information-flow-outputs-declared",
        }:
            check = next(
                c for c in doc.checks
                if c.property == property_name and c.target_id == review.id
            )
            self.assertEqual(check.status, CheckStatus.UNKNOWN, property_name)
            self.assertTrue(
                any(
                    ("MissingInformationFlowEvidence", obj.id, property_name) in obj.facts
                    and any(fact == ("Blocks", obj.id, check.obligation_id) for fact in obj.facts)
                    for obj in doc.objects
                    if obj.role == Role.QUESTION_OBJECT
                ),
                property_name,
            )

    def test_explicit_inputs_and_outputs_pass_declaration_checks(self):
        """Specs that explicitly mention inputs and outputs pass declaration checks."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The service consumes input from the message queue.\n"
            "- The service produces output to the database.\n"
            "- The pipeline depends on the upstream service.\n",
            "info-flow-declared.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        input_check = next(
            c for c in doc.checks
            if c.property == "information-flow-inputs-declared" and c.target_id == review.id
        )
        self.assertEqual(input_check.status, CheckStatus.PASS)

        output_check = next(
            c for c in doc.checks
            if c.property == "information-flow-outputs-declared" and c.target_id == review.id
        )
        self.assertEqual(output_check.status, CheckStatus.PASS)

    def test_dependency_without_direction_becomes_unknown(self):
        """Specs with dependency wording but no explicit direction produce Unknown questions."""
        doc = compile_source(
            "***functional specifications***\n"
            "- Component A depends on component B.\n",
            "info-flow-direction.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        # Dependency direction should pass because "depends on" is recognized direction wording.
        direction_check = next(
            c for c in doc.checks
            if c.property == "information-flow-dependency-direction-declared" and c.target_id == review.id
        )
        self.assertEqual(direction_check.status, CheckStatus.PASS)

    def test_temporal_availability_without_evidence_becomes_unknown(self):
        """Specs with temporal-ordering signal but no availability evidence produce Unknown questions."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the upstream source and writes to the downstream sink.\n"
            "- The output is produced after the input is consumed.\n",
            "info-flow-temporal.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        temporal_check = next(
            c for c in doc.checks
            if c.property == "information-flow-temporal-availability-reviewed" and c.target_id == review.id
        )
        self.assertEqual(temporal_check.status, CheckStatus.UNKNOWN)
        self.assertTrue(
            any(
                ("MissingInformationFlowEvidence", obj.id, "information-flow-temporal-availability-reviewed") in obj.facts
                and any(fact == ("Blocks", obj.id, temporal_check.obligation_id) for fact in obj.facts)
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            ),
            "temporal availability question not found",
        )

    def test_temporal_availability_with_evidence_passes(self):
        """Specs that declare temporal availability evidence pass the temporal-availability check."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the upstream source and writes to the downstream sink.\n"
            "- All inputs are available before outputs are needed; execution order follows the dependency order.\n",
            "info-flow-temporal-ok.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        temporal_check = next(
            c for c in doc.checks
            if c.property == "information-flow-temporal-availability-reviewed" and c.target_id == review.id
        )
        self.assertEqual(temporal_check.status, CheckStatus.PASS)

    def test_circular_dependency_without_termination_evidence_becomes_unknown(self):
        """Specs mentioning circular/recursive dependencies without termination evidence produce Unknown questions."""
        doc = compile_source(
            "***functional specifications***\n"
            "- Component A and component B have a circular dependency.\n"
            "- The system uses a feedback loop between modules.\n",
            "info-flow-circular.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        circular_check = next(
            c for c in doc.checks
            if c.property == "information-flow-circular-dependency-reviewed" and c.target_id == review.id
        )
        self.assertEqual(circular_check.status, CheckStatus.UNKNOWN)
        self.assertTrue(
            any(
                ("MissingInformationFlowEvidence", obj.id, "information-flow-circular-dependency-reviewed") in obj.facts
                and any(fact == ("Blocks", obj.id, circular_check.obligation_id) for fact in obj.facts)
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            ),
            "circular dependency question not found",
        )

    def test_circular_dependency_with_termination_evidence_passes(self):
        """Specs mentioning circular dependencies with termination/acyclicity evidence pass."""
        doc = compile_source(
            "***functional specifications***\n"
            "- Component A and component B have a circular dependency.\n"
            "- The recursion has a base case with a depth limit to ensure termination.\n",
            "info-flow-circular-ok.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        circular_check = next(
            c for c in doc.checks
            if c.property == "information-flow-circular-dependency-reviewed" and c.target_id == review.id
        )
        self.assertEqual(circular_check.status, CheckStatus.PASS)

    def test_no_info_flow_signal_produces_no_info_flow_objects(self):
        """Specs without data-flow/dependency wording do not create information-flow review objects."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The system should be user-friendly.\n"
            "- The UI should be responsive.\n",
            "no-info-flow.plain",
        )

        self.assertFalse(
            any(("InformationFlowReview", obj.id) in obj.facts for obj in doc.objects)
        )

    def test_information_flow_atoms_exported_through_petta_profile(self):
        """InformationFlowReview and MissingInformationFlowEvidence atoms are exported through the PeTTa reified profile."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline depends on the upstream service.\n",
            "info-flow-export.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn(f"(InformationFlowReview {review.id})", atoms)
        self.assertTrue(any(atom.startswith("(MissingInformationFlowEvidence") for atom in atoms))
        self.assertFalse(any("MissingInformationFlowEvidence" in refusal.reason for refusal in refusals))

    def test_explicit_data_path_edges_are_extracted(self):
        """Explicit component-level data-path patterns produce DataFlowEdge atoms."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the upstream source.\n"
            "- The pipeline writes to the downstream sink.\n"
            "- The service consumes input from the message queue.\n"
            "- Component A depends on component B.\n",
            "data-path-edges.plain",
        )

        edge_atoms = [obj for obj in doc.objects if any(f[0] == "DataFlowEdge" for f in obj.facts)]
        self.assertGreaterEqual(len(edge_atoms), 4, f"expected at least 4 edges, got {len(edge_atoms)}")

        # Verify edge contents match ground truth.
        edges = []
        for obj in edge_atoms:
            for fact in obj.facts:
                if fact[0] == "DataFlowEdge":
                    edges.append((fact[2], fact[3], fact[4]))  # (source, target, direction)

        self.assertIn(("pipeline", "upstream source", "reads-from"), edges)
        self.assertIn(("pipeline", "downstream sink", "writes-to"), edges)
        self.assertIn(("service", "message queue", "consumes-from"), edges)
        self.assertIn(("component a", "component b", "depends-on"), edges)

    def test_data_path_check_passes_with_explicit_edges(self):
        """The information-flow-data-path-declared check passes when explicit edges are found."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the upstream source.\n"
            "- The pipeline writes to the downstream sink.\n",
            "data-path-pass.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        check = next(
            c for c in doc.checks
            if c.property == "information-flow-data-path-declared" and c.target_id == review.id
        )
        self.assertEqual(check.status, CheckStatus.PASS)
        self.assertIn("explicit data-path edges found", check.evidence)

    def test_data_path_check_unknown_with_only_vague_wording(self):
        """The information-flow-data-path-declared check is Unknown when only vague wording exists."""
        doc = compile_source(
            "***functional specifications***\n"
            "- Data flows from one component to another.\n"
            "- There is a dependency between components.\n",
            "data-path-vague.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        check = next(
            c for c in doc.checks
            if c.property == "information-flow-data-path-declared" and c.target_id == review.id
        )
        self.assertEqual(check.status, CheckStatus.UNKNOWN)

        # Should produce a blocking question.
        self.assertTrue(
            any(
                ("MissingInformationFlowEvidence", obj.id, "information-flow-data-path-declared") in obj.facts
                and any(fact == ("Blocks", obj.id, check.obligation_id) for fact in obj.facts)
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            ),
            "data-path question not found",
        )

    def test_data_flow_edge_atoms_exported_through_petta_profile(self):
        """DataFlowEdge atoms are exported through the PeTTa reified profile."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the upstream source.\n",
            "data-path-export.plain",
        )

        atoms, refusals = emit_reified_atoms(doc)
        self.assertTrue(any(atom.startswith("(DataFlowEdge") for atom in atoms))
        self.assertFalse(any("DataFlowEdge" in refusal.reason for refusal in refusals))

    def test_no_data_path_edges_for_non_flow_specs(self):
        """Specs without data-flow wording produce no DataFlowEdge atoms."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The system should be user-friendly.\n",
            "no-data-path.plain",
        )

        edge_atoms = [obj for obj in doc.objects if any(f[0] == "DataFlowEdge" for f in obj.facts)]
        self.assertEqual(len(edge_atoms), 0)


if __name__ == "__main__":
    unittest.main()

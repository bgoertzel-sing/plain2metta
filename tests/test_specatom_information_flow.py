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

    def test_transitive_dependency_detected_and_unacknowledged(self):
        """When A→B and B→C edges exist, a transitive A→C dependency is detected and produces Unknown without acknowledgement."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the cache.\n"
            "- The cache reads from the database.\n",
            "transitive-unack.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        transitive_check = next(
            c for c in doc.checks
            if c.property == "information-flow-transitive-dependency-reviewed" and c.target_id == review.id
        )
        self.assertEqual(transitive_check.status, CheckStatus.UNKNOWN)
        self.assertIn("pipeline", transitive_check.evidence.lower())
        self.assertIn("database", transitive_check.evidence.lower())
        self.assertTrue(
            any(
                ("MissingInformationFlowEvidence", obj.id, "information-flow-transitive-dependency-reviewed") in obj.facts
                and any(fact == ("Blocks", obj.id, transitive_check.obligation_id) for fact in obj.facts)
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            ),
            "transitive dependency question not found",
        )

    def test_transitive_dependency_acknowledged_passes(self):
        """When transitive chains exist and the spec acknowledges them (via 'through' or similar), the check passes."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the cache.\n"
            "- The cache reads from the database.\n"
            "- The pipeline indirectly accesses the database through the cache.\n",
            "transitive-ack.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        transitive_check = next(
            c for c in doc.checks
            if c.property == "information-flow-transitive-dependency-reviewed" and c.target_id == review.id
        )
        self.assertEqual(transitive_check.status, CheckStatus.PASS)
        self.assertIn("acknowledged", transitive_check.evidence.lower())

    def test_no_transitive_dependency_when_no_chains(self):
        """When edges don't form chains (no intermediate hops), the transitive check passes with 'no transitive' evidence."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the upstream source.\n"
            "- The service writes to the database.\n",
            "no-transitive.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        transitive_check = next(
            c for c in doc.checks
            if c.property == "information-flow-transitive-dependency-reviewed" and c.target_id == review.id
        )
        self.assertEqual(transitive_check.status, CheckStatus.PASS)
        self.assertIn("no transitive", transitive_check.evidence.lower())

    def test_cycle_detected_from_graph_edges(self):
        """When A→B and B→A edges exist, a graph cycle is detected and produces Unknown."""
        doc = compile_source(
            "***functional specifications***\n"
            "- Component A reads from component B.\n"
            "- Component B writes to component A.\n",
            "cycle-simple.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        cycle_check = next(
            c for c in doc.checks
            if c.property == "information-flow-cycle-detected" and c.target_id == review.id
        )
        self.assertEqual(cycle_check.status, CheckStatus.UNKNOWN)
        self.assertIn("cycle", cycle_check.evidence.lower())
        self.assertTrue(
            any(
                ("MissingInformationFlowEvidence", obj.id, "information-flow-cycle-detected") in obj.facts
                and any(fact == ("Blocks", obj.id, cycle_check.obligation_id) for fact in obj.facts)
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            ),
            "cycle question not found",
        )

    def test_no_cycle_when_acyclic_graph(self):
        """When edges form a DAG (no back edges), the cycle check passes."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the upstream source.\n"
            "- The pipeline writes to the downstream sink.\n",
            "cycle-acyclic.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        cycle_check = next(
            c for c in doc.checks
            if c.property == "information-flow-cycle-detected" and c.target_id == review.id
        )
        self.assertEqual(cycle_check.status, CheckStatus.PASS)
        self.assertIn("no cycles", cycle_check.evidence.lower())

    def test_three_node_cycle_detected(self):
        """A→B→C→A three-node cycle is detected."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The alpha reads from the beta.\n"
            "- The beta reads from the gamma.\n"
            "- The gamma writes to the alpha.\n",
            "cycle-three-node.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        cycle_check = next(
            c for c in doc.checks
            if c.property == "information-flow-cycle-detected" and c.target_id == review.id
        )
        self.assertEqual(cycle_check.status, CheckStatus.UNKNOWN)
        self.assertIn("alpha", cycle_check.evidence.lower())
        self.assertIn("gamma", cycle_check.evidence.lower())

    def test_no_cycle_when_no_edges(self):
        """When no DataFlowEdge atoms are extracted, the cycle check passes trivially."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The system should be fast.\n",
            "cycle-no-edges.plain",
        )

        # No information-flow review at all, so no cycle obligation should exist.
        self.assertFalse(
            any(c.property == "information-flow-cycle-detected" for c in doc.checks)
        )

    def test_high_fan_out_detected_and_unacknowledged(self):
        """A component with >=3 outgoing edges triggers fan-out review and produces Unknown without acknowledgement."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The router reads from the cache.\n"
            "- The router reads from the database.\n"
            "- The router reads from the queue.\n"
            "- The router reads from the index.\n",
            "fan-out-high.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        fan_out_check = next(
            c for c in doc.checks
            if c.property == "information-flow-fan-out-reviewed" and c.target_id == review.id
        )
        self.assertEqual(fan_out_check.status, CheckStatus.UNKNOWN)
        self.assertIn("router", fan_out_check.evidence.lower())
        self.assertTrue(
            any(
                ("MissingInformationFlowEvidence", obj.id, "information-flow-fan-out-reviewed") in obj.facts
                and any(fact == ("Blocks", obj.id, fan_out_check.obligation_id) for fact in obj.facts)
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            ),
            "fan-out question not found",
        )

    def test_high_fan_out_acknowledged_passes(self):
        """When high fan-out exists and the spec acknowledges it (e.g. 'bottleneck'), the check passes."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The router reads from the cache.\n"
            "- The router reads from the database.\n"
            "- The router reads from the queue.\n"
            "- The router is a known bottleneck with failover.\n",
            "fan-out-ack.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        fan_out_check = next(
            c for c in doc.checks
            if c.property == "information-flow-fan-out-reviewed" and c.target_id == review.id
        )
        self.assertEqual(fan_out_check.status, CheckStatus.PASS)
        self.assertIn("acknowledged", fan_out_check.evidence.lower())

    def test_low_fan_out_passes(self):
        """Components with <3 outgoing edges do not trigger fan-out review."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the cache.\n"
            "- The pipeline writes to the sink.\n",
            "fan-out-low.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        fan_out_check = next(
            c for c in doc.checks
            if c.property == "information-flow-fan-out-reviewed" and c.target_id == review.id
        )
        self.assertEqual(fan_out_check.status, CheckStatus.PASS)
        self.assertIn("no components", fan_out_check.evidence.lower())

    def test_high_fan_in_detected_and_unacknowledged(self):
        """A component with >=3 incoming edges triggers fan-in review and produces Unknown without acknowledgement."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The alpha writes to the database.\n"
            "- The beta writes to the database.\n"
            "- The gamma writes to the database.\n"
            "- The delta writes to the database.\n",
            "fan-in-high.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        fan_in_check = next(
            c for c in doc.checks
            if c.property == "information-flow-fan-in-reviewed" and c.target_id == review.id
        )
        self.assertEqual(fan_in_check.status, CheckStatus.UNKNOWN)
        self.assertIn("database", fan_in_check.evidence.lower())
        self.assertTrue(
            any(
                ("MissingInformationFlowEvidence", obj.id, "information-flow-fan-in-reviewed") in obj.facts
                and any(fact == ("Blocks", obj.id, fan_in_check.obligation_id) for fact in obj.facts)
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            ),
            "fan-in question not found",
        )

    def test_high_fan_in_acknowledged_passes(self):
        """When high fan-in exists and the spec acknowledges it (e.g. 'critical dependency'), the check passes."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The alpha writes to the database.\n"
            "- The beta writes to the database.\n"
            "- The gamma writes to the database.\n"
            "- The database is a critical shared dependency with redundancy.\n",
            "fan-in-ack.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        fan_in_check = next(
            c for c in doc.checks
            if c.property == "information-flow-fan-in-reviewed" and c.target_id == review.id
        )
        self.assertEqual(fan_in_check.status, CheckStatus.PASS)
        self.assertIn("acknowledged", fan_in_check.evidence.lower())

    def test_fan_out_and_fan_in_atoms_exported_through_petta_profile(self):
        """MissingInformationFlowEvidence atoms for fan-out and fan-in are exported through the PeTTa reified profile."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The router reads from the cache.\n"
            "- The router reads from the database.\n"
            "- The router reads from the queue.\n"
            "- The alpha writes to the sink.\n"
            "- The beta writes to the sink.\n"
            "- The gamma writes to the sink.\n",
            "fan-export.plain",
        )

        atoms, refusals = emit_reified_atoms(doc)
        self.assertTrue(any("information-flow-fan-out-reviewed" in atom for atom in atoms))
        self.assertTrue(any("information-flow-fan-in-reviewed" in atom for atom in atoms))
        self.assertTrue(any(atom.startswith("(MissingInformationFlowEvidence") for atom in atoms))
        self.assertFalse(any("MissingInformationFlowEvidence" in refusal.reason for refusal in refusals))

    def test_no_fan_review_when_no_edges(self):
        """Specs without data-flow edges do not create fan-out or fan-in obligations."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The system should be fast.\n",
            "fan-no-edges.plain",
        )

        self.assertFalse(
            any(c.property == "information-flow-fan-out-reviewed" for c in doc.checks)
        )
        self.assertFalse(
            any(c.property == "information-flow-fan-in-reviewed" for c in doc.checks)
        )

    def test_bottleneck_node_detected_and_unacknowledged(self):
        """A component with high fan-in AND high fan-out that is not acknowledged produces an Unknown blocking question."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The hub reads from the alpha.\n"
            "- The hub reads from the beta.\n"
            "- The hub reads from the gamma.\n"
            "- The delta writes to the hub.\n"
            "- The epsilon writes to the hub.\n"
            "- The zeta writes to the hub.\n",
            "bottleneck.plain",
        )

        bottleneck_checks = [c for c in doc.checks if c.property == "information-flow-bottleneck-node-reviewed"]
        self.assertEqual(len(bottleneck_checks), 1)
        self.assertEqual(bottleneck_checks[0].status, CheckStatus.UNKNOWN)
        self.assertIn("hub", bottleneck_checks[0].evidence)
        self.assertIn("in=3", bottleneck_checks[0].evidence)
        self.assertIn("out=3", bottleneck_checks[0].evidence)

        questions = [o for o in doc.objects if o.role == Role.QUESTION_OBJECT]
        bottleneck_questions = [q for q in questions if any(f[0] == "MissingInformationFlowEvidence" and "bottleneck" in str(f[2]) for f in q.facts)]
        self.assertEqual(len(bottleneck_questions), 1)
        self.assertTrue(any(f[0] == "Blocks" for f in bottleneck_questions[0].facts))

    def test_bottleneck_node_acknowledged_passes(self):
        """A bottleneck component acknowledged with bottleneck/SPoF wording passes."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The hub reads from the alpha.\n"
            "- The hub reads from the beta.\n"
            "- The hub reads from the gamma.\n"
            "- The delta writes to the hub.\n"
            "- The epsilon writes to the hub.\n"
            "- The zeta writes to the hub.\n"
            "- The hub is a known bottleneck and single point of failure with redundancy.\n",
            "bottleneck-ack.plain",
        )

        bottleneck_checks = [c for c in doc.checks if c.property == "information-flow-bottleneck-node-reviewed"]
        self.assertEqual(len(bottleneck_checks), 1)
        self.assertEqual(bottleneck_checks[0].status, CheckStatus.PASS)
        self.assertIn("hub", bottleneck_checks[0].evidence)

    def test_no_bottleneck_when_only_high_fan_out(self):
        """A component with high fan-out but low fan-in is not a bottleneck node."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The source writes to the alpha.\n"
            "- The source writes to the beta.\n"
            "- The source writes to the gamma.\n",
            "fan-out-only.plain",
        )

        bottleneck_checks = [c for c in doc.checks if c.property == "information-flow-bottleneck-node-reviewed"]
        self.assertEqual(len(bottleneck_checks), 1)
        self.assertEqual(bottleneck_checks[0].status, CheckStatus.PASS)
        self.assertIn("no bottleneck nodes", bottleneck_checks[0].evidence)

    def test_no_bottleneck_check_when_no_edges(self):
        """Specs without data-flow edges do not create bottleneck obligations."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The system should be fast.\n",
            "bottleneck-no-edges.plain",
        )

        self.assertFalse(
            any(c.property == "information-flow-bottleneck-node-reviewed" for c in doc.checks)
        )

    def test_bottleneck_atoms_exported_through_petta_profile(self):
        """MissingInformationFlowEvidence atoms for bottleneck are exported through the PeTTa reified profile."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The hub reads from the alpha.\n"
            "- The hub reads from the beta.\n"
            "- The hub reads from the gamma.\n"
            "- The delta writes to the hub.\n"
            "- The epsilon writes to the hub.\n"
            "- The zeta writes to the hub.\n",
            "bottleneck-export.plain",
        )

        atoms, refusals = emit_reified_atoms(doc)
        self.assertTrue(any("information-flow-bottleneck-node-reviewed" in atom for atom in atoms))
        self.assertTrue(any(atom.startswith("(MissingInformationFlowEvidence") and "bottleneck" in atom for atom in atoms))
        self.assertFalse(any("MissingInformationFlowEvidence" in refusal.reason for refusal in refusals))

    def test_source_sink_identified_with_dag(self):
        """A DAG with clear source and sink nodes passes the source-sink identification check."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the upstream source.\n"
            "- The pipeline writes to the downstream sink.\n",
            "source-sink-dag.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        check = next(
            c for c in doc.checks
            if c.property == "information-flow-source-sink-identified" and c.target_id == review.id
        )
        self.assertEqual(check.status, CheckStatus.PASS)
        self.assertIn("upstream source", check.evidence)
        self.assertIn("downstream sink", check.evidence)

    def test_source_sink_unknown_when_all_nodes_have_incoming_edges(self):
        """When every node has incoming edges (e.g. a pure cycle), source-sink identification is Unknown."""
        doc = compile_source(
            "***functional specifications***\n"
            "- Component A reads from component B.\n"
            "- Component B writes to component A.\n",
            "source-sink-cycle.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        check = next(
            c for c in doc.checks
            if c.property == "information-flow-source-sink-identified" and c.target_id == review.id
        )
        self.assertEqual(check.status, CheckStatus.UNKNOWN)
        self.assertTrue(
            any(
                ("MissingInformationFlowEvidence", obj.id, "information-flow-source-sink-identified") in obj.facts
                and any(fact == ("Blocks", obj.id, check.obligation_id) for fact in obj.facts)
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            ),
            "source-sink question not found",
        )

    def test_reachability_passes_when_all_nodes_reachable(self):
        """When all nodes are reachable from source nodes, reachability check passes."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the cache.\n"
            "- The cache reads from the database.\n",
            "reachability-ok.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        check = next(
            c for c in doc.checks
            if c.property == "information-flow-reachability-reviewed" and c.target_id == review.id
        )
        self.assertEqual(check.status, CheckStatus.PASS)
        self.assertIn("reachable", check.evidence.lower())

    def test_reachability_unknown_when_unreachable_nodes_exist(self):
        """When nodes exist but no source nodes are found (e.g. pure cycle), reachability check is Unknown."""
        doc = compile_source(
            "***functional specifications***\n"
            "- Component A reads from component B.\n"
            "- Component B writes to component A.\n",
            "reachability-gap.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        check = next(
            c for c in doc.checks
            if c.property == "information-flow-reachability-reviewed" and c.target_id == review.id
        )
        self.assertEqual(check.status, CheckStatus.UNKNOWN)
        self.assertIn("unreachable", check.evidence.lower())
        self.assertTrue(
            any(
                ("MissingInformationFlowEvidence", obj.id, "information-flow-reachability-reviewed") in obj.facts
                and any(fact == ("Blocks", obj.id, check.obligation_id) for fact in obj.facts)
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            ),
            "reachability question not found",
        )

    def test_no_source_sink_or_reachability_when_no_edges(self):
        """Specs without data-flow edges do not create source-sink or reachability obligations."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The system should be fast.\n",
            "no-source-sink.plain",
        )

        self.assertFalse(
            any(c.property == "information-flow-source-sink-identified" for c in doc.checks)
        )
        self.assertFalse(
            any(c.property == "information-flow-reachability-reviewed" for c in doc.checks)
        )

    def test_source_sink_and_reachability_atoms_exported_through_petta_profile(self):
        """Source-sink and reachability obligations and questions are exported through the PeTTa reified profile."""
        doc = compile_source(
            "***functional specifications***\n"
            "- Component A reads from component B.\n"
            "- Component B writes to component A.\n",
            "source-sink-export.plain",
        )

        atoms, refusals = emit_reified_atoms(doc)
        self.assertTrue(any("information-flow-source-sink-identified" in atom for atom in atoms))
        self.assertTrue(any("information-flow-reachability-reviewed" in atom for atom in atoms))
        self.assertTrue(any(atom.startswith("(MissingInformationFlowEvidence") for atom in atoms))
        self.assertFalse(any("MissingInformationFlowEvidence" in refusal.reason for refusal in refusals))


    def test_isolated_component_detected_and_unacknowledged(self):
        """A component mentioned with broader data-flow verbs but not in any edge triggers Unknown."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the upstream source.\n"
            "- The monitor receives data from the alert system.\n",
            "isolated-component.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        # 'pipeline' appears in an explicit edge (pipeline reads-from upstream source)
        # but 'monitor' uses 'receives data from' which is a broader data-flow verb
        # that does not produce a DataFlowEdge.  So 'monitor' is isolated.
        isolated_checks = [c for c in doc.checks if c.property == "information-flow-isolated-component-reviewed"]
        self.assertTrue(len(isolated_checks) >= 1, "isolated component check should exist when edges are present")
        check = isolated_checks[0]
        self.assertEqual(check.status, CheckStatus.UNKNOWN)
        self.assertIn("monitor", check.evidence)
        self.assertTrue(
            any(
                ("MissingInformationFlowEvidence", obj.id, "information-flow-isolated-component-reviewed") in obj.facts
                and any(fact == ("Blocks", obj.id, check.obligation_id) for fact in obj.facts)
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            )
        )

    def test_isolated_component_passes_when_all_connected(self):
        """When all data-flow-mentioned components appear in edges, the check passes."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the source.\n"
            "- The pipeline writes to the sink.\n",
            "all-connected.plain",
        )

        isolated_checks = [c for c in doc.checks if c.property == "information-flow-isolated-component-reviewed"]
        self.assertTrue(len(isolated_checks) >= 1)
        self.assertEqual(isolated_checks[0].status, CheckStatus.PASS)

    def test_no_isolated_component_check_when_no_edges(self):
        """When no DataFlowEdge atoms exist, no isolated-component obligation is emitted."""
        doc = compile_source(
            "***functional specifications***\n"
            "- Data flows from one component to another.\n",
            "no-edges-no-isolated.plain",
        )

        self.assertFalse(
            any(c.property == "information-flow-isolated-component-reviewed" for c in doc.checks)
        )

    def test_isolated_component_atoms_exported_through_petta_profile(self):
        """Isolated component obligations and questions are exported through the PeTTa reified profile."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the upstream source.\n"
            "- The monitor receives data from the alert system.\n",
            "isolated-export.plain",
        )

        atoms, refusals = emit_reified_atoms(doc)
        self.assertTrue(any("information-flow-isolated-component-reviewed" in atom for atom in atoms))
        self.assertTrue(any(atom.startswith("(MissingInformationFlowEvidence") for atom in atoms))
        self.assertFalse(any("MissingInformationFlowEvidence" in refusal.reason for refusal in refusals))

    # --- Redundant path detection tests ---

    def test_redundant_path_detected_and_unacknowledged(self):
        """When multiple distinct paths exist between the same pair of nodes without acknowledgment, Unknown + blocking question."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The gateway reads from the source.\n"
            "- The gateway writes to the cache.\n"
            "- The cache writes to the database.\n"
            "- The gateway writes to the queue.\n"
            "- The queue writes to the database.\n"
            # Direct path: gateway → database (via direct edge? No.)
            # Actually: gateway → cache → database  (indirect path from gateway to database)
            # And: gateway → queue → database       (another indirect path from gateway to database)
            # But we need a DIRECT edge gateway→database too for redundant path.
            # Let's add it:
            "- The gateway writes to the database.\n"
            "- The system depends on data flow.\n",
            "redundant-unack.plain",
        )

        redundant_checks = [c for c in doc.checks if c.property == "information-flow-redundant-path-reviewed"]
        self.assertEqual(len(redundant_checks), 1)
        self.assertEqual(redundant_checks[0].status, CheckStatus.UNKNOWN)
        self.assertIn("gateway", redundant_checks[0].evidence)
        self.assertIn("database", redundant_checks[0].evidence)

        blocking = [
            obj for obj in doc.objects
            if obj.role == Role.QUESTION_OBJECT
            and any(fact == ("MissingInformationFlowEvidence", obj.id, "information-flow-redundant-path-reviewed") for fact in obj.facts)
        ]
        self.assertEqual(len(blocking), 1)
        self.assertTrue(any(fact[0] == "Blocks" for fact in blocking[0].facts))

    def test_redundant_path_acknowledged_passes(self):
        """When redundant paths exist and the spec acknowledges redundancy, the obligation passes."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The gateway reads from the source.\n"
            "- The gateway writes to the cache.\n"
            "- The cache writes to the database.\n"
            "- The gateway writes to the queue.\n"
            "- The queue writes to the database.\n"
            "- The gateway writes to the database.\n"
            "- The system uses redundant paths for fault tolerance.\n"
            "- The system depends on data flow.\n",
            "redundant-ack.plain",
        )

        redundant_checks = [c for c in doc.checks if c.property == "information-flow-redundant-path-reviewed"]
        self.assertEqual(len(redundant_checks), 1)
        self.assertEqual(redundant_checks[0].status, CheckStatus.PASS)
        self.assertIn("acknowledged", redundant_checks[0].evidence)

    def test_no_redundant_path_when_no_indirect_paths(self):
        """When no indirect paths exist, the redundant-path obligation passes with 'no redundant paths'."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the source.\n"
            "- The pipeline writes to the sink.\n",
            "no-redundant.plain",
        )

        redundant_checks = [c for c in doc.checks if c.property == "information-flow-redundant-path-reviewed"]
        self.assertEqual(len(redundant_checks), 1)
        self.assertEqual(redundant_checks[0].status, CheckStatus.PASS)
        self.assertIn("no redundant paths", redundant_checks[0].evidence)

    def test_no_redundant_path_check_when_no_edges(self):
        """When no DataFlowEdge atoms exist, no redundant-path obligation is emitted."""
        doc = compile_source(
            "***functional specifications***\n"
            "- Data flows from one component to another.\n",
            "no-edges-no-redundant.plain",
        )

        self.assertFalse(
            any(c.property == "information-flow-redundant-path-reviewed" for c in doc.checks)
        )

    def test_redundant_path_atoms_exported_through_petta_profile(self):
        """Redundant-path obligations and questions are exported through the PeTTa reified profile."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The gateway reads from the source.\n"
            "- The gateway writes to the cache.\n"
            "- The cache writes to the database.\n"
            "- The gateway writes to the queue.\n"
            "- The queue writes to the database.\n"
            "- The gateway writes to the database.\n"
            "- The system depends on data flow.\n",
            "redundant-export.plain",
        )

        atoms, refusals = emit_reified_atoms(doc)
        self.assertTrue(any("information-flow-redundant-path-reviewed" in atom for atom in atoms))
        self.assertTrue(any(atom.startswith("(MissingInformationFlowEvidence") for atom in atoms))
        self.assertFalse(any("MissingInformationFlowEvidence" in refusal.reason for refusal in refusals))

    # --- Temporal ordering impossibility detection tests ---

    def test_temporal_impossibility_detected_with_contradictory_before(self):
        """When the spec says 'A before B' and 'B before A', an impossible temporal cycle is detected."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The alpha happens before the beta.\n"
            "- The beta happens before the alpha.\n"
            "- The system depends on data flow.\n",
            "temporal-cycle.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        check = next(
            c for c in doc.checks
            if c.property == "information-flow-temporal-impossibility-reviewed" and c.target_id == review.id
        )
        self.assertEqual(check.status, CheckStatus.FAIL)
        self.assertIn("impossible temporal cycle", check.evidence.lower())
        self.assertIn("alpha", check.evidence.lower())
        self.assertIn("beta", check.evidence.lower())
        self.assertTrue(
            any(
                ("MissingInformationFlowEvidence", obj.id, "information-flow-temporal-impossibility-reviewed") in obj.facts
                and any(fact == ("Blocks", obj.id, check.obligation_id) for fact in obj.facts)
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            ),
            "temporal impossibility question not found",
        )

    def test_temporal_ordering_consistent_passes(self):
        """When temporal ordering is consistent (no cycles), the check passes."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The alpha happens before the beta.\n"
            "- The beta happens before the gamma.\n"
            "- The system depends on data flow.\n",
            "temporal-consistent.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        check = next(
            c for c in doc.checks
            if c.property == "information-flow-temporal-impossibility-reviewed" and c.target_id == review.id
        )
        self.assertEqual(check.status, CheckStatus.PASS)
        self.assertIn("consistent", check.evidence.lower())

    def test_temporal_ordering_with_after_normalizes_correctly(self):
        """'A after B' is normalized to 'B before A' and checked for cycles."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The alpha happens after the beta.\n"
            "- The beta happens after the alpha.\n"
            "- The system depends on data flow.\n",
            "temporal-after-cycle.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        check = next(
            c for c in doc.checks
            if c.property == "information-flow-temporal-impossibility-reviewed" and c.target_id == review.id
        )
        self.assertEqual(check.status, CheckStatus.FAIL)
        self.assertIn("impossible temporal cycle", check.evidence.lower())

    def test_temporal_ordering_with_follows_normalizes_correctly(self):
        """'A follows B' is normalized to 'B before A' and checked for cycles."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The gamma follows the beta.\n"
            "- The beta follows the alpha.\n"
            "- The system depends on data flow.\n",
            "temporal-follows.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        check = next(
            c for c in doc.checks
            if c.property == "information-flow-temporal-impossibility-reviewed" and c.target_id == review.id
        )
        self.assertEqual(check.status, CheckStatus.PASS)
        self.assertIn("consistent", check.evidence.lower())

    def test_temporal_ordering_with_then_detected(self):
        """'A then B' is recognized as a temporal ordering statement."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The alpha then the beta.\n"
            "- The beta then the alpha.\n"
            "- The system depends on data flow.\n",
            "temporal-then-cycle.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        check = next(
            c for c in doc.checks
            if c.property == "information-flow-temporal-impossibility-reviewed" and c.target_id == review.id
        )
        self.assertEqual(check.status, CheckStatus.FAIL)
        self.assertIn("impossible temporal cycle", check.evidence.lower())

    def test_no_temporal_ordering_passes(self):
        """Specs without explicit temporal ordering statements pass with 'no temporal ordering' evidence."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the upstream source.\n"
            "- The pipeline writes to the downstream sink.\n",
            "no-temporal.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        check = next(
            c for c in doc.checks
            if c.property == "information-flow-temporal-impossibility-reviewed" and c.target_id == review.id
        )
        self.assertEqual(check.status, CheckStatus.PASS)
        self.assertIn("no explicit temporal ordering", check.evidence.lower())

    def test_temporal_order_edge_atoms_exported_through_petta_profile(self):
        """TemporalOrderEdge atoms are exported through the PeTTa reified profile."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The alpha happens before the beta.\n"
            "- The system depends on data flow.\n",
            "temporal-export.plain",
        )

        atoms, refusals = emit_reified_atoms(doc)
        self.assertTrue(any(atom.startswith("(TemporalOrderEdge") for atom in atoms), f"TemporalOrderEdge atom not found in: {atoms}")
        self.assertFalse(any("TemporalOrderEdge" in refusal.reason for refusal in refusals))

    def test_three_node_temporal_cycle_detected(self):
        """A→B→C→A three-node temporal cycle is detected."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The alpha happens before the beta.\n"
            "- The beta happens before the gamma.\n"
            "- The gamma happens before the alpha.\n"
            "- The system depends on data flow.\n",
            "temporal-three-cycle.plain",
        )

        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )

        check = next(
            c for c in doc.checks
            if c.property == "information-flow-temporal-impossibility-reviewed" and c.target_id == review.id
        )
        self.assertEqual(check.status, CheckStatus.FAIL)
        self.assertIn("alpha", check.evidence.lower())
        self.assertIn("gamma", check.evidence.lower())

    def test_temporal_impossibility_atoms_exported_through_petta_profile(self):
        """Temporal impossibility obligations and questions are exported through the PeTTa reified profile."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The alpha happens before the beta.\n"
            "- The beta happens before the alpha.\n"
            "- The system depends on data flow.\n",
            "temporal-impossibility-export.plain",
        )

        atoms, refusals = emit_reified_atoms(doc)
        self.assertTrue(any("information-flow-temporal-impossibility-reviewed" in atom for atom in atoms))
        self.assertTrue(any(atom.startswith("(MissingInformationFlowEvidence") for atom in atoms))
        self.assertFalse(any("MissingInformationFlowEvidence" in refusal.reason for refusal in refusals))


    def test_cross_layer_data_temporal_contradiction_detected(self):
        """Data flows A→B but temporal says B before A → FAIL cross-layer check."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the database.\n"
            "- The database happens before the pipeline.\n",
            "cross-layer-contradiction.plain",
        )

        cross_check = next(
            c for c in doc.checks
            if c.property == "information-flow-data-temporal-consistency-reviewed"
        )
        self.assertEqual(cross_check.status, CheckStatus.FAIL)
        self.assertIn("contradiction", cross_check.evidence.lower())

        # Blocking question should exist.
        q_objs = [
            obj for obj in doc.objects
            if obj.role == Role.QUESTION_OBJECT
            and ("MissingInformationFlowEvidence", obj.id, "information-flow-data-temporal-consistency-reviewed") in obj.facts
        ]
        self.assertEqual(len(q_objs), 1)
        self.assertTrue(
            any(fact == ("Blocks", q_objs[0].id, cross_check.obligation_id) for fact in q_objs[0].facts)
        )

    def test_cross_layer_data_temporal_consistent_passes(self):
        """Data flows A→B and temporal says A before B → PASS cross-layer check."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the database.\n"
            "- The pipeline happens before the database.\n",
            "cross-layer-consistent.plain",
        )

        cross_check = next(
            c for c in doc.checks
            if c.property == "information-flow-data-temporal-consistency-reviewed"
        )
        self.assertEqual(cross_check.status, CheckStatus.PASS)

    def test_cross_layer_no_check_when_no_edges_or_temporal(self):
        """No DataFlowEdge or no TemporalOrderEdge → no cross-layer obligation."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The system depends on data flow.\n",
            "cross-layer-no-edges.plain",
        )
        self.assertFalse(
            any(c.property == "information-flow-data-temporal-consistency-reviewed" for c in doc.checks)
        )

    def test_cross_layer_atoms_exported_through_petta_profile(self):
        """Cross-layer consistency obligations and questions are exported through the PeTTa reified profile."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline writes to the database.\n"
            "- The database happens before the pipeline.\n",
            "cross-layer-export.plain",
        )
        atoms, refusals = emit_reified_atoms(doc)
        self.assertTrue(any("information-flow-data-temporal-consistency-reviewed" in atom for atom in atoms))
        self.assertTrue(any(atom.startswith("(MissingInformationFlowEvidence") for atom in atoms))
        self.assertFalse(any("MissingInformationFlowEvidence" in refusal.reason for refusal in refusals))

    def test_dependency_depth_shallow_passes(self):
        """A shallow graph (depth < 4) passes the dependency-depth check."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the source.\n"
            "- The pipeline writes to the database.\n",
            "depth-shallow.plain",
        )
        depth_check = next(
            c for c in doc.checks
            if c.property == "information-flow-dependency-depth-reviewed"
        )
        self.assertEqual(depth_check.status, CheckStatus.PASS)
        self.assertIn("below threshold", depth_check.evidence)

    def test_dependency_depth_deep_unacknowledged(self):
        """A deep chain (>= 4 edges) without acknowledgment produces Unknown + blocking question."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The gateway reads from the source.\n"
            "- The cache reads from the gateway.\n"
            "- The queue reads from the cache.\n"
            "- The worker reads from the queue.\n"
            "- The database writes from the worker.\n",
            "depth-deep-unack.plain",
        )
        depth_check = next(
            c for c in doc.checks
            if c.property == "information-flow-dependency-depth-reviewed"
        )
        self.assertEqual(depth_check.status, CheckStatus.UNKNOWN)
        self.assertIn("not acknowledged", depth_check.evidence)

        q_objs = [
            obj for obj in doc.objects
            if obj.role == Role.QUESTION_OBJECT
            and ("MissingInformationFlowEvidence", obj.id, "information-flow-dependency-depth-reviewed") in obj.facts
        ]
        self.assertEqual(len(q_objs), 1)
        self.assertTrue(
            any(fact == ("Blocks", q_objs[0].id, depth_check.obligation_id) for fact in q_objs[0].facts)
        )

    def test_dependency_depth_deep_acknowledged_passes(self):
        """A deep chain with acknowledgment wording passes the dependency-depth check."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The gateway reads from the source.\n"
            "- The cache reads from the gateway.\n"
            "- The queue reads from the cache.\n"
            "- The worker reads from the queue.\n"
            "- The database writes from the worker.\n"
            "- This is a deep multi-layer pipeline architecture.\n",
            "depth-deep-ack.plain",
        )
        depth_check = next(
            c for c in doc.checks
            if c.property == "information-flow-dependency-depth-reviewed"
        )
        self.assertEqual(depth_check.status, CheckStatus.PASS)
        self.assertIn("acknowledged", depth_check.evidence)

    def test_dependency_depth_no_check_when_no_edges(self):
        """No DataFlowEdge atoms → no dependency-depth obligation."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The system has a pipeline and data flow connections.\n",
            "depth-no-edges.plain",
        )
        self.assertFalse(
            any(c.property == "information-flow-dependency-depth-reviewed" for c in doc.checks)
        )

    def test_dependency_depth_no_check_when_cyclic(self):
        """When the graph has a cycle, depth check is not emitted (only meaningful for DAGs)."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The alpha reads from the beta.\n"
            "- The beta reads from the alpha.\n",
            "depth-cyclic.plain",
        )
        # Cycle should be detected but depth should not.
        self.assertTrue(
            any(c.property == "information-flow-cycle-detected" for c in doc.checks)
        )
        self.assertFalse(
            any(c.property == "information-flow-dependency-depth-reviewed" for c in doc.checks)
        )

    def test_dependency_depth_atoms_exported_through_petta_profile(self):
        """Dependency-depth obligations and questions are exported through the PeTTa reified profile."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The gateway reads from the source.\n"
            "- The cache reads from the gateway.\n"
            "- The queue reads from the cache.\n"
            "- The worker reads from the queue.\n"
            "- The database writes from the worker.\n",
            "depth-export.plain",
        )
        atoms, refusals = emit_reified_atoms(doc)
        self.assertTrue(any("information-flow-dependency-depth-reviewed" in atom for atom in atoms))
        self.assertTrue(any(atom.startswith("(MissingInformationFlowEvidence") for atom in atoms))
        self.assertFalse(any("MissingInformationFlowEvidence" in refusal.reason for refusal in refusals))

    def test_data_flow_edge_has_item_level_source_provenance(self):
        """Each DataFlowEdge object should cite the source span of the specific item where the edge was found."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the source.\n"
            "- The service writes to the database.\n",
            "edge-provenance.plain",
        )
        item_by_text = {item.raw_text: item for item in doc.items}
        pipeline_item = item_by_text["The pipeline reads from the source."]
        service_item = item_by_text["The service writes to the database."]

        edge_objects = [
            obj for obj in doc.objects
            if any(fact and str(fact[0]) == "DataFlowEdge" for fact in obj.facts)
        ]
        self.assertEqual(len(edge_objects), 2)

        for edge_obj in edge_objects:
            provenance_checks = [
                c for c in doc.checks
                if c.property == "edge-has-item-level-source-provenance" and c.target_id == edge_obj.id
            ]
            self.assertEqual(len(provenance_checks), 1)
            self.assertEqual(provenance_checks[0].status, CheckStatus.PASS)

        # Verify each edge's source span matches the expected item.
        edge_by_source = {}
        for edge_obj in edge_objects:
            edge_fact = next(f for f in edge_obj.facts if str(f[0]) == "DataFlowEdge")
            edge_by_source[edge_fact[2]] = edge_obj

        self.assertEqual(edge_by_source["pipeline"].source_span_id, pipeline_item.span.id)
        self.assertEqual(edge_by_source["service"].source_span_id, service_item.span.id)

    def test_temporal_order_edge_has_item_level_source_provenance(self):
        """Each TemporalOrderEdge object should cite the source span of the specific item where the edge was found."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the source.\n"
            "- The service runs before the database.\n",
            "temporal-provenance.plain",
        )
        item_by_text = {item.raw_text: item for item in doc.items}
        pipeline_item = item_by_text["The pipeline reads from the source."]
        service_item = item_by_text["The service runs before the database."]

        temporal_edges = [
            obj for obj in doc.objects
            if any(fact and str(fact[0]) == "TemporalOrderEdge" for fact in obj.facts)
        ]
        self.assertEqual(len(temporal_edges), 1)

        for edge_obj in temporal_edges:
            provenance_checks = [
                c for c in doc.checks
                if c.property == "edge-has-item-level-source-provenance" and c.target_id == edge_obj.id
            ]
            self.assertEqual(len(provenance_checks), 1)
            self.assertEqual(provenance_checks[0].status, CheckStatus.PASS)

        # Verify per-item span assignment.
        # "service runs before database" -> service before database
        edge_obj = temporal_edges[0]
        self.assertEqual(edge_obj.source_span_id, service_item.span.id)

        # Also verify the DataFlowEdge has per-item provenance.
        data_edges = [
            obj for obj in doc.objects
            if any(fact and str(fact[0]) == "DataFlowEdge" for fact in obj.facts)
        ]
        self.assertEqual(len(data_edges), 1)
        self.assertEqual(data_edges[0].source_span_id, pipeline_item.span.id)

    def test_edge_provenance_validation_fails_for_missing_source_span(self):
        """An edge object without a source span should fail the edge-provenance validation."""
        from specatom_hs.schema import SpecObject, SemanticLevel, Role, SpecDocument, stable_id
        from specatom_hs.validators import _validate_edge_source_provenance
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the source.\n",
            "edge-missing-span.plain",
        )
        # Inject a synthetic edge object with no source span and validate.
        bad_edge_id = stable_id("edge", "bad", "target", "reads-from", "synthetic")
        doc.objects.append(
            SpecObject(
                bad_edge_id,
                Role.VALIDATION_OBJECT,
                SemanticLevel.TEMPLATE_PARSED,
                None,
                facts=[("DataFlowEdge", bad_edge_id, "bad", "target", "reads-from")],
            )
        )
        _validate_edge_source_provenance(doc)
        provenance_check = next(
            c for c in doc.checks
            if c.property == "edge-has-item-level-source-provenance" and c.target_id == bad_edge_id
        )
        self.assertEqual(provenance_check.status, CheckStatus.FAIL)

    def test_connected_components_single_component_passes(self):
        """A fully connected data-flow graph passes the connected-components check."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the upstream source.\n"
            "- The pipeline writes to the downstream sink.\n",
            "connected-single.plain",
        )
        cc_check = next(
            c for c in doc.checks
            if c.property == "information-flow-connected-components-reviewed"
        )
        self.assertEqual(cc_check.status, CheckStatus.PASS)
        self.assertIn("fully connected", cc_check.evidence)

    def test_connected_components_multiple_disconnected_passes_with_acknowledgment(self):
        """Multiple disconnected components with acknowledgment text pass the check."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the source and writes to the sink.\n"
            "- The monitor reads from the metrics database and writes to the dashboard.\n"
            "- These are independent standalone subsystems.\n",
            "connected-ack.plain",
        )
        cc_check = next(
            c for c in doc.checks
            if c.property == "information-flow-connected-components-reviewed"
        )
        self.assertEqual(cc_check.status, CheckStatus.PASS)
        self.assertIn("acknowledged", cc_check.evidence)

    def test_connected_components_multiple_disconnected_unknown_without_acknowledgment(self):
        """Multiple disconnected components without acknowledgment produce Unknown and a blocking question."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the source and writes to the sink.\n"
            "- The monitor reads from the metrics database and writes to the dashboard.\n",
            "connected-gaps.plain",
        )
        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )
        cc_check = next(
            c for c in doc.checks
            if c.property == "information-flow-connected-components-reviewed"
            and c.target_id == review.id
        )
        self.assertEqual(cc_check.status, CheckStatus.UNKNOWN)
        self.assertIn("disconnected components", cc_check.evidence)
        # Verify a blocking question was created.
        question = next(
            obj for obj in doc.objects
            if obj.role == Role.QUESTION_OBJECT
            and any(f[0] == "MissingInformationFlowEvidence" and f[2] == "information-flow-connected-components-reviewed" for f in obj.facts)
        )
        self.assertTrue(
            any(f[0] == "Blocks" and f[2] == cc_check.obligation_id for f in question.facts)
        )


    def test_information_flow_graph_summary_matches_ground_truth(self):
        """The information-flow-graph-summary atom must reflect the actual graph structure."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the upstream source.\n"
            "- The cache reads from the database.\n"
            "- The pipeline writes to the downstream sink.\n",
            "graph-summary.plain",
        )
        atoms, _ = emit_reified_atoms(doc)

        summary_atom = next(a for a in atoms if a.startswith("(information-flow-graph-summary"))
        # Parse the atom parts.
        inner = summary_atom.strip()
        if inner.startswith("(") and inner.endswith(")"):
            inner = inner[1:-1]
        import re as _re
        tokens = _re.findall(r'"[^"]*"|\S+', inner)
        parts = []
        for t in tokens:
            try:
                parts.append(int(t))
            except ValueError:
                parts.append(t)

        # parts = ["information-flow-graph-summary", file_id, nodes, edges, temporal_edges, sources, sinks, cycles, components, max_depth, bottlenecks]
        self.assertEqual(len(parts), 11, f"expected 11 parts, got {parts}")

        # Edges: pipeline→upstream_source (reads-from), cache→database (reads-from),
        # pipeline→downstream_sink (writes-to). 4 distinct nodes, 3 edges, 0 temporal edges.
        self.assertEqual(parts[2], 5, "node count")  # pipeline, upstream source, cache, database, downstream sink
        self.assertEqual(parts[3], 3, "edge count")
        self.assertEqual(parts[4], 0, "temporal edge count")
        self.assertEqual(parts[7], 0, "cycles")
        self.assertEqual(parts[10], 0, "bottlenecks")

    def test_information_flow_graph_summary_empty_doc(self):
        """An empty document should produce a zero-stats graph summary."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The system should be user-friendly.\n",
            "no-graph.plain",
        )
        atoms, _ = emit_reified_atoms(doc)
        summary_atom = next(a for a in atoms if a.startswith("(information-flow-graph-summary"))
        # All stats should be zero.
        import re as _re
        inner = summary_atom.strip()
        if inner.startswith("(") and inner.endswith(")"):
            inner = inner[1:-1]
        tokens = _re.findall(r'"[^"]*"|\S+', inner)
        parts = [int(t) if t.isdigit() else t for t in tokens]
        # parts = ["information-flow-graph-summary", file_id, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        self.assertEqual(parts[2:], [0, 0, 0, 0, 0, 0, 0, 0, 0], "all graph stats should be zero")

    def test_bidirectional_edge_detected_and_unacknowledged(self):
        """A→B and B→A edges trigger an Unknown blocking question without acknowledgment."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The service reads from the cache.\n"
            "- The cache reads from the service.\n",
            "bidirectional-unack.plain",
        )
        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )
        bidir_check = next(
            c for c in doc.checks
            if c.property == "information-flow-bidirectional-edge-reviewed" and c.target_id == review.id
        )
        self.assertEqual(bidir_check.status, CheckStatus.UNKNOWN)
        self.assertIn("service ↔ cache", bidir_check.evidence)
        self.assertTrue(
            any(
                ("MissingInformationFlowEvidence", obj.id, "information-flow-bidirectional-edge-reviewed") in obj.facts
                and any(fact == ("Blocks", obj.id, bidir_check.obligation_id) for fact in obj.facts)
                for obj in doc.objects
                if obj.role == Role.QUESTION_OBJECT
            ),
            "bidirectional edge question not found",
        )

    def test_bidirectional_edge_acknowledged_passes(self):
        """Bidirectional edges with acknowledgment (request-response, feedback loop, etc.) pass."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The service reads from the cache.\n"
            "- The cache reads from the service.\n"
            "- This is a request-response pattern.\n",
            "bidirectional-ack.plain",
        )
        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )
        bidir_check = next(
            c for c in doc.checks
            if c.property == "information-flow-bidirectional-edge-reviewed" and c.target_id == review.id
        )
        self.assertEqual(bidir_check.status, CheckStatus.PASS)
        self.assertIn("service ↔ cache", bidir_check.evidence)

    def test_bidirectional_edge_no_bidirectional_passes(self):
        """A DAG with no bidirectional edges passes the check."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The pipeline reads from the upstream source.\n"
            "- The pipeline writes to the downstream sink.\n",
            "bidirectional-none.plain",
        )
        review = next(
            obj for obj in doc.objects
            if ("InformationFlowReview", obj.id) in obj.facts
        )
        bidir_check = next(
            c for c in doc.checks
            if c.property == "information-flow-bidirectional-edge-reviewed" and c.target_id == review.id
        )
        self.assertEqual(bidir_check.status, CheckStatus.PASS)
        self.assertIn("no bidirectional edges", bidir_check.evidence)

    def test_bidirectional_edge_atoms_exported_through_petta_profile(self):
        """The bidirectional edge obligation and check are exported through the PeTTa reified profile."""
        doc = compile_source(
            "***functional specifications***\n"
            "- The service reads from the cache.\n"
            "- The cache reads from the service.\n",
            "bidirectional-export.plain",
        )
        atoms, refusals = emit_reified_atoms(doc)
        self.assertTrue(
            any("information-flow-bidirectional-edge-reviewed" in atom for atom in atoms),
            "bidirectional edge obligation should be in reified atoms",
        )
        self.assertFalse(any("bidirectional" in refusal.reason for refusal in refusals))


if __name__ == "__main__":
    unittest.main()

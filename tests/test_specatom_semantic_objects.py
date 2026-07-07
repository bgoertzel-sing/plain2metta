import unittest

from specatom_hs.backends.petta import emit_reified_atoms
from specatom_hs.passes import compile_source
from specatom_hs.schema import CheckStatus, Role, SemanticLevel


class SemanticObjectTests(unittest.TestCase):
    def test_proposition_extraction_with_typed_predicate_and_concept_link(self):
        doc = compile_source(
            "***definitions***\n"
            "- :Task: is tracked work.\n"
            "***requirements***\n"
            "- [id:R1] The :Task: is a workflow item.\n"
            "***acceptance tests***\n"
            "- [covers:R1] A task can be shown.\n",
            "proposition.plain",
        )

        prop = next(obj for obj in doc.objects if obj.role == Role.PROPOSITION_OBJECT)
        self.assertEqual(prop.semantic_level, SemanticLevel.PREDICATE_PARSED)
        self.assertIn(("PropositionPredicate", prop.id, "is-a"), prop.facts)
        self.assertIn(("PropositionSubject", prop.id, "Task"), prop.facts)
        self.assertTrue(any(fact[0] == "GeneratedFrom" and fact[2].startswith("req-") for fact in prop.facts))
        self.assertTrue(any(fact[0] == "RefersToConcept" for fact in prop.facts))
        self.assertTrue(any(c.property == "proposition-has-typed-predicate" and c.target_id == prop.id and c.status == CheckStatus.PASS for c in doc.checks))
        self.assertTrue(any(c.property == "provisional-semantic-link-reviewed" and c.target_id == prop.id and c.status == CheckStatus.PASS for c in doc.checks))

    def test_action_template_extraction(self):
        doc = compile_source(
            "***definitions***\n"
            "- :System: is the service boundary.\n"
            "***requirements***\n"
            "- [id:R2] The :System: shall store audit events.\n"
            "***acceptance tests***\n"
            "- [covers:R2] Audit events are stored.\n",
            "action.plain",
        )

        action = next(obj for obj in doc.objects if obj.role == Role.ACTION_TEMPLATE)
        self.assertEqual(action.semantic_level, SemanticLevel.ACTION_SCHEMA_PARSED)
        self.assertIn(("ActionSubject", action.id, "System"), action.facts)
        self.assertIn(("ActionVerb", action.id, "store"), action.facts)
        self.assertIn(("ActionObject", action.id, "audit events"), action.facts)
        self.assertTrue(any(c.property == "action-template-has-verb" and c.target_id == action.id and c.status == CheckStatus.PASS for c in doc.checks))

    def test_marker_raw_proposition_gets_unknown_predicate_obligation(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R3] Proposition: reliability maybe.\n"
            "***acceptance tests***\n"
            "- [covers:R3] Review exists.\n",
            "raw-proposition.plain",
        )

        prop = next(obj for obj in doc.objects if obj.role == Role.PROPOSITION_OBJECT)
        self.assertEqual(prop.semantic_level, SemanticLevel.TEMPLATE_PARSED)
        self.assertFalse(any(fact[0] == "PropositionPredicate" for fact in prop.facts))
        self.assertTrue(any(c.property == "proposition-has-typed-predicate" and c.target_id == prop.id and c.status == CheckStatus.UNKNOWN for c in doc.checks))

    def test_unresolved_concept_reference_gets_review_unknown(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R6] The :MissingThing: is a workflow item.\n"
            "***acceptance tests***\n"
            "- [covers:R6] Review exists.\n",
            "unresolved-semantic-link.plain",
        )

        prop = next(obj for obj in doc.objects if obj.role == Role.PROPOSITION_OBJECT)
        self.assertTrue(any(fact == ("UnresolvedSemanticConcept", prop.id, "missingthing") for fact in prop.facts))
        self.assertTrue(any(c.property == "provisional-semantic-link-reviewed" and c.target_id == prop.id and c.status == CheckStatus.UNKNOWN for c in doc.checks))

    def test_marker_raw_action_gets_unknown_verb_obligation(self):
        doc = compile_source(
            "***requirements***\n"
            "- [id:R5] Action: TBD after architecture review.\n"
            "***acceptance tests***\n"
            "- [covers:R5] Review exists.\n",
            "raw-action.plain",
        )

        action = next(obj for obj in doc.objects if obj.role == Role.ACTION_TEMPLATE)
        self.assertEqual(action.semantic_level, SemanticLevel.TEMPLATE_PARSED)
        self.assertFalse(any(fact[0] == "ActionVerb" for fact in action.facts))
        self.assertTrue(any(c.property == "action-template-has-verb" and c.target_id == action.id and c.status == CheckStatus.UNKNOWN for c in doc.checks))

    def test_petta_exports_phase2_semantic_facts(self):
        doc = compile_source(
            "***definitions***\n"
            "- :Component: is a deployable unit.\n"
            "***requirements***\n"
            "- [id:R6] The :Component: must validate input. The :Component: has property isolated.\n"
            "***acceptance tests***\n"
            "- [covers:R6] Invalid input is rejected.\n",
            "petta-semantic.plain",
        )
        atoms, refusals = emit_reified_atoms(doc)
        joined = "\n".join(atoms)
        self.assertIn("(Proposition ", joined)
        self.assertIn("(PropositionPredicate ", joined)
        self.assertIn("(ActionTemplate ", joined)
        self.assertIn("(ActionVerb ", joined)
        self.assertFalse(any("Proposition" in r.reason or "Action" in r.reason for r in refusals))


if __name__ == "__main__":
    unittest.main()

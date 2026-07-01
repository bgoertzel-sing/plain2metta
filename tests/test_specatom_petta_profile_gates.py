import unittest

from specatom_hs.backends.petta import emit_reified_atoms, refuse_executable_skeleton
from specatom_hs.passes import compile_source
from specatom_hs.schema import CheckStatus, Role, SemanticLevel, SpecDocument, SpecObject
from specatom_hs.validators import add_check, add_validation_obligation


def obj(level):
    return SpecObject("obj-1", Role.REQUIREMENT_OBJECT, level, "span-1")


class PettaProfileGateTests(unittest.TestCase):
    def test_refuses_executable_skeleton_from_raw_text_only(self):
        refusals = refuse_executable_skeleton([obj(SemanticLevel.RAW_TEXT_ONLY)])
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0].reason, "raw-text-only-skeleton-forbidden")

    def test_refuses_executable_skeleton_from_unsupported_semantic_levels(self):
        refusals = refuse_executable_skeleton([obj(SemanticLevel.TEMPLATE_PARSED)])
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0].reason, "unsupported-semantic-level-for-executable-skeleton")

    def test_basic_reified_atom_emission_stub_when_safe(self):
        doc = SpecDocument(objects=[obj(SemanticLevel.TEMPLATE_PARSED)])
        atoms, refusals = emit_reified_atoms(doc)
        self.assertFalse(refusals)
        self.assertIn("(target-profile petta_reified_v0)", atoms)
        self.assertIn("(spec-object obj-1 RequirementObject TemplateParsed)", atoms)

    def test_reified_atom_refuses_raw_text_only(self):
        doc = SpecDocument(objects=[obj(SemanticLevel.RAW_TEXT_ONLY)])
        atoms, refusals = emit_reified_atoms(doc)
        self.assertEqual(atoms, ["(target-profile petta_reified_v0)"])
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0].reason, "unsupported-semantic-level-for-reified-emission")

    def test_reified_profile_filters_unknown_and_malformed_object_facts(self):
        good = SpecObject("obj-good", Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, "span-1", facts=[("Requirement", "obj-good")])
        unknown = SpecObject("obj-unknown", Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, "span-1", facts=[("InventedExecutable", "obj-unknown", "run")])
        malformed = SpecObject("obj-bad", Role.VALIDATION_OBJECT, SemanticLevel.TEMPLATE_PARSED, "span-1", facts=[("Covers", "obj-bad")])
        atoms, refusals = emit_reified_atoms(SpecDocument(objects=[good, unknown, malformed]))
        self.assertIn("(Requirement obj-good)", atoms)
        self.assertNotIn("(InventedExecutable obj-unknown run)", atoms)
        self.assertNotIn("(Covers obj-bad)", atoms)
        self.assertTrue(any(r.reason == "unsupported-fact-predicate:InventedExecutable" for r in refusals))
        self.assertTrue(any(r.reason == "unsupported-fact-arity:Covers:expected-3:got-2" for r in refusals))

    def test_reified_validation_records_preserve_rationale_and_check_evidence(self):
        doc = compile_source("***definitions***\n- :Task: is work.\n", "validation.plain")
        obligation = add_validation_obligation(doc, "manual-question", doc.items[0].id, "Need Ben to confirm the intended scope.", doc.items[0].span.id)
        check = add_check(doc, obligation, CheckStatus.UNKNOWN, "not enough source evidence")
        atoms, refusals = emit_reified_atoms(doc)
        self.assertTrue(any(atom == f'(validation-rationale {obligation.id} "Need Ben to confirm the intended scope.")' for atom in atoms))
        self.assertTrue(any(atom == f'(check-obligation {check.id} {obligation.id})' for atom in atoms))
        self.assertTrue(any(atom == f'(check-evidence {check.id} "not enough source evidence")' for atom in atoms))


if __name__ == "__main__":
    unittest.main()

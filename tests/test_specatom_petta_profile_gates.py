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

    def test_reified_profile_filters_unknown_malformed_and_wrong_subject_facts(self):
        good = SpecObject("obj-good", Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, "span-1", facts=[("Requirement", "obj-good")])
        unknown = SpecObject("obj-unknown", Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, "span-1", facts=[("InventedExecutable", "obj-unknown", "run")])
        malformed = SpecObject("obj-bad", Role.VALIDATION_OBJECT, SemanticLevel.TEMPLATE_PARSED, "span-1", facts=[("Covers", "obj-bad")])
        wrong_subject = SpecObject("obj-owner", Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, "span-1", facts=[("RequirementText", "obj-other", "text")])
        atoms, refusals = emit_reified_atoms(SpecDocument(objects=[good, unknown, malformed, wrong_subject]))
        self.assertIn("(Requirement obj-good)", atoms)
        self.assertNotIn("(InventedExecutable obj-unknown run)", atoms)
        self.assertNotIn("(Covers obj-bad)", atoms)
        self.assertNotIn("(RequirementText obj-other text)", atoms)
        self.assertTrue(any(r.reason == "unsupported-fact-predicate:InventedExecutable" for r in refusals))
        self.assertTrue(any(r.reason == "unsupported-fact-arity:Covers:expected-3:got-2" for r in refusals))
        self.assertTrue(any(r.reason == "fact-subject-mismatch:RequirementText:expected-obj-owner:got-obj-other" for r in refusals))

    def test_reified_validation_records_preserve_rationale_and_check_evidence(self):
        doc = compile_source("***definitions***\n- :Task: is work.\n", "validation.plain")
        obligation = add_validation_obligation(doc, "manual-question", doc.items[0].id, "Need Ben to confirm the intended scope.", doc.items[0].span.id)
        check = add_check(doc, obligation, CheckStatus.UNKNOWN, "not enough source evidence")
        atoms, refusals = emit_reified_atoms(doc)
        self.assertTrue(any(atom == f'(validation-rationale {obligation.id} "Need Ben to confirm the intended scope.")' for atom in atoms))
        self.assertTrue(any(atom == f'(check-obligation {check.id} {obligation.id})' for atom in atoms))
        self.assertTrue(any(atom == f'(check-evidence {check.id} "not enough source evidence")' for atom in atoms))

    def test_reified_projection_includes_source_provenance_manifest(self):
        doc = compile_source("***definitions***\n- Task: tracked work.\n", "source_manifest.plain")
        atoms, refusals = emit_reified_atoms(doc)

        plain_file = doc.files[0]
        section = doc.sections[0]
        item = doc.items[0]
        span = item.span
        expected_manifest_atoms = {
            f"(plain-file {plain_file.id} source_manifest.plain {plain_file.digest})",
            f"(section {section.id} {plain_file.id} Definitions 1)",
            f"(derived-from {section.id} {section.span.id})",
            f'(plain-item {item.id} {section.id} none 1 "Task: tracked work.")',
            f"(derived-from {item.id} {span.id})",
            f"(source-span {span.id} {plain_file.id} {span.start_byte} {span.end_byte} {span.start_line} {span.end_line})",
        }
        self.assertTrue(expected_manifest_atoms.issubset(set(atoms)))
        self.assertFalse(any(r.reason.startswith("unsupported-fact") for r in refusals))


if __name__ == "__main__":
    unittest.main()

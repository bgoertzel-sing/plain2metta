"""End-to-end ground-truth tests for the auth_service.plain fixture.

These tests run the full compiler pipeline (source indexing → concept table →
requirement/test coverage → security/privacy → information-flow → validation →
PeTTa reified export) on ``auth_service.plain`` and compare generated atoms
against expected ground-truth structure.
"""

import unittest
from pathlib import Path

from specatom_hs.backends.petta import emit_reified_atoms, emit_reified_atoms_grouped
from specatom_hs.passes import compile_path
from specatom_hs.schema import CheckStatus, Role, SemanticLevel

AUTH_EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "auth_service.plain"


class AuthSvcGroundTruthTests(unittest.TestCase):
    """Ground-truth structural expectations for the auth_service fixture."""

    @classmethod
    def setUpClass(cls):
        cls.doc = compile_path(AUTH_EXAMPLE)
        cls.atoms, cls.refusals = emit_reified_atoms(cls.doc)

    # --- Source provenance ground truth ---

    def test_source_files_indexed(self):
        """The auth_service Plain file must be indexed with a digest."""
        self.assertEqual(len(self.doc.files), 1)
        f = self.doc.files[0]
        self.assertIn("auth_service.plain", f.path)
        self.assertTrue(f.digest)
        self.assertIn(f"(plain-file {f.id}", "".join(self.atoms))

    def test_sections_covers_definitions_functional_and_acceptance(self):
        """Sections must include definitions, functional specifications, acceptance tests."""
        section_kinds = [s.kind.lower() for s in self.doc.sections]
        self.assertIn("definitions", section_kinds)
        self.assertIn("functionalspecifications", section_kinds)
        self.assertIn("acceptancetests", section_kinds)

    # --- Concept ground truth ---

    def test_concepts_defined(self):
        """User, Session, AuthToken must be defined concepts."""
        concept_names = set()
        for obj in self.doc.objects:
            if obj.role == Role.CONCEPT_OBJECT:
                for fact in obj.facts:
                    if fact[0] == "ConceptName":
                        concept_names.add(fact[2])
        self.assertIn("User", concept_names)
        self.assertIn("Session", concept_names)
        self.assertIn("AuthToken", concept_names)

    def test_external_concept_recognized(self):
        """argon2id must be recognized as an external concept."""
        concept_names = set()
        for obj in self.doc.objects:
            if obj.role == Role.CONCEPT_OBJECT:
                for fact in obj.facts:
                    if fact[0] == "ConceptName":
                        concept_names.add(fact[2])
        ext_found = any(name == "argon2id" for name in concept_names)
        self.assertTrue(ext_found, "argon2id should be recognized as a concept")

    def test_unresolved_concept_creates_question(self):
        """AuditSink is only referenced (never defined), so it must become an unresolved question."""
        unresolved = set()
        for obj in self.doc.objects:
            if obj.role == Role.QUESTION_OBJECT:
                for fact in obj.facts:
                    if fact[0] == "UnresolvedConcept":
                        unresolved.add(fact[2])
        self.assertIn("AuditSink", unresolved)

    # --- Requirement/coverage ground truth ---

    def test_requirement_labels_emitted(self):
        """AUTH-1, AUTH-2, AUTH-3, AUTH-4 labels must be emitted."""
        labels = set()
        for obj in self.doc.objects:
            for fact in obj.facts:
                if fact[0] == "RequirementLabel":
                    labels.add(fact[2])
        self.assertIn("AUTH-1", labels)
        self.assertIn("AUTH-2", labels)
        self.assertIn("AUTH-3", labels)
        self.assertIn("AUTH-4", labels)

    def test_duplicate_requirement_label_detected(self):
        """AUTH-2 appears twice and must trigger a DuplicateRequirementLabel."""
        dup_found = any(
            fact[0] == "DuplicateRequirementLabel"
            for obj in self.doc.objects
            for fact in obj.facts
        )
        self.assertTrue(dup_found, "Duplicate AUTH-2 label should be detected")

    def test_coverage_claims_emitted(self):
        """Coverage claims for AUTH-1 and AUTH-2 must be emitted."""
        coverage_targets = set()
        for obj in self.doc.objects:
            for fact in obj.facts:
                if fact[0] == "CoverageClaim":
                    coverage_targets.add(fact[2])
        self.assertIn("AUTH-1", coverage_targets)
        self.assertIn("AUTH-2", coverage_targets)

    def test_orphan_acceptance_test_emitted(self):
        """AUTH-99 coverage claim must become a MissingCoverageTarget and OrphanAcceptanceTest."""
        missing_targets = set()
        for obj in self.doc.objects:
            for fact in obj.facts:
                if fact[0] == "MissingCoverageTarget":
                    missing_targets.add(fact[2])
        self.assertIn("AUTH-99", missing_targets)

    def test_orphan_acceptance_test_without_covers_label(self):
        """The acceptance test without a [covers:...] label must become an OrphanAcceptanceTest."""
        orphan_found = any(
            fact[0] == "OrphanAcceptanceTest"
            for obj in self.doc.objects
            for fact in obj.facts
        )
        self.assertTrue(orphan_found, "Orphan acceptance test should be detected")

    # --- Validation summary ground truth ---

    def test_document_validation_summary_emitted(self):
        """The PeTTa reified export must include a document-validation-summary atom."""
        summary_atoms = [a for a in self.atoms if a.startswith("(document-validation-summary")]
        self.assertEqual(len(summary_atoms), 1, "exactly one document-validation-summary atom expected")

    def _parse_summary_atom(self, atom_str: str) -> list:
        """Parse a MeTTa S-expression atom into its parts."""
        import re
        inner = atom_str.strip()
        if inner.startswith("(") and inner.endswith(")"):
            inner = inner[1:-1]
        # Use shlex-like splitting: split on whitespace but respect quoted strings
        parts = []
        for token in re.findall(r'"[^"]*"|\S+', inner):
            if token.startswith('"') and token.endswith('"'):
                parts.append(token[1:-1])
            else:
                try:
                    parts.append(int(token))
                except ValueError:
                    parts.append(token)
        return parts

    def test_document_validation_summary_counts_match_diagnostics(self):
        """Summary counts must match the actual check/question counts."""
        pass_count = sum(1 for c in self.doc.checks if hasattr(c.status, "value") and c.status.value == "Pass")
        fail_count = sum(1 for c in self.doc.checks if hasattr(c.status, "value") and c.status.value == "Fail")
        unknown_count = sum(1 for c in self.doc.checks if hasattr(c.status, "value") and c.status.value == "Unknown")
        question_count = sum(1 for obj in self.doc.objects if obj.role == Role.QUESTION_OBJECT)

        summary_atom = next(a for a in self.atoms if a.startswith("(document-validation-summary"))
        parts = self._parse_summary_atom(summary_atom)
        # parts = ["document-validation-summary", file_id, pass, fail, unknown, questions]
        self.assertEqual(len(parts), 6, f"expected 6 parts, got {parts}")
        self.assertEqual(parts[2], pass_count)
        self.assertEqual(parts[3], fail_count)
        self.assertEqual(parts[4], unknown_count)
        self.assertEqual(parts[5], question_count)

    def test_summary_has_nonzero_unknowns_and_questions(self):
        """The auth_service fixture should surface Unknown checks and QuestionObjects."""
        summary_atom = next(a for a in self.atoms if a.startswith("(document-validation-summary"))
        parts = self._parse_summary_atom(summary_atom)
        self.assertGreater(parts[4], 0, "should have Unknown checks")
        self.assertGreater(parts[5], 0, "should have QuestionObjects")

    # --- PeTTa reified export ground truth ---

    def test_reified_atoms_include_all_categories(self):
        """Reified atoms must include source, object, and validation categories."""
        atom_text = "\n".join(self.atoms)
        self.assertIn("(target-profile", atom_text)
        self.assertIn("(plain-file", atom_text)
        self.assertIn("(source-span", atom_text)
        self.assertIn("(section", atom_text)
        self.assertIn("(spec-object", atom_text)
        self.assertIn("(validation-obligation", atom_text)
        self.assertIn("(check", atom_text)

    def test_grouped_export_has_separators(self):
        """Grouped .metta output must have section comment separators."""
        grouped, _ = emit_reified_atoms_grouped(self.doc)
        self.assertIn(";;; Source Files", grouped)
        self.assertIn(";;; Objects", grouped)
        self.assertIn(";;; Validation", grouped)

    def test_refusals_present_for_unsupported_levels(self):
        """RawTextOnly objects must produce backend refusals, not reified atoms."""
        # The acceptance-test bullet without [covers:...] is likely RawTextOnly
        # and should produce a refusal or at minimum should not appear as
        # (spec-object ... RawTextOnly) in reified atoms
        raw_text_objects = [
            obj for obj in self.doc.objects
            if obj.semantic_level == SemanticLevel.RAW_TEXT_ONLY
        ]
        if raw_text_objects:
            refused_ids = {r.object_id for r in self.refusals}
            for obj in raw_text_objects:
                self.assertIn(obj.id, refused_ids, f"RawTextOnly object {obj.id} should be refused")

    def test_all_check_statuses_are_declared(self):
        """No check should have an undeclared status (all should be Pass/Fail/Unknown)."""
        for check in self.doc.checks:
            self.assertIsInstance(check.status, CheckStatus,
                f"Check {check.id} has non-enum status: {check.status}")

    def test_all_objects_have_known_semantic_levels(self):
        """Every object must have a declared SemanticLevel."""
        known_levels = {level for level in SemanticLevel}
        for obj in self.doc.objects:
            self.assertIn(obj.semantic_level, known_levels,
                f"Object {obj.id} has unknown semantic level: {obj.semantic_level}")


if __name__ == "__main__":
    unittest.main()

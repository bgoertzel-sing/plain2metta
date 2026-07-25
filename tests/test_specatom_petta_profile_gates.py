import unittest

from specatom_hs.backends.petta import emit_reified_atoms, refuse_executable_skeleton
from specatom_hs.passes import compile_source
from specatom_hs.schema import (
    CheckRecord,
    CheckStatus,
    PlainFile,
    PlainItem,
    Role,
    Section,
    SemanticLevel,
    SourceSpan,
    SpecDocument,
    SpecObject,
    ValidationObligation,
)
from specatom_hs.validators import add_check, add_validation_obligation


def obj(level):
    return SpecObject("obj-1", Role.REQUIREMENT_OBJECT, level, "span-1")


def document_with_checks(
    checks,
    obligation_id="obligation",
    obligation_property="property",
    obligation_target="target",
):
    return SpecDocument(
        validation_obligations=[
            ValidationObligation(
                obligation_id,
                obligation_property,
                obligation_target,
                "Ground-truth obligation for backend check tests.",
            )
        ],
        checks=checks,
    )


class PettaProfileGateTests(unittest.TestCase):
    def test_reified_profile_refuses_malformed_object_facts_containers(self):
        malformed = SpecObject("object-malformed", Role.CONCEPT_OBJECT, SemanticLevel.TEMPLATE_PARSED)
        malformed.facts = None
        valid = SpecObject("object-valid", Role.CONCEPT_OBJECT, SemanticLevel.TEMPLATE_PARSED)

        atoms, refusals = emit_reified_atoms(SpecDocument(objects=[malformed, valid]))

        self.assertNotIn("(spec-object object-malformed ConceptObject TemplateParsed)", atoms)
        self.assertIn("(spec-object object-valid ConceptObject TemplateParsed)", atoms)
        self.assertTrue(any(refusal.reason == "unsupported-object-facts-container-type:NoneType" and refusal.object_id == "object-malformed" for refusal in refusals))

    def test_refuses_malformed_spec_object_record_types_without_crashing(self):
        valid = SpecObject("valid-object", Role.CONCEPT_OBJECT, SemanticLevel.TEMPLATE_PARSED)
        atoms, refusals = emit_reified_atoms(SpecDocument(objects=[None, ["bad"], valid]))

        self.assertIn("(spec-object valid-object ConceptObject TemplateParsed)", atoms)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                (None, "unsupported-spec-object-record-type:NoneType"),
                (None, "unsupported-spec-object-record-type:list"),
            ],
        )

    def test_refuses_plain_items_with_dangling_or_inconsistent_parents(self):
        plain_file = PlainFile("file", "valid.plain", "digest", "text")
        span = SourceSpan("span", plain_file.id, 0, 4, 1, 1)
        other_span = SourceSpan("other-span", plain_file.id, 0, 4, 1, 1)
        section = Section("section", plain_file.id, "Main", "requirements", 0, span)
        other_section = Section(
            "other-section", plain_file.id, "Other", "requirements", 1, other_span
        )
        items = [
            PlainItem("missing-parent", plain_file.id, section.id, "absent", 0, 1, "missing", span),
            PlainItem("cross-section", plain_file.id, section.id, "other-parent", 1, 1, "cross", span),
            PlainItem("self-parent", plain_file.id, section.id, "self-parent", 2, 1, "self", span),
            PlainItem("refused-parent", plain_file.id, section.id, "missing-parent", 3, 2, "cascade", span),
            PlainItem("valid-child", plain_file.id, section.id, "valid-parent", 4, 1, "child", span),
            PlainItem("valid-parent", plain_file.id, section.id, None, 5, 0, "parent", span),
            PlainItem("other-parent", plain_file.id, other_section.id, None, 6, 0, "other", other_span),
        ]

        atoms, refusals = emit_reified_atoms(
            SpecDocument(
                files=[plain_file],
                spans=[span, other_span],
                sections=[section, other_section],
                items=items,
            )
        )

        self.assertEqual(
            [atom for atom in atoms if atom.startswith("(plain-item")],
            [
                "(plain-item valid-child section valid-parent 4 child)",
                "(plain-item valid-parent section none 5 parent)",
                "(plain-item other-parent other-section none 6 other)",
            ],
        )
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                ("missing-parent", "plain-item-parent-not-emitted"),
                ("cross-section", "plain-item-parent-section-mismatch"),
                ("self-parent", "plain-item-self-parent"),
                ("refused-parent", "plain-item-parent-not-emitted"),
            ],
        )

    def test_refuses_dangling_object_and_obligation_provenance_links(self):
        valid_file = PlainFile("file-valid", "valid.plain", "digest-valid", "text")
        refused_file = PlainFile("file-refused", " ", "digest-refused", "text")
        valid_span = SourceSpan("span-valid", valid_file.id, 0, 4, 1, 1)
        refused_span = SourceSpan("span-refused", refused_file.id, 0, 4, 1, 1)
        objects = [
            SpecObject("object-no-span", Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED),
            SpecObject("object-missing-span", Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, "span-missing"),
            SpecObject("object-refused-span", Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, refused_span.id),
            SpecObject("object-valid", Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, valid_span.id),
        ]
        obligations = [
            ValidationObligation("obligation-no-span", "property", "target", "rationale"),
            ValidationObligation("obligation-missing-span", "property", "target", "rationale", "span-missing"),
            ValidationObligation("obligation-refused-span", "property", "target", "rationale", refused_span.id),
            ValidationObligation("obligation-valid", "property", "target", "rationale", valid_span.id),
        ]

        atoms, refusals = emit_reified_atoms(
            SpecDocument(
                files=[refused_file, valid_file],
                spans=[refused_span, valid_span],
                objects=objects,
                validation_obligations=obligations,
            )
        )

        self.assertEqual(
            [atom for atom in atoms if atom.startswith("(derived-from object")],
            ["(derived-from object-valid span-valid)"],
        )
        self.assertEqual(
            [atom for atom in atoms if atom.startswith("(derived-from obligation")],
            ["(derived-from obligation-valid span-valid)"],
        )
        self.assertNotIn(
            "(validation-obligation obligation-missing-span property target)",
            atoms,
        )
        self.assertNotIn(
            "(validation-obligation obligation-refused-span property target)",
            atoms,
        )
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                ("file-refused", "invalid-plain-file-path"),
                ("span-refused", "source-span-file-not-emitted"),
                ("object-missing-span", "object-source-span-not-emitted"),
                ("object-refused-span", "object-source-span-not-emitted"),
                (
                    "obligation-missing-span",
                    "validation-obligation-source-span-not-emitted",
                ),
                (
                    "obligation-refused-span",
                    "validation-obligation-source-span-not-emitted",
                ),
            ],
        )

    def test_refuses_plain_items_with_unemitted_or_inconsistent_provenance(self):
        valid_file = PlainFile("file-valid", "valid.plain", "digest-valid", "text")
        other_file = PlainFile("file-other", "other.plain", "digest-other", "text")
        malformed_file = PlainFile("file-refused", " ", "digest-refused", "text")
        valid_span = SourceSpan("span-valid", valid_file.id, 0, 4, 1, 1)
        other_span = SourceSpan("span-other", other_file.id, 0, 4, 1, 1)
        refused_span = SourceSpan("span-refused", malformed_file.id, 0, 4, 1, 1)
        valid_section = Section(
            "section-valid", valid_file.id, "Valid", "definitions", 0, valid_span
        )
        other_section = Section(
            "section-other", other_file.id, "Other", "definitions", 0, other_span
        )
        refused_section = Section(
            "section-refused", malformed_file.id, "Refused", "definitions", 0, refused_span
        )
        items = [
            PlainItem("item-missing-file", "file-missing", valid_section.id, None, 0, 0, "missing file", valid_span),
            PlainItem("item-refused-file", malformed_file.id, refused_section.id, None, 1, 0, "refused file", refused_span),
            PlainItem("item-missing-section", valid_file.id, "section-missing", None, 2, 0, "missing section", valid_span),
            PlainItem("item-refused-section", valid_file.id, refused_section.id, None, 3, 0, "refused section", valid_span),
            PlainItem(
                "item-missing-span",
                valid_file.id,
                valid_section.id,
                None,
                4,
                0,
                "missing span",
                SourceSpan("span-missing", valid_file.id, 0, 4, 1, 1),
            ),
            PlainItem("item-section-mismatch", valid_file.id, other_section.id, None, 5, 0, "section mismatch", valid_span),
            PlainItem("item-span-mismatch", valid_file.id, valid_section.id, None, 6, 0, "span mismatch", other_span),
            PlainItem("item-valid", valid_file.id, valid_section.id, None, 7, 0, "valid", valid_span),
        ]

        atoms, refusals = emit_reified_atoms(
            SpecDocument(
                files=[malformed_file, valid_file, other_file],
                spans=[refused_span, valid_span, other_span],
                sections=[refused_section, valid_section, other_section],
                items=items,
            )
        )

        self.assertEqual(
            [atom for atom in atoms if atom.startswith("(plain-item")],
            ["(plain-item item-valid section-valid none 7 valid)"],
        )
        self.assertEqual(
            [atom for atom in atoms if atom.startswith("(derived-from item")],
            ["(derived-from item-valid span-valid)"],
        )
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                ("file-refused", "invalid-plain-file-path"),
                ("span-refused", "source-span-file-not-emitted"),
                ("section-refused", "section-file-not-emitted"),
                ("item-missing-file", "plain-item-file-not-emitted"),
                ("item-refused-file", "plain-item-file-not-emitted"),
                ("item-missing-section", "plain-item-section-not-emitted"),
                ("item-refused-section", "plain-item-section-not-emitted"),
                ("item-missing-span", "plain-item-span-not-emitted"),
                ("item-section-mismatch", "plain-item-section-file-mismatch"),
                ("item-span-mismatch", "plain-item-span-file-mismatch"),
            ],
        )

    def test_refuses_sections_with_unemitted_or_inconsistent_provenance(self):
        valid_file = PlainFile("file-valid", "valid.plain", "digest-valid", "text")
        other_file = PlainFile("file-other", "other.plain", "digest-other", "text")
        malformed_file = PlainFile("file-refused", " ", "digest-refused", "text")
        valid_span = SourceSpan("span-valid", valid_file.id, 0, 4, 1, 1)
        other_span = SourceSpan("span-other", other_file.id, 0, 4, 1, 1)
        refused_span = SourceSpan("span-refused", malformed_file.id, 0, 4, 1, 1)
        sections = [
            Section("section-missing-file", "file-missing", "Missing", "definitions", 0, valid_span),
            Section("section-refused-file", malformed_file.id, "Refused", "definitions", 1, refused_span),
            Section(
                "section-missing-span",
                valid_file.id,
                "Missing span",
                "definitions",
                2,
                SourceSpan("span-missing", valid_file.id, 0, 4, 1, 1),
            ),
            Section("section-mismatched-span", valid_file.id, "Mismatch", "definitions", 3, other_span),
            Section("section-valid", valid_file.id, "Valid", "definitions", 4, valid_span),
        ]

        atoms, refusals = emit_reified_atoms(
            SpecDocument(
                files=[malformed_file, valid_file, other_file],
                spans=[refused_span, valid_span, other_span],
                sections=sections,
            )
        )

        self.assertEqual(
            [atom for atom in atoms if atom.startswith("(section")],
            ["(section section-valid file-valid definitions 4)"],
        )
        self.assertEqual(
            [atom for atom in atoms if atom.startswith("(derived-from section")],
            ["(derived-from section-valid span-valid)"],
        )
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                ("file-refused", "invalid-plain-file-path"),
                ("span-refused", "source-span-file-not-emitted"),
                ("section-missing-file", "section-file-not-emitted"),
                ("section-refused-file", "section-file-not-emitted"),
                ("section-missing-span", "section-span-not-emitted"),
                ("section-mismatched-span", "section-span-file-mismatch"),
            ],
        )

    def test_refuses_section_when_embedded_span_masks_manifest_file_mismatch(self):
        valid_file = PlainFile("file-valid", "valid.plain", "digest-valid", "text")
        other_file = PlainFile("file-other", "other.plain", "digest-other", "text")
        manifest_span = SourceSpan("span-shared", other_file.id, 0, 4, 1, 1)
        masked_span = SourceSpan("span-shared", valid_file.id, 0, 4, 1, 1)
        section = Section(
            "section-masked-mismatch",
            valid_file.id,
            "Masked mismatch",
            "definitions",
            0,
            masked_span,
        )

        atoms, refusals = emit_reified_atoms(
            SpecDocument(
                files=[valid_file, other_file],
                spans=[manifest_span],
                sections=[section],
            )
        )

        self.assertNotIn(
            "(section section-masked-mismatch file-valid definitions 0)", atoms
        )
        self.assertNotIn(
            "(derived-from section-masked-mismatch span-shared)", atoms
        )
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [("section-masked-mismatch", "section-span-file-mismatch")],
        )

    def test_refuses_source_spans_linked_to_unemitted_files(self):
        valid_file = PlainFile("file-valid", "valid.plain", "digest-valid", "text")
        malformed_file = PlainFile("file-malformed", " ", "digest-malformed", "text")
        valid_span = SourceSpan("span-valid", valid_file.id, 0, 4, 1, 1)
        dangling_spans = [
            SourceSpan("span-missing-file", "file-missing", 0, 4, 1, 1),
            SourceSpan("span-refused-file", malformed_file.id, 0, 4, 1, 1),
        ]

        atoms, refusals = emit_reified_atoms(
            SpecDocument(
                files=[malformed_file, valid_file],
                spans=[*dangling_spans, valid_span],
            )
        )

        self.assertEqual(
            [atom for atom in atoms if atom.startswith("(plain-file")],
            ["(plain-file file-valid valid.plain digest-valid)"],
        )
        self.assertEqual(
            [atom for atom in atoms if atom.startswith("(source-span")],
            ["(source-span span-valid file-valid 0 4 1 1)"],
        )
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                ("file-malformed", "invalid-plain-file-path"),
                ("span-missing-file", "source-span-file-not-emitted"),
                ("span-refused-file", "source-span-file-not-emitted"),
            ],
        )

    def test_refuses_duplicate_source_manifest_ids_and_preserves_valid_neighbors(self):
        valid_file = PlainFile("file-valid", "valid.plain", "digest-valid", "text")
        duplicate_files = [
            PlainFile("file-duplicate", "first.plain", "digest-first", "first"),
            PlainFile("file-duplicate", "second.plain", "digest-second", "second"),
        ]
        valid_span = SourceSpan("span-valid", valid_file.id, 0, 4, 1, 1)
        duplicate_spans = [
            SourceSpan("span-duplicate", valid_file.id, 0, 2, 1, 1),
            SourceSpan("span-duplicate", valid_file.id, 2, 4, 1, 1),
        ]
        valid_section = Section(
            "section-valid", valid_file.id, "Valid", "definitions", 0, valid_span
        )
        duplicate_sections = [
            Section(
                "section-duplicate", valid_file.id, "First", "definitions", 0, valid_span
            ),
            Section(
                "section-duplicate", valid_file.id, "Second", "requirements", 1, valid_span
            ),
        ]
        valid_item = PlainItem(
            "item-valid", valid_file.id, valid_section.id, None, 0, 0, "valid", valid_span
        )
        duplicate_items = [
            PlainItem(
                "item-duplicate", valid_file.id, valid_section.id, None, 0, 0, "first", valid_span
            ),
            PlainItem(
                "item-duplicate", valid_file.id, valid_section.id, None, 1, 0, "second", valid_span
            ),
        ]

        atoms, refusals = emit_reified_atoms(
            SpecDocument(
                files=[*duplicate_files, valid_file],
                spans=[*duplicate_spans, valid_span],
                sections=[*duplicate_sections, valid_section],
                items=[*duplicate_items, valid_item],
            )
        )

        self.assertEqual(
            [atom for atom in atoms if atom.startswith("(plain-file")],
            ["(plain-file file-valid valid.plain digest-valid)"],
        )
        self.assertEqual(
            [atom for atom in atoms if atom.startswith("(source-span")],
            ["(source-span span-valid file-valid 0 4 1 1)"],
        )
        self.assertEqual(
            [atom for atom in atoms if atom.startswith("(section")],
            ["(section section-valid file-valid definitions 0)"],
        )
        self.assertEqual(
            [atom for atom in atoms if atom.startswith("(plain-item")],
            ["(plain-item item-valid section-valid none 0 valid)"],
        )
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                ("file-duplicate", "duplicate-plain-file-id"),
                ("file-duplicate", "duplicate-plain-file-id"),
                ("span-duplicate", "duplicate-source-span-id"),
                ("span-duplicate", "duplicate-source-span-id"),
                ("section-duplicate", "duplicate-section-id"),
                ("section-duplicate", "duplicate-section-id"),
                ("item-duplicate", "duplicate-plain-item-id"),
                ("item-duplicate", "duplicate-plain-item-id"),
            ],
        )

    def test_refuses_malformed_plain_file_fields_and_preserves_valid_neighbor(self):
        valid = PlainFile("file-valid", "valid.plain", "digest-valid", "text")
        malformed = [
            PlainFile(7, "numeric-id.plain", "digest", "text"),
            PlainFile("file-path", " ", "digest", "text"),
            PlainFile("file-digest", "digest.plain", None, "text"),
        ]

        atoms, refusals = emit_reified_atoms(
            SpecDocument(files=[*malformed, valid])
        )

        self.assertEqual(
            [atom for atom in atoms if atom.startswith("(plain-file")],
            ["(plain-file file-valid valid.plain digest-valid)"],
        )
        self.assertIn(
            "(document-validation-summary file-valid 0 0 0 0)", atoms
        )
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                ("7", "invalid-plain-file-id"),
                ("file-path", "invalid-plain-file-path"),
                ("file-digest", "invalid-plain-file-digest"),
            ],
        )

    def test_refuses_malformed_source_manifest_record_types_without_crashing(self):
        plain_file = PlainFile("file-valid", "valid.plain", "digest", "text")
        span = SourceSpan("span-valid", plain_file.id, 0, 4, 1, 1)
        section = Section(
            "section-valid", plain_file.id, "Title", "definitions", 0, span
        )
        item = PlainItem(
            "item-valid", plain_file.id, section.id, None, 0, 0, "text", span
        )
        doc = SpecDocument(
            files=[7, plain_file],
            spans=[{"id": "not-a-span"}, span],
            sections=[None, section],
            items=[["not-an-item"], item],
        )

        atoms, refusals = emit_reified_atoms(doc)
        rendered = "\n".join(atoms)

        self.assertIn("(plain-file file-valid valid.plain digest)", atoms)
        self.assertIn("(source-span span-valid file-valid 0 4 1 1)", atoms)
        self.assertIn("(section section-valid file-valid definitions 0)", atoms)
        self.assertIn("(plain-item item-valid section-valid none 0 text)", atoms)
        self.assertIn("(document-validation-summary file-valid 0 0 0 0)", atoms)
        self.assertNotIn("not-a-span", rendered)
        self.assertNotIn("not-an-item", rendered)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                (None, "unsupported-plain-file-record-type:int"),
                (None, "unsupported-source-span-record-type:dict"),
                (None, "unsupported-section-record-type:NoneType"),
                (None, "unsupported-plain-item-record-type:list"),
            ],
        )

    def test_refuses_malformed_source_span_fields_and_preserves_valid_neighbor(self):
        valid = SourceSpan("span-valid", "file-valid", 0, 4, 1, 1)
        malformed = [
            SourceSpan(7, "file-valid", 0, 4, 1, 1),
            SourceSpan("span-file", " ", 0, 4, 1, 1),
            SourceSpan("span-byte-type", "file-valid", False, 4, 1, 1),
            SourceSpan("span-byte-order", "file-valid", 5, 4, 1, 1),
            SourceSpan("span-line-type", "file-valid", 0, 4, 1.0, 1),
            SourceSpan("span-line-order", "file-valid", 0, 4, 2, 1),
        ]

        atoms, refusals = emit_reified_atoms(
            SpecDocument(
                files=[PlainFile("file-valid", "valid.plain", "digest-valid", "text")],
                spans=[*malformed, valid],
            )
        )

        self.assertEqual(
            [atom for atom in atoms if atom.startswith("(source-span")],
            ["(source-span span-valid file-valid 0 4 1 1)"],
        )
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                ("7", "invalid-source-span-id"),
                ("span-file", "invalid-source-span-file-id"),
                ("span-byte-type", "invalid-source-span-byte-bound-type"),
                ("span-byte-order", "invalid-source-span-byte-bounds"),
                ("span-line-type", "invalid-source-span-line-bound-type"),
                ("span-line-order", "invalid-source-span-line-bounds"),
            ],
        )

    def test_refuses_malformed_section_and_item_fields_with_valid_neighbors(self):
        span = SourceSpan("span-valid", "file-valid", 0, 4, 1, 1)
        valid_section = Section(
            "section-valid", "file-valid", "Title", "definitions", 0, span
        )
        malformed_sections = [
            Section(7, "file-valid", "Title", "definitions", 0, span),
            Section("section-file", " ", "Title", "definitions", 0, span),
            Section("section-kind", "file-valid", "Title", None, 0, span),
            Section("section-ordinal-type", "file-valid", "Title", "definitions", False, span),
            Section("section-ordinal", "file-valid", "Title", "definitions", -1, span),
            Section("section-span-record", "file-valid", "Title", "definitions", 0, None),
            Section(
                "section-span-id",
                "file-valid",
                "Title",
                "definitions",
                0,
                SourceSpan(" ", "file-valid", 0, 4, 1, 1),
            ),
        ]
        valid_item = PlainItem(
            "item-valid", "file-valid", valid_section.id, None, 0, 0, "text", span
        )
        malformed_items = [
            PlainItem(7, "file-valid", valid_section.id, None, 0, 0, "text", span),
            PlainItem("item-section", "file-valid", " ", None, 0, 0, "text", span),
            PlainItem("item-parent", "file-valid", valid_section.id, 7, 0, 0, "text", span),
            PlainItem("item-ordinal-type", "file-valid", valid_section.id, None, True, 0, "text", span),
            PlainItem("item-ordinal", "file-valid", valid_section.id, None, -1, 0, "text", span),
            PlainItem("item-level-type", "file-valid", valid_section.id, None, 0, True, "text", span),
            PlainItem("item-level", "file-valid", valid_section.id, None, 0, -1, "text", span),
            PlainItem("item-text", "file-valid", valid_section.id, None, 0, 0, " ", span),
            PlainItem("item-span-record", "file-valid", valid_section.id, None, 0, 0, "text", None),
            PlainItem(
                "item-span-id",
                "file-valid",
                valid_section.id,
                None,
                0,
                0,
                "text",
                SourceSpan(" ", "file-valid", 0, 4, 1, 1),
            ),
        ]

        atoms, refusals = emit_reified_atoms(
            SpecDocument(
                files=[PlainFile("file-valid", "valid.plain", "digest-valid", "text")],
                spans=[span],
                sections=[*malformed_sections, valid_section],
                items=[*malformed_items, valid_item],
            )
        )

        self.assertEqual(
            [atom for atom in atoms if atom.startswith("(section")],
            ["(section section-valid file-valid definitions 0)"],
        )
        self.assertEqual(
            [atom for atom in atoms if atom.startswith("(plain-item")],
            ["(plain-item item-valid section-valid none 0 text)"],
        )
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                ("7", "invalid-section-id"),
                ("section-file", "invalid-section-file-id"),
                ("section-kind", "invalid-section-kind"),
                ("section-ordinal-type", "invalid-section-ordinal-type"),
                ("section-ordinal", "invalid-section-ordinal"),
                ("section-span-record", "invalid-section-span-record"),
                ("section-span-id", "invalid-section-span-id"),
                ("7", "invalid-plain-item-id"),
                ("item-section", "invalid-plain-item-section-id"),
                ("item-parent", "invalid-plain-item-parent-id"),
                ("item-ordinal-type", "invalid-plain-item-ordinal-type"),
                ("item-ordinal", "invalid-plain-item-ordinal"),
                ("item-level-type", "invalid-plain-item-level-type"),
                ("item-level", "invalid-plain-item-level"),
                ("item-text", "invalid-plain-item-raw-text"),
                ("item-span-record", "invalid-plain-item-span-record"),
                ("item-span-id", "invalid-plain-item-span-id"),
            ],
        )

    def test_refuses_malformed_validation_record_types_without_crashing(self):
        valid_check = CheckRecord(
            "valid-check",
            "valid-obligation",
            "manual-review",
            "target",
            CheckStatus.PASS,
            "Reviewed against ground truth.",
        )
        doc = SpecDocument(
            validation_obligations=[
                7,
                ValidationObligation(
                    "valid-obligation",
                    "manual-review",
                    "target",
                    "Review the target.",
                ),
            ],
            checks=[{"id": "not-a-check"}, valid_check],
        )

        atoms, refusals = emit_reified_atoms(doc)
        rendered = "\n".join(atoms)

        self.assertIn(
            "(validation-obligation valid-obligation manual-review target)",
            atoms,
        )
        self.assertIn(
            "(check valid-check manual-review target Pass)",
            atoms,
        )
        self.assertIn(
            "(document-validation-summary document 1 0 0 0)",
            atoms,
        )
        self.assertNotIn("not-a-check", rendered)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                (None, "unsupported-validation-obligation-record-type:int"),
                (None, "unsupported-check-record-type:dict"),
            ],
        )

    def test_quotes_ascii_control_characters_in_fact_text(self):
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            "span-1",
            facts=[("RequirementText", "requirement", "alpha\x00beta\x07gamma")],
        )

        atoms, refusals = emit_reified_atoms(SpecDocument(objects=[requirement]))

        self.assertIn(
            '(RequirementText requirement "alpha\\u0000beta\\u0007gamma")',
            atoms,
        )
        self.assertFalse(any("RequirementText" in refusal.reason for refusal in refusals))
        self.assertFalse(any("\x00" in atom or "\x07" in atom for atom in atoms))

    def test_quotes_semicolons_in_source_and_fact_text(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Requirement: preserve alpha; do not treat beta as a comment.\n",
            "semicolon.plain",
        )

        atoms, refusals = emit_reified_atoms(doc)
        rendered = "\n".join(atoms)

        self.assertIn(
            '"Requirement: preserve alpha; do not treat beta as a comment."',
            rendered,
        )
        self.assertNotIn(
            "Requirement: preserve alpha; do not treat beta as a comment.)",
            rendered,
        )
        self.assertFalse(
            any("RequirementText" in refusal.reason for refusal in refusals)
        )

    def test_refuses_executable_skeleton_from_raw_text_only(self):
        refusals = refuse_executable_skeleton([obj(SemanticLevel.RAW_TEXT_ONLY)])
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0].reason, "raw-text-only-skeleton-forbidden")

    def test_semantic_level_refusal_precedes_missing_provenance(self):
        objects = [
            SpecObject("raw", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, ""),
            SpecObject("parsed", Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, ""),
        ]
        refusals = refuse_executable_skeleton(objects)
        self.assertEqual(
            [(r.object_id, r.reason, r.semantic_level) for r in refusals],
            [
                ("raw", "raw-text-only-skeleton-forbidden", "RawTextOnly"),
                ("parsed", "unsupported-semantic-level-for-executable-skeleton", "TemplateParsed"),
            ],
        )

    def test_refuses_executable_skeleton_from_unsupported_semantic_levels(self):
        refusals = refuse_executable_skeleton([obj(SemanticLevel.TEMPLATE_PARSED)])
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0].reason, "unsupported-semantic-level-for-executable-skeleton")

    def test_refuses_executable_skeleton_without_object_id(self):
        unidentified = SpecObject(
            "",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("Requirement", "")],
        )
        refusals = refuse_executable_skeleton([unidentified])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [("", "missing-object-id-for-executable-skeleton")],
        )

    def test_refuses_executable_skeleton_with_empty_object_reference(self):
        unidentified = SpecObject(
            "",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("Requirement", "")],
        )
        coverage = SpecObject(
            "coverage",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-2",
            facts=[("Covers", "coverage", "")],
        )
        refusals = refuse_executable_skeleton([unidentified, coverage])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [
                ("", "missing-object-id-for-executable-skeleton"),
                ("coverage", "unsafe-profile-fact:empty-object-reference:Covers"),
            ],
        )

    def test_refuses_transitive_reference_to_empty_object_identity(self):
        unidentified = SpecObject(
            "",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("Requirement", "")],
        )
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-2",
            facts=[("GeneratedFrom", "requirement", "")],
        )
        coverage = SpecObject(
            "coverage",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-3",
            facts=[("Covers", "coverage", "requirement")],
        )
        refusals = refuse_executable_skeleton([unidentified, requirement, coverage])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [
                ("", "missing-object-id-for-executable-skeleton"),
                ("requirement", "unsafe-profile-fact:empty-object-reference:GeneratedFrom"),
                (
                    "coverage",
                    "unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:"
                    "Covers:requirement->:MissingObjectId",
                ),
            ],
        )

    def test_refuses_whitespace_only_object_identity_across_reference_depths(self):
        unidentified = SpecObject(
            "   ",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("Requirement", "   ")],
        )
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-2",
            facts=[("GeneratedFrom", "requirement", "   ")],
        )
        coverage = SpecObject(
            "coverage",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-3",
            facts=[("Covers", "coverage", "requirement")],
        )

        refusals = refuse_executable_skeleton([unidentified, requirement, coverage])

        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [
                ("   ", "missing-object-id-for-executable-skeleton"),
                ("requirement", "unsafe-profile-fact:empty-object-reference:GeneratedFrom"),
                (
                    "coverage",
                    "unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:"
                    "Covers:requirement->   :MissingObjectId",
                ),
            ],
        )

    def test_refuses_executable_skeleton_when_lowered_object_has_unsafe_facts(self):
        objects = [
            SpecObject("unknown", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-1", facts=[("InventedExecutable", "unknown", "run")]),
            SpecObject("malformed", Role.VALIDATION_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-1", facts=[("Covers", "malformed")]),
            SpecObject("wrong-owner", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-1", facts=[("RequirementText", "other", "text")]),
        ]
        refusals = refuse_executable_skeleton(objects)
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [
                ("unknown", "unsafe-profile-fact:unsupported-fact-predicate:InventedExecutable"),
                ("malformed", "unsafe-profile-fact:unsupported-fact-arity:Covers:expected-3:got-2"),
                ("wrong-owner", "unsafe-profile-fact:fact-subject-mismatch:RequirementText:expected-wrong-owner:got-other"),
            ],
        )

    def test_refuses_blank_scalar_fact_argument_for_reified_and_executable_profiles(self):
        obj = SpecObject(
            "obj-blank-value",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-blank-value",
            facts=[("RequirementLabel", "obj-blank-value", " \t ")],
        )

        atoms, reified_refusals = emit_reified_atoms(SpecDocument(objects=[obj]))
        executable_refusals = refuse_executable_skeleton([obj])

        self.assertNotIn("(RequirementLabel ", "\n".join(atoms))
        self.assertTrue(any(r.reason == "empty-fact-argument:RequirementLabel:position-2" for r in reified_refusals))
        self.assertTrue(any(r.reason == "unsafe-profile-fact:empty-fact-argument:RequirementLabel:position-2" for r in executable_refusals))

    def test_refuses_none_scalar_fact_argument_for_reified_and_executable_profiles(self):
        missing_value = SpecObject(
            "obj-none-value",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("RequirementLabel", "obj-none-value", None)],
        )

        atoms, reified_refusals = emit_reified_atoms(SpecDocument(objects=[missing_value]))
        executable_refusals = refuse_executable_skeleton([missing_value])

        self.assertNotIn("(RequirementLabel ", "\n".join(atoms))
        self.assertTrue(any(r.reason == "empty-fact-argument:RequirementLabel:position-2" for r in reified_refusals))
        self.assertTrue(any(r.reason == "unsafe-profile-fact:empty-fact-argument:RequirementLabel:position-2" for r in executable_refusals))

    def test_refuses_non_finite_scalar_fact_arguments_for_reified_and_executable_profiles(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                candidate = SpecObject(
                    "obj-non-finite-value",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-non-finite-value",
                    facts=[("RequirementLabel", "obj-non-finite-value", value)],
                )

                atoms, reified_refusals = emit_reified_atoms(SpecDocument(objects=[candidate]))
                executable_refusals = refuse_executable_skeleton([candidate])

                self.assertNotIn("(RequirementLabel ", "\n".join(atoms))
                self.assertTrue(any(r.reason == "non-finite-fact-argument:RequirementLabel:position-2" for r in reified_refusals))
                self.assertTrue(any(r.reason == "unsafe-profile-fact:non-finite-fact-argument:RequirementLabel:position-2" for r in executable_refusals))

    def test_refuses_non_string_fact_subject_despite_apparent_matching_id(self):
        for object_id, subject in (("1", 1), ("1.5", 1.5), ("True", True)):
            with self.subTest(object_id=object_id, subject=subject):
                candidate = SpecObject(
                    object_id,
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-subject",
                    facts=[("RequirementLabel", subject, "label")],
                )

                atoms, reified_refusals = emit_reified_atoms(
                    SpecDocument(objects=[candidate])
                )
                executable_refusals = refuse_executable_skeleton([candidate])
                reason = (
                    "unsupported-fact-subject-type:RequirementLabel:position-1:"
                    f"{type(subject).__name__}"
                )

                self.assertFalse(
                    any(atom.startswith("(RequirementLabel ") for atom in atoms)
                )
                self.assertTrue(any(r.reason == reason for r in reified_refusals))
                self.assertTrue(
                    any(
                        r.reason == f"unsafe-profile-fact:{reason}"
                        for r in executable_refusals
                    )
                )

    def test_refuses_non_string_object_ids_without_aliasing_or_crashing(self):
        for object_id in (1, 1.5, True):
            with self.subTest(object_id=object_id):
                candidate = SpecObject(
                    object_id,
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-object-id",
                    facts=[("Requirement", object_id)],
                )

                atoms, reified_refusals = emit_reified_atoms(
                    SpecDocument(objects=[candidate])
                )
                executable_refusals = refuse_executable_skeleton([candidate])
                type_name = type(object_id).__name__

                self.assertFalse(any(atom.startswith("(spec-object ") for atom in atoms))
                self.assertFalse(any(atom.startswith("(Requirement ") for atom in atoms))
                self.assertTrue(
                    any(
                        refusal.reason
                        == f"unsupported-object-id-type-for-reified-emission:{type_name}"
                        for refusal in reified_refusals
                    )
                )
                self.assertEqual(
                    [refusal.reason for refusal in executable_refusals],
                    [
                        "unsupported-object-id-type-for-executable-skeleton:"
                        f"{type_name}"
                    ],
                )

    def test_refuses_non_enum_object_roles_without_emitting_facts(self):
        for role in ("RequirementObject", None, 7):
            with self.subTest(role=role):
                candidate = SpecObject(
                    "obj-invalid-role",
                    role,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-invalid-role",
                    facts=[("Requirement", "obj-invalid-role")],
                )

                atoms, reified_refusals = emit_reified_atoms(
                    SpecDocument(objects=[candidate])
                )
                executable_refusals = refuse_executable_skeleton([candidate])
                type_name = type(role).__name__

                self.assertFalse(any(atom.startswith("(spec-object ") for atom in atoms))
                self.assertFalse(any(atom.startswith("(Requirement ") for atom in atoms))
                self.assertEqual(
                    [refusal.reason for refusal in reified_refusals],
                    [
                        "unsupported-object-role-type-for-reified-emission:"
                        f"{type_name}"
                    ],
                )
                self.assertEqual(
                    [refusal.reason for refusal in executable_refusals],
                    [
                        "unsupported-object-role-type-for-executable-skeleton:"
                        f"{type_name}"
                    ],
                )

    def test_refuses_non_enum_semantic_levels_without_emitting_facts(self):
        for level in ("BackendLowered", None, 7):
            with self.subTest(level=level):
                candidate = SpecObject(
                    "obj-invalid-level",
                    Role.REQUIREMENT_OBJECT,
                    level,
                    "span-invalid-level",
                    facts=[("Requirement", "obj-invalid-level")],
                )

                atoms, reified_refusals = emit_reified_atoms(
                    SpecDocument(objects=[candidate])
                )
                executable_refusals = refuse_executable_skeleton([candidate])
                type_name = type(level).__name__

                self.assertFalse(any(atom.startswith("(spec-object ") for atom in atoms))
                self.assertFalse(any(atom.startswith("(Requirement ") for atom in atoms))
                self.assertEqual(
                    [refusal.reason for refusal in reified_refusals],
                    [
                        "unsupported-semantic-level-type-for-reified-emission:"
                        f"{type_name}"
                    ],
                )
                self.assertEqual(
                    [refusal.reason for refusal in executable_refusals],
                    [
                        "unsupported-semantic-level-type-for-executable-skeleton:"
                        f"{type_name}"
                    ],
                )

    def test_refuses_structured_fact_arguments_for_reified_and_executable_profiles(self):
        for value in (["nested"], {"nested": "value"}):
            with self.subTest(value=value):
                unsafe = SpecObject(
                    "obj-structured-value",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-structured-value",
                    facts=[("RequirementLabel", "obj-structured-value", value)],
                )
                atoms, reified_refusals = emit_reified_atoms(SpecDocument(objects=[unsafe]))
                executable_refusals = refuse_executable_skeleton([unsafe])
                reason = f"unsupported-fact-argument-type:RequirementLabel:position-2:{type(value).__name__}"
                self.assertNotIn(f"(RequirementLabel obj-structured-value {value})", atoms)
                self.assertTrue(any(r.reason == reason for r in reified_refusals))
                self.assertTrue(any(r.reason == f"unsafe-profile-fact:{reason}" for r in executable_refusals))

    def test_refuses_malformed_fact_records_without_crashing(self):
        for fact in (["Requirement", "obj-malformed-fact"], "Requirement", {0: "Requirement"}, None):
            with self.subTest(fact=fact):
                unsafe = SpecObject(
                    "obj-malformed-fact",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-malformed-fact",
                    facts=[fact],
                )

                atoms, reified_refusals = emit_reified_atoms(
                    SpecDocument(objects=[unsafe])
                )
                executable_refusals = refuse_executable_skeleton([unsafe])
                reason = f"unsupported-fact-record-type:{type(fact).__name__}"

                self.assertFalse(
                    any(atom.startswith("(Requirement ") for atom in atoms)
                )
                self.assertEqual(
                    [refusal.reason for refusal in reified_refusals], [reason]
                )
                self.assertEqual(
                    [refusal.reason for refusal in executable_refusals],
                    [f"unsafe-profile-fact:{reason}"],
                )

    def test_refuses_non_string_fact_predicates_without_aliasing(self):
        class RequirementAlias:
            def __str__(self):
                return "Requirement"

        for predicate in (1, None, RequirementAlias()):
            with self.subTest(predicate=predicate):
                unsafe = SpecObject(
                    "obj-non-string-predicate",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-non-string-predicate",
                    facts=[(predicate, "obj-non-string-predicate")],
                )

                atoms, reified_refusals = emit_reified_atoms(
                    SpecDocument(objects=[unsafe])
                )
                executable_refusals = refuse_executable_skeleton([unsafe])
                reason = (
                    "unsupported-fact-predicate-type:"
                    f"{type(predicate).__name__}"
                )

                self.assertFalse(any(atom.startswith("(Requirement ") for atom in atoms))
                self.assertEqual(
                    [refusal.reason for refusal in reified_refusals], [reason]
                )
                self.assertEqual(
                    [refusal.reason for refusal in executable_refusals],
                    [f"unsafe-profile-fact:{reason}"],
                )

    def test_refuses_structured_object_references_before_id_resolution(self):
        for value in (["requirement-1"], {"id": "requirement-1"}):
            with self.subTest(value=value):
                coverage = SpecObject(
                    "coverage-structured-reference",
                    Role.VALIDATION_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-structured-reference",
                    facts=[("Covers", "coverage-structured-reference", value)],
                )
                requirement = SpecObject(
                    "requirement-1",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-requirement-1",
                    facts=[("Requirement", "requirement-1")],
                )

                atoms, reified_refusals = emit_reified_atoms(
                    SpecDocument(objects=[coverage, requirement])
                )
                executable_refusals = refuse_executable_skeleton(
                    [coverage, requirement]
                )
                reason = (
                    "unsupported-fact-argument-type:Covers:position-2:"
                    f"{type(value).__name__}"
                )

                self.assertFalse(any(atom.startswith("(Covers ") for atom in atoms))
                self.assertTrue(any(r.reason == reason for r in reified_refusals))
                self.assertTrue(
                    any(
                        r.reason == f"unsafe-profile-fact:{reason}"
                        for r in executable_refusals
                    )
                )

    def test_refuses_empty_object_ids_without_emitting_reified_facts(self):
        for object_id in ("", " \t "):
            with self.subTest(object_id=object_id):
                candidate = SpecObject(
                    object_id,
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    "span-object-id",
                    facts=[("RequirementText", object_id, "must stay suppressed")],
                )

                atoms, refusals = emit_reified_atoms(
                    SpecDocument(objects=[candidate])
                )

                self.assertFalse(any(atom.startswith("(spec-object ") for atom in atoms))
                self.assertFalse(any(atom.startswith("(RequirementText ") for atom in atoms))
                self.assertFalse(any(atom.startswith("(derived-from ") for atom in atoms))
                self.assertEqual(
                    [(r.object_id, r.reason) for r in refusals],
                    [(object_id, "missing-object-id-for-reified-emission")],
                )

    def test_refuses_none_object_reference_for_reified_and_executable_profiles(self):
        requirement = SpecObject(
            "requirement-1",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("GeneratedFrom", "requirement-1", None)],
        )
        atoms, reified_refusals = emit_reified_atoms(SpecDocument(objects=[requirement]))
        executable_refusals = refuse_executable_skeleton([requirement])

        self.assertFalse(any("GeneratedFrom" in atom for atom in atoms))
        self.assertTrue(any(r.reason == "empty-object-reference:GeneratedFrom:position-2" for r in reified_refusals))
        self.assertTrue(any(r.reason == "unsafe-profile-fact:empty-object-reference:GeneratedFrom" for r in executable_refusals))

    def test_refuses_non_string_object_references_before_id_resolution(self):
        for value in (1, 1.5, True):
            with self.subTest(value=value):
                coverage = SpecObject(
                    "coverage-non-string-reference",
                    Role.VALIDATION_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-non-string-reference",
                    facts=[("Covers", "coverage-non-string-reference", value)],
                )
                apparent_target = SpecObject(
                    str(value),
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-apparent-target",
                    facts=[("Requirement", str(value))],
                )

                atoms, reified_refusals = emit_reified_atoms(
                    SpecDocument(objects=[coverage, apparent_target])
                )
                executable_refusals = refuse_executable_skeleton(
                    [coverage, apparent_target]
                )
                reason = (
                    "unsupported-object-reference-type:Covers:position-2:"
                    f"{type(value).__name__}"
                )

                self.assertFalse(any(atom.startswith("(Covers ") for atom in atoms))
                self.assertTrue(any(r.reason == reason for r in reified_refusals))
                self.assertTrue(
                    any(
                        r.reason == f"unsafe-profile-fact:{reason}"
                        for r in executable_refusals
                    )
                )

    def test_refuses_executable_skeleton_with_dangling_object_reference(self):
        lowered = SpecObject(
            "coverage",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("Covers", "coverage", "missing-requirement")],
        )
        refusals = refuse_executable_skeleton([lowered])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [("coverage", "unsafe-profile-fact:dangling-object-reference:Covers:missing-requirement")],
        )

    def test_refuses_executable_skeleton_reference_to_raw_text_object(self):
        requirement = SpecObject("requirement", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-1", facts=[("Requirement", "requirement")])
        coverage = SpecObject("coverage", Role.VALIDATION_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-2", facts=[("Covers", "coverage", "requirement")])
        refusals = refuse_executable_skeleton([requirement, coverage])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [
                ("requirement", "raw-text-only-skeleton-forbidden"),
                ("coverage", "unsafe-profile-fact:unsafe-object-reference-semantic-level:Covers:requirement:RawTextOnly"),
            ],
        )

    def test_allows_executable_skeleton_reference_to_declared_safe_object(self):
        requirement = SpecObject("requirement", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-1", facts=[("Requirement", "requirement")])
        coverage = SpecObject("coverage", Role.VALIDATION_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-2", facts=[("Covers", "coverage", "requirement")])
        self.assertEqual(refuse_executable_skeleton(iter([requirement, coverage])), [])

    def test_allows_profile_safe_diamond_reference_graph(self):
        shared = SpecObject(
            "shared-source",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.VERIFIED,
            "span-1",
            facts=[("Requirement", "shared-source")],
        )
        left = SpecObject(
            "left-artifact",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-2",
            facts=[("GeneratedFrom", "left-artifact", "shared-source")],
        )
        right = SpecObject(
            "right-artifact",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-3",
            facts=[("GeneratedFrom", "right-artifact", "shared-source")],
        )
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-4",
            facts=[
                ("GeneratedFrom", "requirement", "left-artifact"),
                ("GeneratedFrom", "requirement", "right-artifact"),
            ],
        )
        coverage = SpecObject(
            "coverage",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-5",
            facts=[("Covers", "coverage", "requirement")],
        )

        self.assertEqual(
            refuse_executable_skeleton([coverage, requirement, right, left, shared]),
            [],
        )

    def test_refuses_executable_skeleton_references_to_profile_unsafe_objects(self):
        unprovenanced = SpecObject("unprovenanced", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "", facts=[("Requirement", "unprovenanced")])
        empty = SpecObject("empty", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-2")
        malformed = SpecObject("malformed", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-3", facts=[("RequirementText", "other", "text")])
        coverage = SpecObject(
            "coverage",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-4",
            facts=[
                ("Covers", "coverage", "unprovenanced"),
                ("Covers", "coverage", "empty"),
                ("Covers", "coverage", "malformed"),
            ],
        )
        refusals = refuse_executable_skeleton([unprovenanced, empty, malformed, coverage])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [
                ("unprovenanced", "missing-source-provenance-for-executable-skeleton"),
                ("empty", "missing-profile-facts-for-executable-skeleton"),
                ("malformed", "unsafe-profile-fact:fact-subject-mismatch:RequirementText:expected-malformed:got-other"),
                ("coverage", "unsafe-profile-fact:unsafe-object-reference-missing-profile-facts:Covers:empty"),
                ("coverage", "unsafe-profile-fact:unsafe-object-reference-profile:Covers:malformed:fact-subject-mismatch:RequirementText:expected-malformed:got-other"),
                ("coverage", "unsafe-profile-fact:unsafe-object-reference-missing-source-provenance:Covers:unprovenanced"),
            ],
        )

    def test_refuses_reference_to_object_with_transitive_dangling_reference(self):
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("GeneratedFrom", "requirement", "missing-source-object")],
        )
        coverage = SpecObject("coverage", Role.VALIDATION_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-2", facts=[("Covers", "coverage", "requirement")])
        refusals = refuse_executable_skeleton([requirement, coverage])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [
                ("requirement", "unsafe-profile-fact:dangling-object-reference:GeneratedFrom:missing-source-object"),
                ("coverage", "unsafe-profile-fact:unsafe-object-reference-transitive-dangling:Covers:requirement:GeneratedFrom:missing-source-object"),
            ],
        )

    def test_refuses_reference_to_object_with_transitive_raw_text_reference(self):
        raw_source = SpecObject("raw-source", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-1", facts=[("Requirement", "raw-source")])
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-2",
            facts=[("GeneratedFrom", "requirement", "raw-source")],
        )
        coverage = SpecObject("coverage", Role.VALIDATION_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-3", facts=[("Covers", "coverage", "requirement")])
        refusals = refuse_executable_skeleton([raw_source, requirement, coverage])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [
                ("raw-source", "raw-text-only-skeleton-forbidden"),
                ("requirement", "unsafe-profile-fact:unsafe-object-reference-semantic-level:GeneratedFrom:raw-source:RawTextOnly"),
                ("coverage", "unsafe-profile-fact:unsafe-object-reference-transitive-semantic-level:Covers:requirement:GeneratedFrom:raw-source:RawTextOnly"),
            ],
        )

    def test_transitive_refusal_is_stable_across_fact_order(self):
        raw_targets = [
            SpecObject("alpha-source", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-1", facts=[("Requirement", "alpha-source")]),
            SpecObject("zeta-source", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-2", facts=[("Requirement", "zeta-source")]),
        ]
        expected = "unsafe-profile-fact:unsafe-object-reference-transitive-semantic-level:Covers:requirement:GeneratedFrom:alpha-source:RawTextOnly"
        for target_order in (raw_targets, list(reversed(raw_targets))):
            with self.subTest(order=[target.id for target in target_order]):
                requirement = SpecObject(
                    "requirement",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-3",
                    facts=[("GeneratedFrom", "requirement", target.id) for target in target_order],
                )
                coverage = SpecObject(
                    "coverage",
                    Role.VALIDATION_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-4",
                    facts=[("Covers", "coverage", "requirement")],
                )
                coverage_reasons = [
                    refusal.reason
                    for refusal in refuse_executable_skeleton([*raw_targets, requirement, coverage])
                    if refusal.object_id == "coverage"
                ]
                self.assertEqual(coverage_reasons, [expected])

    def test_originating_refusal_order_is_stable_across_fact_order(self):
        referenced = [
            SpecObject("alpha-target", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-1", facts=[("Requirement", "alpha-target")]),
            SpecObject("zeta-target", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-2", facts=[("Requirement", "zeta-target")]),
        ]
        expected = [
            "unsafe-profile-fact:unsafe-object-reference-semantic-level:GeneratedFrom:alpha-target:RawTextOnly",
            "unsafe-profile-fact:unsafe-object-reference-semantic-level:GeneratedFrom:zeta-target:RawTextOnly",
        ]
        facts = [
            ("GeneratedFrom", "origin", "zeta-target"),
            ("GeneratedFrom", "origin", "alpha-target"),
        ]
        for fact_order in (facts, list(reversed(facts))):
            with self.subTest(order=[fact[2] for fact in fact_order]):
                origin = SpecObject(
                    "origin",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-3",
                    facts=fact_order,
                )
                origin_reasons = [
                    refusal.reason
                    for refusal in refuse_executable_skeleton([*referenced, origin])
                    if refusal.object_id == "origin"
                ]
                self.assertEqual(origin_reasons, expected)

    def test_deep_refusal_is_stable_across_fact_order(self):
        raw_targets = [
            SpecObject("alpha-source", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-1", facts=[("Requirement", "alpha-source")]),
            SpecObject("zeta-source", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-2", facts=[("Requirement", "zeta-source")]),
        ]
        expected = "unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:Covers:requirement->alpha-artifact->alpha-source:RawTextOnly"
        for target_order in (raw_targets, list(reversed(raw_targets))):
            with self.subTest(order=[target.id for target in target_order]):
                artifacts = [
                    SpecObject(
                        target.id.replace("source", "artifact"),
                        Role.REQUIREMENT_OBJECT,
                        SemanticLevel.BACKEND_LOWERED,
                        f"span-{index + 3}",
                        facts=[("GeneratedFrom", target.id.replace("source", "artifact"), target.id)],
                    )
                    for index, target in enumerate(target_order)
                ]
                requirement = SpecObject(
                    "requirement",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-5",
                    facts=[("GeneratedFrom", "requirement", artifact.id) for artifact in artifacts],
                )
                coverage = SpecObject(
                    "coverage",
                    Role.VALIDATION_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-6",
                    facts=[("Covers", "coverage", "requirement")],
                )
                coverage_reasons = [
                    refusal.reason
                    for refusal in refuse_executable_skeleton([*raw_targets, *artifacts, requirement, coverage])
                    if refusal.object_id == "coverage"
                ]
                self.assertEqual(coverage_reasons, [expected])

    def test_deep_refusal_uses_canonical_path_across_mixed_depths(self):
        alpha_leaf = SpecObject(
            "alpha-leaf",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("GeneratedFrom", "alpha-leaf", "alpha-raw")],
        )
        alpha_raw = SpecObject("alpha-raw", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-2", facts=[("Requirement", "alpha-raw")])
        zeta_raw = SpecObject("zeta-raw", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-3", facts=[("Requirement", "zeta-raw")])
        artifact = SpecObject(
            "artifact",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-4",
            facts=[
                ("GeneratedFrom", "artifact", "zeta-raw"),
                ("GeneratedFrom", "artifact", "alpha-leaf"),
            ],
        )
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-5",
            facts=[("GeneratedFrom", "requirement", "artifact")],
        )
        coverage = SpecObject(
            "coverage",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-6",
            facts=[("Covers", "coverage", "requirement")],
        )

        coverage_reasons = [
            refusal.reason
            for refusal in refuse_executable_skeleton([alpha_leaf, alpha_raw, zeta_raw, artifact, requirement, coverage])
            if refusal.object_id == "coverage"
        ]
        self.assertEqual(
            coverage_reasons,
            [
                "unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:"
                "Covers:requirement->artifact->alpha-leaf->alpha-raw:RawTextOnly"
            ],
        )

    def test_refuses_reference_with_deep_raw_text_dependency(self):
        raw_source = SpecObject("raw-source", Role.REQUIREMENT_OBJECT, SemanticLevel.RAW_TEXT_ONLY, "span-1", facts=[("Requirement", "raw-source")])
        artifact = SpecObject(
            "artifact",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-2",
            facts=[("GeneratedFrom", "artifact", "raw-source")],
        )
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-3",
            facts=[("GeneratedFrom", "requirement", "artifact")],
        )
        coverage = SpecObject("coverage", Role.VALIDATION_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-4", facts=[("Covers", "coverage", "requirement")])
        refusals = refuse_executable_skeleton([raw_source, artifact, requirement, coverage])
        self.assertIn(
            (
                "coverage",
                "unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:Covers:requirement->artifact->raw-source:RawTextOnly",
            ),
            [(r.object_id, r.reason) for r in refusals],
        )

    def test_semantic_level_refusal_precedes_missing_provenance_through_reference_depths(self):
        for depth in (1, 2, 3):
            with self.subTest(depth=depth):
                parsed = SpecObject(
                    "parsed",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    "",
                    facts=[("Requirement", "parsed")],
                )
                objects = [parsed]
                target_id = parsed.id
                for hop in range(depth - 1):
                    artifact = SpecObject(
                        f"artifact-{hop}",
                        Role.REQUIREMENT_OBJECT,
                        SemanticLevel.BACKEND_LOWERED,
                        f"span-{hop + 1}",
                        facts=[("GeneratedFrom", f"artifact-{hop}", target_id)],
                    )
                    objects.append(artifact)
                    target_id = artifact.id
                coverage = SpecObject(
                    "coverage",
                    Role.VALIDATION_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-coverage",
                    facts=[("Covers", "coverage", target_id)],
                )
                refusals = refuse_executable_skeleton([*objects, coverage])
                coverage_reasons = [r.reason for r in refusals if r.object_id == "coverage"]
                self.assertEqual(len(coverage_reasons), 1)
                self.assertIn("TemplateParsed", coverage_reasons[0])
                self.assertNotIn("MissingSourceProvenance", coverage_reasons[0])

    def test_refuses_reference_with_deep_dangling_dependency(self):
        artifact = SpecObject(
            "artifact",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("GeneratedFrom", "artifact", "missing-source")],
        )
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-2",
            facts=[("GeneratedFrom", "requirement", "artifact")],
        )
        coverage = SpecObject("coverage", Role.VALIDATION_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-3", facts=[("Covers", "coverage", "requirement")])
        refusals = refuse_executable_skeleton([artifact, requirement, coverage])
        self.assertIn(
            (
                "coverage",
                "unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:Covers:requirement->artifact->missing-source:DanglingReference",
            ),
            [(r.object_id, r.reason) for r in refusals],
        )

    def test_refuses_reference_with_deep_profile_unsafe_dependencies(self):
        unsafe_targets = [
            (
                SpecObject("unprovenanced", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "", facts=[("Requirement", "unprovenanced")]),
                "MissingSourceProvenance",
            ),
            (
                SpecObject("empty", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-1"),
                "MissingProfileFacts",
            ),
            (
                SpecObject("malformed", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-2", facts=[("RequirementText", "other", "text")]),
                "UnsafeProfile:fact-subject-mismatch:RequirementText:expected-malformed:got-other",
            ),
        ]
        for unsafe_target, expected_reason in unsafe_targets:
            with self.subTest(target=unsafe_target.id):
                artifact = SpecObject(
                    "artifact",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-3",
                    facts=[("GeneratedFrom", "artifact", unsafe_target.id)],
                )
                requirement = SpecObject(
                    "requirement",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-4",
                    facts=[("GeneratedFrom", "requirement", "artifact")],
                )
                coverage = SpecObject(
                    "coverage",
                    Role.VALIDATION_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-5",
                    facts=[("Covers", "coverage", "requirement")],
                )
                refusals = refuse_executable_skeleton([unsafe_target, artifact, requirement, coverage])
                self.assertIn(
                    (
                        "coverage",
                        f"unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:Covers:requirement->artifact->{unsafe_target.id}:{expected_reason}",
                    ),
                    [(r.object_id, r.reason) for r in refusals],
                )

    def test_refuses_reference_with_one_hop_transitive_unsafe_dependencies(self):
        unsafe_targets = [
            (
                [SpecObject("source", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "", facts=[("Requirement", "source")])],
                "MissingSourceProvenance",
            ),
            (
                [SpecObject("source", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-1")],
                "MissingProfileFacts",
            ),
            (
                [SpecObject("source", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-2", facts=[("RequirementText", "other", "text")])],
                "UnsafeProfile:fact-subject-mismatch:RequirementText:expected-source:got-other",
            ),
            (
                [
                    SpecObject("source", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-3", facts=[("Requirement", "source")]),
                    SpecObject("source", Role.REQUIREMENT_OBJECT, SemanticLevel.VERIFIED, "span-4", facts=[("Requirement", "source")]),
                ],
                "AmbiguousReference",
            ),
        ]
        for targets, expected_reason in unsafe_targets:
            with self.subTest(reason=expected_reason):
                requirement = SpecObject(
                    "requirement",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-5",
                    facts=[("GeneratedFrom", "requirement", "source")],
                )
                coverage = SpecObject(
                    "coverage",
                    Role.VALIDATION_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    "span-6",
                    facts=[("Covers", "coverage", "requirement")],
                )
                refusals = refuse_executable_skeleton([*targets, requirement, coverage])
                self.assertIn(
                    (
                        "coverage",
                        f"unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:Covers:requirement->source:{expected_reason}",
                    ),
                    [(r.object_id, r.reason) for r in refusals],
                )

    def test_refuses_reference_with_deep_reference_cycle(self):
        artifact = SpecObject(
            "artifact",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("GeneratedFrom", "artifact", "requirement")],
        )
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-2",
            facts=[("GeneratedFrom", "requirement", "artifact")],
        )
        coverage = SpecObject("coverage", Role.VALIDATION_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-3", facts=[("Covers", "coverage", "requirement")])
        refusals = refuse_executable_skeleton([artifact, requirement, coverage])
        self.assertIn(
            (
                "coverage",
                "unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:Covers:requirement->artifact->requirement:ReferenceCycle",
            ),
            [(r.object_id, r.reason) for r in refusals],
        )

    def test_refuses_reference_with_deep_ambiguous_dependency(self):
        duplicate_a = SpecObject(
            "source",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("Requirement", "source")],
        )
        duplicate_b = SpecObject(
            "source",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.VERIFIED,
            "span-2",
            facts=[("Requirement", "source")],
        )
        artifact = SpecObject(
            "artifact",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-3",
            facts=[("GeneratedFrom", "artifact", "source")],
        )
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-4",
            facts=[("GeneratedFrom", "requirement", "artifact")],
        )
        coverage = SpecObject(
            "coverage",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-5",
            facts=[("Covers", "coverage", "requirement")],
        )
        refusals = refuse_executable_skeleton([duplicate_a, duplicate_b, artifact, requirement, coverage])
        self.assertIn(
            (
                "coverage",
                "unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:Covers:requirement->artifact->source:AmbiguousReference",
            ),
            [(r.object_id, r.reason) for r in refusals],
        )

    def test_refuses_duplicate_object_ids_and_ambiguous_references(self):
        requirement_a = SpecObject("requirement", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-1", facts=[("Requirement", "requirement")])
        requirement_b = SpecObject("requirement", Role.REQUIREMENT_OBJECT, SemanticLevel.VERIFIED, "span-2", facts=[("Requirement", "requirement")])
        coverage = SpecObject("coverage", Role.VALIDATION_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-3", facts=[("Covers", "coverage", "requirement")])
        refusals = refuse_executable_skeleton([requirement_a, requirement_b, coverage])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [
                ("requirement", "duplicate-object-id-for-executable-skeleton"),
                ("requirement", "duplicate-object-id-for-executable-skeleton"),
                ("coverage", "unsafe-profile-fact:ambiguous-object-reference:Covers:requirement"),
            ],
        )

    def test_refuses_all_duplicate_object_ids_from_reified_atoms_and_summary(self):
        questions = [
            SpecObject(
                "duplicate-question",
                Role.QUESTION_OBJECT,
                SemanticLevel.TEMPLATE_PARSED,
                "span-1",
                facts=[("QuestionText", "duplicate-question", "First question?")],
            ),
            SpecObject(
                "duplicate-question",
                Role.QUESTION_OBJECT,
                SemanticLevel.TEMPLATE_PARSED,
                "span-2",
                facts=[("QuestionText", "duplicate-question", "Conflicting question?")],
            ),
        ]

        atoms, refusals = emit_reified_atoms(SpecDocument(objects=questions))
        rendered = "\n".join(atoms)

        self.assertNotIn("(spec-object duplicate-question ", rendered)
        self.assertNotIn("(QuestionText duplicate-question ", rendered)
        self.assertNotIn("(derived-from duplicate-question ", rendered)
        self.assertIn("(document-validation-summary document 0 0 0 0)", atoms)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                (
                    "duplicate-question",
                    "duplicate-object-id-for-reified-emission",
                ),
                (
                    "duplicate-question",
                    "duplicate-object-id-for-reified-emission",
                ),
            ],
        )

    def test_refuses_executable_skeleton_without_source_provenance(self):
        lowered = SpecObject("unprovenanced", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "", facts=[("Requirement", "unprovenanced")])
        refusals = refuse_executable_skeleton([lowered])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [("unprovenanced", "missing-source-provenance-for-executable-skeleton")],
        )

    def test_refuses_whitespace_only_source_provenance_directly_and_transitively(self):
        unprovenanced = SpecObject(
            "unprovenanced",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            " \t ",
            facts=[("Requirement", "unprovenanced")],
        )
        requirement = SpecObject(
            "requirement",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-1",
            facts=[("GeneratedFrom", "requirement", "unprovenanced")],
        )
        coverage = SpecObject(
            "coverage",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-2",
            facts=[("Covers", "coverage", "requirement")],
        )

        refusals = refuse_executable_skeleton([unprovenanced, requirement, coverage])
        refusal_pairs = [(refusal.object_id, refusal.reason) for refusal in refusals]
        self.assertIn(
            ("unprovenanced", "missing-source-provenance-for-executable-skeleton"),
            refusal_pairs,
        )
        self.assertIn(
            (
                "requirement",
                "unsafe-profile-fact:unsafe-object-reference-missing-source-provenance:GeneratedFrom:unprovenanced",
            ),
            refusal_pairs,
        )
        self.assertIn(
            (
                "coverage",
                "unsafe-profile-fact:unsafe-object-reference-deep-semantic-level:Covers:requirement->unprovenanced:MissingSourceProvenance",
            ),
            refusal_pairs,
        )

    def test_refuses_non_string_source_provenance_without_aliasing_or_crashing(self):
        malformed = SpecObject(
            "malformed-provenance",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            7,
            facts=[("Requirement", "malformed-provenance")],
        )
        referencing = SpecObject(
            "referencing",
            Role.VALIDATION_OBJECT,
            SemanticLevel.BACKEND_LOWERED,
            "span-referencing",
            facts=[("Covers", "referencing", "malformed-provenance")],
        )

        atoms, reified_refusals = emit_reified_atoms(
            SpecDocument(objects=[malformed, referencing])
        )
        executable_refusals = refuse_executable_skeleton([malformed, referencing])

        self.assertNotIn("(derived-from malformed-provenance 7)", atoms)
        self.assertNotIn(
            "(spec-object malformed-provenance RequirementObject BackendLowered)",
            atoms,
        )
        self.assertNotIn("(Requirement malformed-provenance)", atoms)
        self.assertIn(
            "(spec-object referencing ValidationObject BackendLowered)",
            atoms,
        )
        self.assertTrue(
            any(
                refusal.reason
                == "unsupported-source-span-id-type:int-for-reified-emission"
                for refusal in reified_refusals
            )
        )
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in executable_refusals],
            [
                (
                    "malformed-provenance",
                    "unsupported-source-span-id-type:int-for-executable-skeleton",
                ),
                (
                    "referencing",
                    "unsafe-profile-fact:unsafe-object-reference-"
                    "unsupported-source-span-id-type:int:Covers:malformed-provenance",
                ),
            ],
        )

    def test_refuses_non_string_validation_obligation_source_provenance(self):
        obligation = ValidationObligation(
            "obligation-malformed-provenance",
            "manual-review",
            "target",
            "Review the target.",
            7,
        )

        atoms, refusals = emit_reified_atoms(
            SpecDocument(validation_obligations=[obligation])
        )

        self.assertNotIn(
            "(validation-obligation obligation-malformed-provenance manual-review target)",
            atoms,
        )
        self.assertNotIn(
            "(derived-from obligation-malformed-provenance 7)",
            atoms,
        )
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                (
                    "obligation-malformed-provenance",
                    "unsupported-source-span-id-type:int-for-validation-obligation",
                )
            ],
        )

    def test_refuses_blank_reified_source_provenance_without_emitting_it(self):
        malformed_object = SpecObject(
            "object-blank-provenance",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            " \t ",
            [("Requirement", "object-blank-provenance")],
        )
        malformed_obligation = ValidationObligation(
            "obligation-blank-provenance",
            "manual-review",
            "object-blank-provenance",
            "Review the target.",
            " \t ",
        )

        atoms, refusals = emit_reified_atoms(
            SpecDocument(
                objects=[malformed_object],
                validation_obligations=[malformed_obligation],
            )
        )
        rendered = "\n".join(atoms)

        self.assertNotIn(
            "(spec-object object-blank-provenance RequirementObject TemplateParsed)",
            atoms,
        )
        self.assertNotIn(
            "(validation-obligation obligation-blank-provenance manual-review object-blank-provenance)",
            atoms,
        )
        self.assertNotIn("(derived-from object-blank-provenance", rendered)
        self.assertNotIn("(derived-from obligation-blank-provenance", rendered)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                (
                    "object-blank-provenance",
                    "missing-source-provenance-for-reified-emission",
                ),
                (
                    "obligation-blank-provenance",
                    "missing-source-provenance-for-validation-obligation",
                ),
            ],
        )

    def test_refuses_malformed_validation_obligation_ids_without_aliasing(self):
        obligations = [
            ValidationObligation(7, "numeric-id", "target", "Malformed ID."),
            ValidationObligation("7", "string-id", "target", "Valid ID."),
            ValidationObligation(" \t ", "blank-id", "target", "Malformed ID."),
        ]

        atoms, refusals = emit_reified_atoms(
            SpecDocument(validation_obligations=obligations)
        )
        rendered = "\n".join(atoms)

        self.assertIn("(validation-obligation 7 string-id target)", atoms)
        self.assertIn("(validation-rationale 7 \"Valid ID.\")", atoms)
        self.assertNotIn("numeric-id", rendered)
        self.assertNotIn("blank-id", rendered)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                ("7", "unsupported-validation-obligation-id-type:int"),
                (" \t ", "missing-validation-obligation-id"),
            ],
        )

    def test_refuses_all_duplicate_validation_obligation_ids_and_linked_checks(self):
        obligations = [
            ValidationObligation("duplicate", "property-a", "target-a", "First claim."),
            ValidationObligation("duplicate", "property-b", "target-b", "Second claim."),
        ]
        check = CheckRecord(
            "linked-check",
            "duplicate",
            "property-a",
            "target-a",
            CheckStatus.PASS,
            "Must not select one duplicate by order.",
        )

        atoms, refusals = emit_reified_atoms(
            SpecDocument(validation_obligations=obligations, checks=[check])
        )
        rendered = "\n".join(atoms)

        self.assertNotIn("(validation-obligation duplicate ", rendered)
        self.assertNotIn("(validation-rationale duplicate ", rendered)
        self.assertNotIn("linked-check", rendered)
        self.assertIn("(document-validation-summary document 0 0 0 0)", atoms)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                ("duplicate", "duplicate-validation-obligation-id"),
                ("duplicate", "duplicate-validation-obligation-id"),
                ("linked-check", "check-obligation-not-emitted:duplicate"),
            ],
        )

    def test_refuses_malformed_validation_obligation_properties_without_aliasing(self):
        obligations = [
            ValidationObligation("numeric-property", 7, "target", "Malformed property."),
            ValidationObligation("string-property", "7", "target", "Valid property."),
            ValidationObligation("blank-property", " \t ", "target", "Malformed property."),
        ]

        atoms, refusals = emit_reified_atoms(
            SpecDocument(validation_obligations=obligations)
        )
        rendered = "\n".join(atoms)

        self.assertIn("(validation-obligation string-property 7 target)", atoms)
        self.assertIn('(validation-rationale string-property "Valid property.")', atoms)
        self.assertNotIn("numeric-property", rendered)
        self.assertNotIn("blank-property", rendered)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                (
                    "numeric-property",
                    "unsupported-validation-obligation-property-type:int",
                ),
                ("blank-property", "missing-validation-obligation-property"),
            ],
        )

    def test_refuses_malformed_validation_obligation_targets_without_aliasing(self):
        obligations = [
            ValidationObligation("numeric-target", "property", 7, "Malformed target."),
            ValidationObligation("string-target", "property", "7", "Valid target."),
            ValidationObligation("blank-target", "property", " \t ", "Malformed target."),
        ]

        atoms, refusals = emit_reified_atoms(
            SpecDocument(validation_obligations=obligations)
        )
        rendered = "\n".join(atoms)

        self.assertIn("(validation-obligation string-target property 7)", atoms)
        self.assertIn('(validation-rationale string-target "Valid target.")', atoms)
        self.assertNotIn("numeric-target", rendered)
        self.assertNotIn("blank-target", rendered)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                (
                    "numeric-target",
                    "unsupported-validation-obligation-target-id-type:int",
                ),
                ("blank-target", "missing-validation-obligation-target-id"),
            ],
        )

    def test_refuses_malformed_validation_obligation_rationales_without_aliasing(self):
        obligations = [
            ValidationObligation("numeric-rationale", "property", "target", 7),
            ValidationObligation("string-rationale", "property", "target", "7"),
            ValidationObligation("blank-rationale", "property", "target", " \t "),
        ]

        atoms, refusals = emit_reified_atoms(
            SpecDocument(validation_obligations=obligations)
        )
        rendered = "\n".join(atoms)

        self.assertIn(
            "(validation-obligation string-rationale property target)", atoms
        )
        self.assertIn("(validation-rationale string-rationale 7)", atoms)
        self.assertNotIn("numeric-rationale", rendered)
        self.assertNotIn("blank-rationale", rendered)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                (
                    "numeric-rationale",
                    "unsupported-validation-obligation-rationale-type:int",
                ),
                ("blank-rationale", "missing-validation-obligation-rationale"),
            ],
        )

    def test_refuses_malformed_check_ids_without_aliasing_or_summary_counts(self):
        checks = [
            CheckRecord(7, "obligation", "property", "target", CheckStatus.FAIL, "Malformed ID."),
            CheckRecord("7", "obligation", "property", "target", CheckStatus.PASS, "Valid ID."),
            CheckRecord(" \t ", "obligation", "property", "target", CheckStatus.UNKNOWN, "Malformed ID."),
        ]

        atoms, refusals = emit_reified_atoms(document_with_checks(checks))
        rendered = "\n".join(atoms)

        self.assertIn("(check 7 property target Pass)", atoms)
        self.assertIn("(check-obligation 7 obligation)", atoms)
        self.assertIn('(check-evidence 7 "Valid ID.")', atoms)
        self.assertNotIn("numeric-id", rendered)
        self.assertNotIn("blank-id", rendered)
        self.assertIn("(document-validation-summary document 1 0 0 0)", atoms)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                ("7", "unsupported-check-id-type:int"),
                (" \t ", "missing-check-id"),
            ],
        )

    def test_refuses_all_duplicate_check_ids_without_summary_counts(self):
        checks = [
            CheckRecord(
                "duplicate-check",
                "obligation",
                "property",
                "target",
                CheckStatus.PASS,
                "First result.",
            ),
            CheckRecord(
                "duplicate-check",
                "obligation",
                "property",
                "target",
                CheckStatus.FAIL,
                "Conflicting result.",
            ),
        ]

        atoms, refusals = emit_reified_atoms(document_with_checks(checks))
        rendered = "\n".join(atoms)

        self.assertNotIn("(check duplicate-check ", rendered)
        self.assertNotIn("(check-obligation duplicate-check ", rendered)
        self.assertNotIn("(check-evidence duplicate-check ", rendered)
        self.assertIn("(document-validation-summary document 0 0 0 0)", atoms)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                ("duplicate-check", "duplicate-check-id"),
                ("duplicate-check", "duplicate-check-id"),
            ],
        )

    def test_refuses_malformed_check_obligation_ids_without_aliasing(self):
        checks = [
            CheckRecord("numeric-link", 7, "property", "target", CheckStatus.FAIL, "Malformed link."),
            CheckRecord("string-link", "7", "property", "target", CheckStatus.PASS, "Valid link."),
            CheckRecord("blank-link", " \t ", "property", "target", CheckStatus.UNKNOWN, "Malformed link."),
        ]

        atoms, refusals = emit_reified_atoms(
            document_with_checks(checks, obligation_id="7")
        )
        rendered = "\n".join(atoms)

        self.assertIn("(check string-link property target Pass)", atoms)
        self.assertIn("(check-obligation string-link 7)", atoms)
        self.assertIn('(check-evidence string-link "Valid link.")', atoms)
        self.assertNotIn("numeric-link", rendered)
        self.assertNotIn("blank-link", rendered)
        self.assertIn("(document-validation-summary document 1 0 0 0)", atoms)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                ("numeric-link", "unsupported-check-obligation-id-type:int"),
                ("blank-link", "missing-check-obligation-id"),
            ],
        )

    def test_refuses_undeclared_check_statuses_without_aliasing_or_summary_counts(self):
        checks = [
            CheckRecord("string-pass", "obligation", "property", "target", "Pass", "Malformed status."),
            CheckRecord("enum-pass", "obligation", "property", "target", CheckStatus.PASS, "Valid status."),
            CheckRecord("missing-status", "obligation", "property", "target", None, "Malformed status."),
        ]

        atoms, refusals = emit_reified_atoms(document_with_checks(checks))
        rendered = "\n".join(atoms)

        self.assertIn("(check enum-pass property target Pass)", atoms)
        self.assertIn("(check-obligation enum-pass obligation)", atoms)
        self.assertIn('(check-evidence enum-pass "Valid status.")', atoms)
        self.assertNotIn("string-pass", rendered)
        self.assertNotIn("missing-status", rendered)
        self.assertIn("(document-validation-summary document 1 0 0 0)", atoms)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                ("string-pass", "unsupported-check-status-type:str"),
                ("missing-status", "unsupported-check-status-type:NoneType"),
            ],
        )

    def test_refuses_malformed_check_properties_without_aliasing_or_summary_counts(self):
        checks = [
            CheckRecord("numeric-property", "obligation", 7, "target", CheckStatus.FAIL, "Malformed property."),
            CheckRecord("string-property", "obligation", "7", "target", CheckStatus.PASS, "Valid property."),
            CheckRecord("blank-property", "obligation", " \t ", "target", CheckStatus.UNKNOWN, "Malformed property."),
        ]

        atoms, refusals = emit_reified_atoms(
            document_with_checks(checks, obligation_property="7")
        )
        rendered = "\n".join(atoms)

        self.assertIn("(check string-property 7 target Pass)", atoms)
        self.assertIn("(check-obligation string-property obligation)", atoms)
        self.assertIn('(check-evidence string-property "Valid property.")', atoms)
        self.assertNotIn("numeric-property", rendered)
        self.assertNotIn("blank-property", rendered)
        self.assertIn("(document-validation-summary document 1 0 0 0)", atoms)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                ("numeric-property", "unsupported-check-property-type:int"),
                ("blank-property", "missing-check-property"),
            ],
        )

    def test_refuses_malformed_check_target_ids_without_aliasing_or_summary_counts(self):
        checks = [
            CheckRecord("numeric-target", "obligation", "property", 7, CheckStatus.FAIL, "Malformed target."),
            CheckRecord("string-target", "obligation", "property", "7", CheckStatus.PASS, "Valid target."),
            CheckRecord("blank-target", "obligation", "property", " \t ", CheckStatus.UNKNOWN, "Malformed target."),
        ]

        atoms, refusals = emit_reified_atoms(
            document_with_checks(checks, obligation_target="7")
        )
        rendered = "\n".join(atoms)

        self.assertIn("(check string-target property 7 Pass)", atoms)
        self.assertIn("(check-obligation string-target obligation)", atoms)
        self.assertIn('(check-evidence string-target "Valid target.")', atoms)
        self.assertNotIn("numeric-target", rendered)
        self.assertNotIn("blank-target", rendered)
        self.assertIn("(document-validation-summary document 1 0 0 0)", atoms)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                ("numeric-target", "unsupported-check-target-id-type:int"),
                ("blank-target", "missing-check-target-id"),
            ],
        )

    def test_refuses_malformed_check_evidence_without_aliasing_or_summary_counts(self):
        checks = [
            CheckRecord("numeric-evidence", "obligation", "property", "target", CheckStatus.FAIL, 7),
            CheckRecord("string-evidence", "obligation", "property", "target", CheckStatus.PASS, "7"),
            CheckRecord("blank-evidence", "obligation", "property", "target", CheckStatus.UNKNOWN, " \t "),
        ]

        atoms, refusals = emit_reified_atoms(document_with_checks(checks))
        rendered = "\n".join(atoms)

        self.assertIn("(check string-evidence property target Pass)", atoms)
        self.assertIn("(check-obligation string-evidence obligation)", atoms)
        self.assertIn("(check-evidence string-evidence 7)", atoms)
        self.assertNotIn("numeric-evidence", rendered)
        self.assertNotIn("blank-evidence", rendered)
        self.assertIn("(document-validation-summary document 1 0 0 0)", atoms)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                ("numeric-evidence", "unsupported-check-evidence-type:int"),
                ("blank-evidence", "missing-check-evidence"),
            ],
        )

    def test_refuses_check_link_to_unemitted_validation_obligation(self):
        malformed_obligation = ValidationObligation(
            "unemitted-obligation",
            "property",
            "target",
            " ",
        )
        check = CheckRecord(
            "dangling-check",
            "unemitted-obligation",
            "property",
            "target",
            CheckStatus.PASS,
            "Would otherwise look valid.",
        )

        atoms, refusals = emit_reified_atoms(
            SpecDocument(
                validation_obligations=[malformed_obligation],
                checks=[check],
            )
        )
        rendered = "\n".join(atoms)

        self.assertNotIn("unemitted-obligation", rendered)
        self.assertNotIn("dangling-check", rendered)
        self.assertIn("(document-validation-summary document 0 0 0 0)", atoms)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                (
                    "unemitted-obligation",
                    "missing-validation-obligation-rationale",
                ),
                (
                    "dangling-check",
                    "check-obligation-not-emitted:unemitted-obligation",
                ),
            ],
        )

    def test_refuses_checks_that_disagree_with_their_validation_obligation(self):
        checks = [
            CheckRecord(
                "valid-check",
                "obligation",
                "property",
                "target",
                CheckStatus.PASS,
                "Matches its obligation.",
            ),
            CheckRecord(
                "wrong-property",
                "obligation",
                "other-property",
                "target",
                CheckStatus.FAIL,
                "Must not be exported.",
            ),
            CheckRecord(
                "wrong-target",
                "obligation",
                "property",
                "other-target",
                CheckStatus.UNKNOWN,
                "Must not be exported.",
            ),
        ]

        atoms, refusals = emit_reified_atoms(document_with_checks(checks))
        rendered = "\n".join(atoms)

        self.assertIn("(check valid-check property target Pass)", atoms)
        self.assertNotIn("wrong-property", rendered)
        self.assertNotIn("wrong-target", rendered)
        self.assertIn("(document-validation-summary document 1 0 0 0)", atoms)
        self.assertEqual(
            [(refusal.object_id, refusal.reason) for refusal in refusals],
            [
                (
                    "wrong-property",
                    "check-property-mismatch-with-obligation",
                ),
                (
                    "wrong-target",
                    "check-target-mismatch-with-obligation",
                ),
            ],
        )

    def test_refuses_executable_skeleton_without_profile_facts(self):
        lowered = SpecObject("empty", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-1")
        refusals = refuse_executable_skeleton([lowered])
        self.assertEqual(
            [(r.object_id, r.reason) for r in refusals],
            [("empty", "missing-profile-facts-for-executable-skeleton")],
        )

    def test_allows_executable_skeleton_gate_for_profile_safe_lowered_object(self):
        lowered = SpecObject("safe", Role.REQUIREMENT_OBJECT, SemanticLevel.BACKEND_LOWERED, "span-1", facts=[("Requirement", "safe")])
        self.assertEqual(refuse_executable_skeleton([lowered]), [])

    def test_basic_reified_atom_emission_stub_when_safe(self):
        doc = SpecDocument(objects=[obj(SemanticLevel.TEMPLATE_PARSED)])
        atoms, refusals = emit_reified_atoms(doc)
        self.assertFalse(refusals)
        self.assertIn("(target-profile petta_reified_v0)", atoms)
        self.assertIn("(spec-object obj-1 RequirementObject TemplateParsed)", atoms)

    def test_reified_atom_refuses_raw_text_only(self):
        doc = SpecDocument(objects=[obj(SemanticLevel.RAW_TEXT_ONLY)])
        atoms, refusals = emit_reified_atoms(doc)
        self.assertEqual(atoms, ["(target-profile petta_reified_v0)", "(document-validation-summary document 0 0 0 0)", "(information-flow-graph-summary document 0 0 0 0 0 0 0 0 0)"])
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

    def test_refuses_obligation_when_its_semantic_object_target_is_refused(self):
        refused = SpecObject(
            "object-refused",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.RAW_TEXT_ONLY,
        )
        valid = SpecObject(
            "object-valid",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
        )
        obligations = [
            ValidationObligation(
                "obligation-refused", "reviewed", "object-refused:fact:0",
                "Do not validate a target that was not emitted.",
            ),
            ValidationObligation(
                "obligation-valid", "reviewed", "object-valid:fact:0",
                "The valid target remains reviewable.",
            ),
        ]

        atoms, refusals = emit_reified_atoms(
            SpecDocument(objects=[refused, valid], validation_obligations=obligations)
        )

        self.assertNotIn(
            "(validation-obligation obligation-refused reviewed object-refused:fact:0)",
            atoms,
        )
        self.assertIn(
            "(validation-obligation obligation-valid reviewed object-valid:fact:0)",
            atoms,
        )
        self.assertIn(
            (
                "obligation-refused",
                "validation-obligation-target-object-not-emitted",
            ),
            {(refusal.object_id, refusal.reason) for refusal in refusals},
        )

    def test_refuses_target_owned_by_most_specific_colon_bearing_object_id(self):
        parent = SpecObject(
            "object",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
        )
        refused_child = SpecObject(
            "object:child",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.RAW_TEXT_ONLY,
        )
        obligation = ValidationObligation(
            "obligation-child", "reviewed", "object:child:fact:0",
            "The longest matching object identity owns the target.",
        )

        atoms, refusals = emit_reified_atoms(
            SpecDocument(
                objects=[parent, refused_child],
                validation_obligations=[obligation],
            )
        )

        self.assertNotIn(
            "(validation-obligation obligation-child reviewed object:child:fact:0)",
            atoms,
        )
        self.assertIn(
            ("obligation-child", "validation-obligation-target-object-not-emitted"),
            {(refusal.object_id, refusal.reason) for refusal in refusals},
        )

    def test_trailing_colon_is_not_an_object_scoped_target(self):
        obj = SpecObject(
            "object:child",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
        )
        obligation = ValidationObligation(
            "obligation-empty-subtarget", "reviewed", "object:child:",
            "A trailing separator does not identify a subtarget.",
        )

        atoms, refusals = emit_reified_atoms(
            SpecDocument(objects=[obj], validation_obligations=[obligation])
        )

        self.assertIn("(spec-object object:child RequirementObject TemplateParsed)", atoms)
        self.assertNotIn(
            "(validation-obligation obligation-empty-subtarget reviewed object:child:)",
            atoms,
        )
        self.assertIn(
            (
                "obligation-empty-subtarget",
                "validation-obligation-target-has-empty-object-subtarget",
            ),
            {(refusal.object_id, refusal.reason) for refusal in refusals},
        )

    def test_whitespace_only_suffix_is_not_an_object_scoped_target(self):
        obj = SpecObject(
            "object:child",
            Role.REQUIREMENT_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
        )
        obligation = ValidationObligation(
            "obligation-blank-subtarget", "reviewed", "object:child: \t ",
            "Whitespace does not identify a subtarget.",
        )

        atoms, refusals = emit_reified_atoms(
            SpecDocument(objects=[obj], validation_obligations=[obligation])
        )

        self.assertFalse(
            any(atom.startswith("(validation-obligation obligation-blank-subtarget ") for atom in atoms)
        )
        self.assertIn(
            (
                "obligation-blank-subtarget",
                "validation-obligation-target-has-empty-object-subtarget",
            ),
            {(refusal.object_id, refusal.reason) for refusal in refusals},
        )


if __name__ == "__main__":
    unittest.main()

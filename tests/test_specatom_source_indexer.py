import unittest

from specatom_hs.passes import compile_source
from specatom_hs.source_indexer import index_source


TEXT = """***definitions***\n- :Task: is work.\n  - Name - required.\n\n***acceptance tests***\n- Given x, when y, then z.\n"""


class SourceIndexerTests(unittest.TestCase):
    def test_source_indexing_records_file_section_item_and_spans(self):
        doc = index_source(TEXT, "minimal.plain")
        self.assertEqual(len(doc.files), 1)
        self.assertTrue(doc.files[0].digest.startswith("sha256:"))
        self.assertEqual([s.kind for s in doc.sections], ["Definitions", "AcceptanceTests"])
        self.assertEqual(len(doc.items), 3)
        child = doc.items[1]
        self.assertEqual(child.parent_item_id, doc.items[0].id)
        self.assertTrue(all(item.span.file_id == doc.files[0].id for item in doc.items))
        self.assertTrue(all(item.span.start_byte < item.span.end_byte for item in doc.items))
        facts = doc.facts()
        self.assertTrue(any(f[0] == "PlainFile" for f in facts))
        self.assertTrue(any(f[0] == "Section" and f[3] == "Definitions" for f in facts))
        self.assertTrue(any(f[0] == "PlainItem" and ":Task:" in f[5] for f in facts))
        self.assertTrue(any(f[0] == "SourceSpan" for f in facts))

    def test_multiline_bullet_continuations_extend_text_and_span_without_swallowing_children(self):
        text = (
            "***requirements***\n"
            "- The :Task: has a long rule\n"
            "  continuing on the next line.\n"
            "  - Acceptance: Given a :Task:, then it is visible.\n"
        )
        doc = index_source(text, "continuation.plain")

        self.assertEqual(len(doc.items), 2)
        parent, child = doc.items
        self.assertEqual(parent.raw_text, "The :Task: has a long rule\ncontinuing on the next line.")
        self.assertEqual(child.parent_item_id, parent.id)
        self.assertEqual(text[parent.span.start_byte:parent.span.end_byte], "- The :Task: has a long rule\n  continuing on the next line.\n")
        self.assertEqual(parent.span.end_line, 3)

    def test_source_spans_are_utf8_byte_offsets_after_non_ascii_text(self):
        text = (
            "***définitions***\n"
            "- :Café: is reviewable. Evidence: docs/café.md\n"
        )
        doc = index_source(text, "unicode.plain")
        source_bytes = text.encode("utf-8")
        section = doc.sections[0]
        item = doc.items[0]

        self.assertEqual(
            source_bytes[section.span.start_byte:section.span.end_byte].decode("utf-8"),
            "***définitions***\n",
        )
        self.assertEqual(
            source_bytes[item.span.start_byte:item.span.end_byte].decode("utf-8"),
            "- :Café: is reviewable. Evidence: docs/café.md\n",
        )
        self.assertEqual(item.span.start_line, 2)
        self.assertEqual(item.span.end_line, 2)

        compiled = compile_source(text, "unicode.plain")
        concept_reference = next(
            obj for obj in compiled.objects
            if any(fact[0] == "ConceptReference" for fact in obj.facts)
        )
        occurrence_span = next(
            span for span in compiled.spans if span.id == concept_reference.source_span_id
        )
        self.assertEqual(
            source_bytes[occurrence_span.start_byte:occurrence_span.end_byte].decode("utf-8"),
            ":Café:",
        )
        evidence = next(
            obj for obj in compiled.objects
            if any(fact[0] == "EvidenceText" for fact in obj.facts)
        )
        evidence_span = next(
            span for span in compiled.spans if span.id == evidence.source_span_id
        )
        self.assertEqual(
            source_bytes[evidence_span.start_byte:evidence_span.end_byte].decode("utf-8"),
            "Evidence: docs/café.md",
        )

    def test_utf8_bom_does_not_hide_first_heading_or_shift_byte_spans(self):
        text = "\ufeff***definitions***\n- :Task: is work.\n"
        source_bytes = text.encode("utf-8")
        doc = index_source(text, "bom.plain")

        self.assertEqual([section.kind for section in doc.sections], ["Definitions"])
        self.assertEqual(len(doc.items), 1)
        self.assertEqual(
            source_bytes[
                doc.sections[0].span.start_byte:doc.sections[0].span.end_byte
            ].decode("utf-8"),
            "\ufeff***definitions***\n",
        )
        self.assertEqual(
            source_bytes[
                doc.items[0].span.start_byte:doc.items[0].span.end_byte
            ].decode("utf-8"),
            "- :Task: is work.\n",
        )
        self.assertEqual(doc.items[0].span.start_line, 2)

    def test_mixed_newline_styles_preserve_byte_slices_and_line_numbers(self):
        text = (
            "***definitions***\r"
            "- :Café: is work.\r\n"
            "***requirements***\n"
            "- Evidence: docs/café.md\r"
        )
        source_bytes = text.encode("utf-8")
        doc = index_source(text, "mixed-newlines.plain")

        self.assertEqual([section.span.start_line for section in doc.sections], [1, 3])
        self.assertEqual([item.span.start_line for item in doc.items], [2, 4])
        expected_slices = [
            "***definitions***\r",
            "***requirements***\n",
            "- :Café: is work.\r\n",
            "- Evidence: docs/café.md\r",
        ]
        actual_slices = [
            source_bytes[record.span.start_byte:record.span.end_byte].decode("utf-8")
            for record in [*doc.sections, *doc.items]
        ]
        self.assertEqual(actual_slices, expected_slices)

    def test_unicode_and_control_separators_remain_source_content(self):
        separators = ("\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")
        for ordinal, separator in enumerate(separators):
            with self.subTest(code_point=f"U+{ord(separator):04X}"):
                text = (
                    "***definitions***\n"
                    f"- :Task: includes alpha{separator}beta.\n"
                    "- :Result: is reviewable.\n"
                )
                source_bytes = text.encode("utf-8")
                doc = index_source(text, f"separator-{ordinal}.plain")

                self.assertEqual(len(doc.items), 2)
                self.assertEqual([item.span.start_line for item in doc.items], [2, 3])
                self.assertEqual(
                    doc.items[0].raw_text,
                    f":Task: includes alpha{separator}beta.",
                )
                self.assertEqual(
                    source_bytes[
                        doc.items[0].span.start_byte:doc.items[0].span.end_byte
                    ].decode("utf-8"),
                    f"- :Task: includes alpha{separator}beta.\n",
                )

    def test_semantic_marker_on_lone_cr_continuation_has_exact_span(self):
        text = (
            "***requirements***\r"
            "- Review the artifact\r"
            "  Evidence: docs/café.md\r"
        )
        source_bytes = text.encode("utf-8")
        doc = compile_source(text, "cr-continuation.plain")
        evidence = next(
            obj for obj in doc.objects
            if any(fact[0] == "EvidenceText" for fact in obj.facts)
        )
        evidence_span = next(
            span for span in doc.spans if span.id == evidence.source_span_id
        )

        self.assertEqual(
            source_bytes[
                evidence_span.start_byte:evidence_span.end_byte
            ].decode("utf-8"),
            "Evidence: docs/café.md",
        )
        self.assertEqual((evidence_span.start_line, evidence_span.end_line), (3, 3))


if __name__ == "__main__":
    unittest.main()

import unittest

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


if __name__ == "__main__":
    unittest.main()

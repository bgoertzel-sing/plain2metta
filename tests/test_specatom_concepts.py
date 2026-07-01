import unittest

from specatom_hs.passes import compile_source
from specatom_hs.schema import CheckStatus, Role, SemanticLevel


class ConceptPassTests(unittest.TestCase):
    def test_concept_table_distinguishes_defined_external_and_unresolved_refs(self):
        doc = compile_source(
            "***definitions***\n"
            "- :Task: is tracked work.\n"
            "***requirements***\n"
            "- The :Task: references :User: and [external:SUMO.Agent].\n",
            "concepts.plain",
        )

        concept_facts = [fact for obj in doc.objects for fact in obj.facts if fact[0] == "ConceptStatus"]
        self.assertIn(("ConceptStatus", "Task", "defined"), concept_facts)
        self.assertIn(("ConceptStatus", "SUMO.Agent", "external"), concept_facts)
        self.assertIn(("ConceptStatus", "User", "unresolved"), concept_facts)

        questions = [obj for obj in doc.objects if obj.role == Role.QUESTION_OBJECT]
        self.assertTrue(any(("UnresolvedConcept", q.id, "User") in q.facts for q in questions))

        checks = [c for c in doc.checks if c.property == "concept-reference-resolved"]
        self.assertTrue(any(c.target_id.endswith(":Task") and c.status == CheckStatus.PASS for c in checks))
        self.assertTrue(any(c.target_id.endswith(":SUMO.Agent") and c.status == CheckStatus.PASS for c in checks))
        self.assertTrue(any(c.target_id.endswith(":User") and c.status == CheckStatus.UNKNOWN for c in checks))

    def test_concept_objects_are_template_parsed_not_raw_text_only(self):
        doc = compile_source("***definitions***\n- :Task: is work.\n", "minimal.plain")
        task = next(obj for obj in doc.objects if ("ConceptName", obj.id, "Task") in obj.facts)
        self.assertEqual(task.role, Role.CONCEPT_OBJECT)
        self.assertEqual(task.semantic_level, SemanticLevel.TEMPLATE_PARSED)
        self.assertIsNotNone(task.source_span_id)

    def test_concept_reference_occurrences_have_exact_spans_and_targets(self):
        doc = compile_source(
            "***definitions***\n"
            "- :Task: is work.\n"
            "***requirements***\n"
            "- The :Task: belongs to :User:.\n",
            "occurrences.plain",
        )

        refs = [obj for obj in doc.objects if obj.role == Role.CONCEPT_REFERENCE_OBJECT]
        task_refs = [obj for obj in refs if ("ConceptReference", obj.id, "Task") in obj.facts]
        user_refs = [obj for obj in refs if ("ConceptReference", obj.id, "User") in obj.facts]
        self.assertTrue(any(("ConceptReferenceKind", obj.id, "definition") in obj.facts for obj in task_refs))
        self.assertTrue(any(("ConceptReferenceKind", obj.id, "reference") in obj.facts for obj in task_refs))
        self.assertEqual(len(user_refs), 1)

        span_by_id = {span.id: span for span in doc.spans}
        file_text = doc.files[0].text
        user_span = span_by_id[user_refs[0].source_span_id]
        self.assertEqual(file_text[user_span.start_byte:user_span.end_byte], ":User:")
        self.assertTrue(any(c.target_id == f"{user_refs[0].id}:User" and c.status == CheckStatus.UNKNOWN for c in doc.checks))

    def test_concept_aliases_and_bare_glossary_definitions_are_conservative(self):
        doc = compile_source(
            "***glossary***\n"
            "- Task: tracked work.\n"
            "- [concept:User] is an actor.\n"
            "***requirements***\n"
            "- A [ref:Task] belongs to [concept:User] and [def:Tag].\n",
            "aliases.plain",
        )

        concept_facts = [fact for obj in doc.objects for fact in obj.facts if fact[0] == "ConceptStatus"]
        self.assertIn(("ConceptStatus", "Task", "defined"), concept_facts)
        self.assertIn(("ConceptStatus", "User", "defined"), concept_facts)
        self.assertIn(("ConceptStatus", "Tag", "defined"), concept_facts)

        refs = [obj for obj in doc.objects if obj.role == Role.CONCEPT_REFERENCE_OBJECT]
        span_by_id = {span.id: span for span in doc.spans}
        file_text = doc.files[0].text
        task_ref = next(obj for obj in refs if ("ConceptReference", obj.id, "Task") in obj.facts and ("ConceptReferenceKind", obj.id, "reference") in obj.facts)
        tag_def = next(obj for obj in refs if ("ConceptReference", obj.id, "Tag") in obj.facts and ("ConceptReferenceKind", obj.id, "definition") in obj.facts)
        self.assertEqual(file_text[span_by_id[task_ref.source_span_id].start_byte:span_by_id[task_ref.source_span_id].end_byte], "[ref:Task]")
        self.assertEqual(file_text[span_by_id[tag_def.source_span_id].start_byte:span_by_id[tag_def.source_span_id].end_byte], "[def:Tag]")
        self.assertFalse(any(c.property == "concept-reference-resolved" and c.status == CheckStatus.UNKNOWN for c in doc.checks))


if __name__ == "__main__":
    unittest.main()

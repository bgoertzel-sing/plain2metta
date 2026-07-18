import unittest

from specatom_hs.passes import compile_source
from specatom_hs.schema import CheckRecord, CheckStatus, PlainFile, PlainItem, Role, Section, SemanticLevel, SourceSpan, SpecDocument, SpecObject, ValidationObligation
from specatom_hs.validators import add_check, add_validation_obligation


class ValidationRecordTests(unittest.TestCase):
    def test_validation_obligation_and_check_records_are_first_class(self):
        doc = compile_source("***definitions***\n- :Task: is work.\n", "minimal.plain")
        self.assertTrue(doc.validation_obligations)
        self.assertTrue(doc.checks)
        self.assertTrue(any(o.property == "item-has-source-span" for o in doc.validation_obligations))
        self.assertTrue(any(c.status == CheckStatus.PASS for c in doc.checks))
        facts = doc.facts()
        self.assertTrue(any(f[0] == "ValidationObligation" for f in facts))
        self.assertTrue(any(f[0] == "CheckStatus" for f in facts))

    def test_manual_unknown_check_record(self):
        doc = compile_source("***definitions***\n- :Task: is work.\n", "minimal.plain")
        target = doc.items[0].id
        obligation = add_validation_obligation(doc, "test-coverage", target, "Acceptance coverage is not yet known.", doc.items[0].span.id)
        check = add_check(doc, obligation, CheckStatus.UNKNOWN, "no acceptance-test pass implemented")
        self.assertEqual(check.property, "test-coverage")
        self.assertEqual(check.status, CheckStatus.UNKNOWN)

    def test_fact_arity_and_reference_obligations_are_emitted(self):
        doc = compile_source(
            "***requirements***\n"
            "- The [def:Task] must be visible.\n"
            "***acceptance tests***\n"
            "- Given a [ref:Task], then it is visible.\n",
            "facts.plain",
        )
        self.assertTrue(any(c.property == "fact-has-supported-arity" and c.status == CheckStatus.PASS for c in doc.checks))
        self.assertTrue(any(c.property == "fact-references-known-targets" and c.status == CheckStatus.PASS for c in doc.checks))

    def test_fact_validator_fails_bad_arity_dangling_reference_and_subject_mismatch(self):
        doc = SpecDocument(
            objects=[
                SpecObject(
                    "obj-bad",
                    Role.VALIDATION_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    None,
                    facts=[("Covers", "obj-bad"), ("Covers", "other-test", "missing-req")],
                )
            ]
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)
        self.assertTrue(
            any(c.property == "fact-has-supported-arity" and c.status == CheckStatus.FAIL and "expected arity 3" in c.evidence for c in doc.checks)
        )
        self.assertTrue(
            any(c.property == "fact-references-known-targets" and c.status == CheckStatus.FAIL and "missing-req" in c.evidence for c in doc.checks)
        )
        self.assertTrue(
            any(c.property == "fact-subject-matches-object" and c.status == CheckStatus.FAIL and "other-test" in c.evidence for c in doc.checks)
        )

    def test_unknown_fact_predicate_creates_profile_question(self):
        doc = SpecDocument(
            objects=[
                SpecObject(
                    "obj-unknown",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    None,
                    facts=[("InventedExecutable", "obj-unknown", "run")],
                )
            ]
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)
        self.assertTrue(
            any(c.property == "fact-has-supported-arity" and c.status == CheckStatus.UNKNOWN and "InventedExecutable" in c.evidence for c in doc.checks)
        )
        question_facts = [fact for obj in doc.objects if obj.role == Role.QUESTION_OBJECT for fact in obj.facts]
        self.assertIn(("UnsupportedFactPredicate", next(obj.id for obj in doc.objects if obj.role == Role.QUESTION_OBJECT), "InventedExecutable"), question_facts)
        self.assertTrue(any(fact[0] == "Blocks" and fact[2].startswith("vobl-") for fact in question_facts))

    def test_petta_reified_profile_level_obligations_create_refusal_questions(self):
        doc = SpecDocument(
            objects=[
                SpecObject("obj-raw", Role.SOURCE_OBJECT, SemanticLevel.RAW_TEXT_ONLY, None),
                SpecObject("obj-template", Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, None),
            ]
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)
        self.assertTrue(
            any(
                c.property == "object-supported-by-petta-reified-profile"
                and c.target_id == "obj-template"
                and c.status == CheckStatus.PASS
                for c in doc.checks
            )
        )
        self.assertTrue(
            any(
                c.property == "object-supported-by-petta-reified-profile"
                and c.target_id == "obj-raw"
                and c.status == CheckStatus.UNKNOWN
                and "RawTextOnly" in c.evidence
                for c in doc.checks
            )
        )
        question_facts = [fact for obj in doc.objects if obj.role == Role.QUESTION_OBJECT for fact in obj.facts]
        self.assertTrue(any(fact[0] == "UnsupportedSemanticLevel" and fact[2] == "RawTextOnly" for fact in question_facts))
        self.assertTrue(any(fact[0] == "Blocks" and fact[2].startswith("vobl-") for fact in question_facts))

    def test_plain_file_digest_validation_recomputes_preserved_source_text(self):
        doc = compile_source("***requirements***\n- The system stores [def:Task].\n", "digest.plain")
        self.assertTrue(
            any(c.property == "plain-file-digest-matches-content" and c.status == CheckStatus.PASS for c in doc.checks)
        )

        bad = SpecDocument(files=[PlainFile("file-1", "bad.plain", "sha256:not-the-content", "preserved text\n")])
        from specatom_hs.validators import validate_document

        validate_document(bad)
        self.assertTrue(
            any(
                c.property == "plain-file-digest-matches-content"
                and c.target_id == "file-1"
                and c.status == CheckStatus.FAIL
                and "sha256:not-the-content" in c.evidence
                for c in bad.checks
            )
        )

    def test_source_span_validator_checks_bounds_and_line_numbers(self):
        doc = compile_source("***requirements***\n- The system stores [def:Task].\n", "spans.plain")
        self.assertTrue(
            any(c.property == "source-span-within-file-bounds" and c.status == CheckStatus.PASS for c in doc.checks)
        )
        self.assertTrue(
            any(c.property == "source-span-lines-match-byte-offsets" and c.status == CheckStatus.PASS for c in doc.checks)
        )

        bad = SpecDocument(
            files=[PlainFile("file-1", "bad.plain", "sha256:test", "first\nsecond\n")],
            spans=[
                SourceSpan("span-oob", "file-1", 0, 999, 1, 1),
                SourceSpan("span-bad-line", "file-1", 6, 12, 1, 1),
                SourceSpan("span-missing-file", "file-missing", 0, 1, 1, 1),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(bad)
        self.assertTrue(
            any(c.property == "source-span-within-file-bounds" and c.target_id == "span-oob" and c.status == CheckStatus.FAIL for c in bad.checks)
        )
        self.assertTrue(
            any(c.property == "source-span-lines-match-byte-offsets" and c.target_id == "span-bad-line" and c.status == CheckStatus.FAIL and "expected=2:2" in c.evidence for c in bad.checks)
        )
        self.assertTrue(
            any(c.property == "source-span-within-file-bounds" and c.target_id == "span-missing-file" and c.status == CheckStatus.FAIL and "file-missing" in c.evidence for c in bad.checks)
        )

    def test_section_and_item_file_provenance_is_validated(self):
        doc = compile_source("***requirements***\n- The system stores [def:Task].\n", "file-links.plain")
        self.assertTrue(
            any(c.property == "section-file-is-indexed" and c.status == CheckStatus.PASS for c in doc.checks)
        )
        self.assertTrue(
            any(c.property == "section-has-source-span" and c.status == CheckStatus.PASS for c in doc.checks)
        )
        self.assertTrue(
            any(c.property == "section-span-file-matches-section-file" and c.status == CheckStatus.PASS for c in doc.checks)
        )
        self.assertTrue(
            any(c.property == "item-file-is-indexed" and c.status == CheckStatus.PASS for c in doc.checks)
        )
        self.assertTrue(
            any(c.property == "item-file-matches-section-file" and c.status == CheckStatus.PASS for c in doc.checks)
        )
        self.assertTrue(
            any(c.property == "item-span-file-matches-item-file" and c.status == CheckStatus.PASS for c in doc.checks)
        )

        span = SourceSpan("span-1", "file-1", 0, 4, 1, 1)
        bad = SpecDocument(
            files=[PlainFile("file-1", "bad.plain", "sha256:test", "text")],
            spans=[span],
            sections=[Section("section-bad", "file-missing", "Bad", "Bad", 1, span)],
            items=[PlainItem("item-bad", "file-missing", "section-bad", None, 1, 0, "text", span)],
        )
        from specatom_hs.validators import validate_document

        validate_document(bad)
        self.assertTrue(
            any(c.property == "section-file-is-indexed" and c.target_id == "section-bad" and c.status == CheckStatus.FAIL and "file-missing" in c.evidence for c in bad.checks)
        )
        self.assertTrue(
            any(c.property == "item-file-is-indexed" and c.target_id == "item-bad" and c.status == CheckStatus.FAIL and "file-missing" in c.evidence for c in bad.checks)
        )
        self.assertTrue(
            any(
                c.property == "section-span-file-matches-section-file"
                and c.target_id == "section-bad"
                and c.status == CheckStatus.FAIL
                and "span.file_id=file-1" in c.evidence
                for c in bad.checks
            )
        )
        self.assertTrue(
            any(
                c.property == "item-span-file-matches-item-file"
                and c.target_id == "item-bad"
                and c.status == CheckStatus.FAIL
                and "span.file_id=file-1" in c.evidence
                for c in bad.checks
            )
        )

        section = Section("section-1", "file-1", "Good", "Good", 1, span)
        mismatched = SpecDocument(
            files=[PlainFile("file-1", "bad.plain", "sha256:test", "text")],
            spans=[span],
            sections=[section],
            items=[PlainItem("item-mismatched", "file-other", "section-1", None, 1, 0, "text", span)],
        )
        validate_document(mismatched)
        self.assertTrue(
            any(
                c.property == "item-file-matches-section-file"
                and c.target_id == "item-mismatched"
                and c.status == CheckStatus.FAIL
                and "section.file_id=file-1" in c.evidence
                for c in mismatched.checks
            )
        )

    def test_section_file_validation_uses_canonical_indexed_span(self):
        indexed_span = SourceSpan("span-shared", "file-other", 0, 4, 1, 1)
        masked_span = SourceSpan("span-shared", "file-section", 0, 4, 1, 1)
        doc = SpecDocument(
            files=[
                PlainFile("file-section", "section.plain", "digest-section", "text"),
                PlainFile("file-other", "other.plain", "digest-other", "text"),
            ],
            spans=[indexed_span],
            sections=[
                Section(
                    "section-masked-mismatch",
                    "file-section",
                    "Masked mismatch",
                    "definitions",
                    0,
                    masked_span,
                )
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        checks = [
            check
            for check in doc.checks
            if check.property == "section-span-file-matches-section-file"
            and check.target_id == "section-masked-mismatch"
        ]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].status, CheckStatus.FAIL)
        self.assertEqual(
            checks[0].evidence,
            "section.file_id=file-section span.file_id=file-other",
        )

    def test_validation_obligations_validate_source_and_target_provenance(self):
        doc = compile_source("***requirements***\n- The system stores [def:Task].\n", "obligations.plain")
        self.assertTrue(
            any(c.property == "obligation-has-source-provenance" and c.status == CheckStatus.PASS for c in doc.checks)
        )
        self.assertTrue(
            any(c.property == "obligation-target-is-declared" and c.status == CheckStatus.PASS for c in doc.checks)
        )

        bad = SpecDocument(
            validation_obligations=[
                ValidationObligation("vobl-bad", "synthetic-property", "missing-target", "bad provenance", "span-missing")
            ]
        )
        from specatom_hs.validators import validate_document

        validate_document(bad)
        self.assertTrue(
            any(c.property == "obligation-has-source-provenance" and c.status == CheckStatus.FAIL and "span-missing" in c.evidence for c in bad.checks)
        )
        self.assertTrue(
            any(c.property == "obligation-target-is-declared" and c.status == CheckStatus.FAIL and "missing-target" in c.evidence for c in bad.checks)
        )

    def test_question_objects_validate_review_text_and_blocked_obligations(self):
        doc = compile_source("***requirements***\n- The system mentions [ref:GhostConcept].\n", "question-links.plain")
        unresolved_questions = [obj for obj in doc.objects if obj.role == Role.QUESTION_OBJECT and any(fact[0] == "UnresolvedConcept" for fact in obj.facts)]
        self.assertTrue(unresolved_questions)
        self.assertTrue(any(fact[0] == "Blocks" and fact[2].startswith("vobl-") for fact in unresolved_questions[0].facts))
        self.assertTrue(
            any(c.property == "question-has-review-text" and c.target_id == unresolved_questions[0].id and c.status == CheckStatus.PASS for c in doc.checks)
        )
        self.assertTrue(
            any(c.property == "question-blocks-validation-obligation" and c.target_id == unresolved_questions[0].id and c.status == CheckStatus.PASS for c in doc.checks)
        )

        bad = SpecDocument(
            objects=[
                SpecObject("question-empty", Role.QUESTION_OBJECT, SemanticLevel.TEMPLATE_PARSED, None, facts=[("QuestionText", "question-empty", "   ")]),
                SpecObject("question-dangling", Role.QUESTION_OBJECT, SemanticLevel.TEMPLATE_PARSED, None, facts=[("QuestionText", "question-dangling", "Review me."), ("Blocks", "question-dangling", "vobl-missing")]),
            ]
        )
        from specatom_hs.validators import validate_document

        validate_document(bad)
        self.assertTrue(
            any(c.property == "question-has-review-text" and c.target_id == "question-empty" and c.status == CheckStatus.FAIL for c in bad.checks)
        )
        self.assertTrue(
            any(c.property == "question-blocks-validation-obligation" and c.target_id == "question-empty" and c.status == CheckStatus.FAIL and "missing Blocks" in c.evidence for c in bad.checks)
        )
        self.assertTrue(
            any(c.property == "question-blocks-validation-obligation" and c.target_id == "question-dangling" and c.status == CheckStatus.FAIL and "vobl-missing" in c.evidence for c in bad.checks)
        )

    def test_check_records_validate_their_obligation_links_targets_and_statuses(self):
        doc = SpecDocument(
            objects=[SpecObject("target-a", Role.SOURCE_OBJECT, SemanticLevel.RAW_TEXT_ONLY, None)],
            validation_obligations=[
                ValidationObligation("vobl-known", "example-property", "target-a", "synthetic obligation")
            ],
            checks=[
                CheckRecord("chk-good", "vobl-known", "example-property", "target-a", CheckStatus.PASS, "synthetic pass"),
                CheckRecord("chk-mismatch", "vobl-known", "example-property", "target-b", CheckStatus.PASS, "bad target"),
                CheckRecord("chk-missing", "vobl-missing", "example-property", "target-a", CheckStatus.UNKNOWN, "missing link"),
                CheckRecord("chk-bad-status", "vobl-known", "example-property", "target-a", "Definitely", "bad status"),
                CheckRecord("chk-empty-evidence", "vobl-known", "example-property", "target-a", CheckStatus.FAIL, "   "),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)
        self.assertTrue(
            any(c.property == "check-links-known-obligation" and c.target_id == "chk-good" and c.status == CheckStatus.PASS for c in doc.checks)
        )
        self.assertTrue(
            any(c.property == "check-target-matches-obligation" and c.target_id == "chk-mismatch" and c.status == CheckStatus.FAIL and "target-b" in c.evidence for c in doc.checks)
        )
        self.assertTrue(
            any(c.property == "check-links-known-obligation" and c.target_id == "chk-missing" and c.status == CheckStatus.FAIL and "vobl-missing" in c.evidence for c in doc.checks)
        )
        self.assertTrue(
            any(c.property == "check-status-is-known" and c.target_id == "chk-bad-status" and c.status == CheckStatus.FAIL and "Definitely" in c.evidence for c in doc.checks)
        )
        self.assertTrue(
            any(c.property == "check-has-evidence" and c.target_id == "chk-good" and c.status == CheckStatus.PASS for c in doc.checks)
        )
        self.assertTrue(
            any(c.property == "check-has-evidence" and c.target_id == "chk-empty-evidence" and c.status == CheckStatus.FAIL and "empty" in c.evidence for c in doc.checks)
        )


if __name__ == "__main__":
    unittest.main()

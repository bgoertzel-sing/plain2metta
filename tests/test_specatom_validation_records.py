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

    def test_item_file_validation_uses_canonical_indexed_span(self):
        indexed_span = SourceSpan("span-shared", "file-other", 0, 4, 1, 1)
        masked_span = SourceSpan("span-shared", "file-item", 0, 4, 1, 1)
        section_span = SourceSpan("span-section", "file-item", 0, 4, 1, 1)
        doc = SpecDocument(
            files=[
                PlainFile("file-item", "item.plain", "digest-item", "text"),
                PlainFile("file-other", "other.plain", "digest-other", "text"),
            ],
            spans=[indexed_span, section_span],
            sections=[
                Section(
                    "section-item",
                    "file-item",
                    "Items",
                    "requirements",
                    0,
                    section_span,
                )
            ],
            items=[
                PlainItem(
                    "item-masked-mismatch",
                    "file-item",
                    "section-item",
                    None,
                    0,
                    0,
                    "text",
                    masked_span,
                )
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        checks = [
            check
            for check in doc.checks
            if check.property == "item-span-file-matches-item-file"
            and check.target_id == "item-masked-mismatch"
        ]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].status, CheckStatus.FAIL)
        self.assertEqual(
            checks[0].evidence,
            "item.file_id=file-item span.file_id=file-other",
        )

    def test_section_and_item_file_validation_refuse_duplicate_indexed_span_ids(self):
        duplicate_other = SourceSpan("span-duplicate", "file-other", 0, 4, 1, 1)
        duplicate_matching = SourceSpan("span-duplicate", "file-main", 0, 4, 1, 1)
        doc = SpecDocument(
            files=[
                PlainFile("file-main", "main.plain", "digest-main", "text"),
                PlainFile("file-other", "other.plain", "digest-other", "text"),
            ],
            spans=[duplicate_other, duplicate_matching],
            sections=[
                Section("section-main", "file-main", "Main", "requirements", 0, duplicate_matching)
            ],
            items=[
                PlainItem("item-main", "file-main", "section-main", None, 0, 0, "text", duplicate_matching)
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        for property_name, target_id in (
            ("section-has-source-span", "section-main"),
            ("section-span-file-matches-section-file", "section-main"),
            ("item-has-source-span", "item-main"),
            ("item-span-file-matches-item-file", "item-main"),
        ):
            checks = [
                check
                for check in doc.checks
                if check.property == property_name and check.target_id == target_id
            ]
            self.assertEqual(len(checks), 1)
            self.assertEqual(checks[0].status, CheckStatus.FAIL)
            self.assertEqual(
                checks[0].evidence,
                "ambiguous duplicate span=span-duplicate count=2",
            )

    def test_item_validation_refuses_duplicate_indexed_section_ids(self):
        span = SourceSpan("span-main", "file-main", 0, 4, 1, 1)
        doc = SpecDocument(
            files=[PlainFile("file-main", "main.plain", "digest-main", "text")],
            spans=[span],
            sections=[
                Section("section-duplicate", "file-other", "Other", "requirements", 0, span),
                Section("section-duplicate", "file-main", "Main", "requirements", 1, span),
            ],
            items=[
                PlainItem("item-main", "file-main", "section-duplicate", None, 0, 0, "text", span)
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        for property_name in ("item-has-section", "item-file-matches-section-file"):
            checks = [
                check
                for check in doc.checks
                if check.property == property_name and check.target_id == "item-main"
            ]
            self.assertEqual(len(checks), 1)
            self.assertEqual(checks[0].status, CheckStatus.FAIL)
            self.assertEqual(
                checks[0].evidence,
                "ambiguous duplicate section=section-duplicate count=2",
            )

    def test_section_and_item_identity_validation_refuses_duplicates(self):
        span = SourceSpan("span-main", "file-main", 0, 4, 1, 1)
        doc = SpecDocument(
            files=[PlainFile("file-main", "main.plain", "digest-main", "text")],
            spans=[span],
            sections=[
                Section("section-duplicate", "file-main", "First", "requirements", 0, span),
                Section("section-duplicate", "file-main", "Second", "requirements", 1, span),
            ],
            items=[
                PlainItem("item-duplicate", "file-main", "section-duplicate", None, 0, 0, "first", span),
                PlainItem("item-duplicate", "file-main", "section-duplicate", None, 1, 0, "second", span),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        for property_name, target_id, evidence in (
            (
                "section-identity-is-unique",
                "section-duplicate",
                "ambiguous duplicate section=section-duplicate count=2",
            ),
            (
                "item-identity-is-unique",
                "item-duplicate",
                "ambiguous duplicate item=item-duplicate count=2",
            ),
        ):
            checks = [
                check
                for check in doc.checks
                if check.property == property_name and check.target_id == target_id
            ]
            self.assertEqual(len(checks), 1)
            self.assertEqual(checks[0].status, CheckStatus.FAIL)
            self.assertEqual(checks[0].evidence, evidence)

    def test_object_identity_validation_refuses_duplicates(self):
        doc = SpecDocument(
            objects=[
                SpecObject("object-duplicate", Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, None),
                SpecObject("object-duplicate", Role.VALIDATION_OBJECT, SemanticLevel.VERIFIED, None),
                SpecObject("object-unique", Role.QUESTION_OBJECT, SemanticLevel.TEMPLATE_PARSED, None),
            ]
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        duplicate_checks = [
            check
            for check in doc.checks
            if check.property == "object-identity-is-unique"
            and check.target_id == "object-duplicate"
        ]
        self.assertEqual(len(duplicate_checks), 1)
        self.assertEqual(duplicate_checks[0].status, CheckStatus.FAIL)
        self.assertEqual(
            duplicate_checks[0].evidence,
            "ambiguous duplicate object=object-duplicate count=2",
        )

        unique_checks = [
            check
            for check in doc.checks
            if check.property == "object-identity-is-unique"
            and check.target_id == "object-unique"
        ]
        self.assertEqual(len(unique_checks), 1)
        self.assertEqual(unique_checks[0].status, CheckStatus.PASS)
        self.assertEqual(unique_checks[0].evidence, "object=object-unique")

    def test_object_semantic_level_validation_refuses_unsupported_value_without_crashing(self):
        doc = SpecDocument(
            objects=[
                SpecObject(
                    "object-unsupported-level",
                    Role.REQUIREMENT_OBJECT,
                    "UnsupportedLevel",  # type: ignore[arg-type]
                    None,
                )
            ]
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        checks = [
            check
            for check in doc.checks
            if check.property == "object-has-known-semantic-level"
            and check.target_id == "object-unsupported-level"
        ]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].status, CheckStatus.FAIL)
        self.assertEqual(
            checks[0].evidence,
            "unsupported semantic level='UnsupportedLevel'",
        )

    def test_validation_layer_identity_validation_refuses_duplicates(self):
        obligation = ValidationObligation(
            "obligation-duplicate", "property", "target", "rationale"
        )
        check = CheckRecord(
            "check-duplicate",
            obligation.id,
            obligation.property,
            obligation.target_id,
            CheckStatus.PASS,
            "evidence",
        )
        doc = SpecDocument(
            validation_obligations=[obligation, obligation],
            checks=[check, check],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        expected = (
            (
                "validation-obligation-identity-is-unique",
                "obligation-duplicate",
                "ambiguous duplicate validation obligation=obligation-duplicate count=2",
            ),
            (
                "check-identity-is-unique",
                "check-duplicate",
                "ambiguous duplicate check=check-duplicate count=2",
            ),
        )
        for property_name, target_id, evidence in expected:
            checks = [
                record
                for record in doc.checks
                if record.property == property_name and record.target_id == target_id
            ]
            self.assertEqual(len(checks), 1)
            self.assertEqual(checks[0].status, CheckStatus.FAIL)
            self.assertEqual(checks[0].evidence, evidence)

    def test_source_links_refuse_duplicate_indexed_file_ids(self):
        span = SourceSpan("span-main", "file-duplicate", 0, 4, 1, 1)
        doc = SpecDocument(
            files=[
                PlainFile("file-duplicate", "other.plain", "digest-other", "nope"),
                PlainFile("file-duplicate", "main.plain", "digest-main", "text"),
            ],
            spans=[span],
            sections=[
                Section("section-main", "file-duplicate", "Main", "requirements", 0, span)
            ],
            items=[
                PlainItem("item-main", "file-duplicate", "section-main", None, 0, 0, "text", span)
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        for property_name, target_id in (
            ("source-span-within-file-bounds", "span-main"),
            ("section-file-is-indexed", "section-main"),
            ("item-file-is-indexed", "item-main"),
        ):
            checks = [
                check
                for check in doc.checks
                if check.property == property_name and check.target_id == target_id
            ]
            self.assertEqual(len(checks), 1)
            self.assertEqual(checks[0].status, CheckStatus.FAIL)
            self.assertEqual(
                checks[0].evidence,
                "ambiguous duplicate file=file-duplicate count=2",
            )

    def test_file_and_source_span_identity_validation_refuses_duplicates(self):
        duplicate_span_first = SourceSpan("span-duplicate", "file-duplicate", 0, 2, 1, 1)
        duplicate_span_second = SourceSpan("span-duplicate", "file-duplicate", 2, 4, 1, 1)
        doc = SpecDocument(
            files=[
                PlainFile("file-duplicate", "first.plain", "digest-first", "text"),
                PlainFile("file-duplicate", "second.plain", "digest-second", "text"),
            ],
            spans=[duplicate_span_first, duplicate_span_second],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        for property_name, target_id, evidence in (
            (
                "plain-file-identity-is-unique",
                "file-duplicate",
                "ambiguous duplicate file=file-duplicate count=2",
            ),
            (
                "source-span-identity-is-unique",
                "span-duplicate",
                "ambiguous duplicate span=span-duplicate count=2",
            ),
        ):
            checks = [
                check
                for check in doc.checks
                if check.property == property_name and check.target_id == target_id
            ]
            self.assertEqual(len(checks), 1)
            self.assertEqual(checks[0].status, CheckStatus.FAIL)
            self.assertEqual(checks[0].evidence, evidence)

    def test_item_parent_validation_fails_closed(self):
        span = SourceSpan("span-main", "file-main", 0, 4, 1, 1)
        other_span = SourceSpan("span-other", "file-other", 0, 4, 1, 1)
        doc = SpecDocument(
            files=[
                PlainFile("file-main", "main.plain", "digest-main", "text"),
                PlainFile("file-other", "other.plain", "digest-other", "text"),
            ],
            spans=[span, other_span],
            sections=[Section("section-main", "file-main", "Main", "requirements", 0, span)],
            items=[
                PlainItem("parent-duplicate", "file-main", "section-main", None, 0, 0, "first", span),
                PlainItem("parent-duplicate", "file-main", "section-main", None, 1, 0, "second", span),
                PlainItem("child-ambiguous", "file-main", "section-main", "parent-duplicate", 2, 1, "child", span),
                PlainItem("child-missing", "file-main", "section-main", "parent-missing", 3, 1, "child", span),
                PlainItem("child-self", "file-main", "section-main", "child-self", 4, 1, "child", span),
                PlainItem("parent-other", "file-other", "section-other", None, 0, 0, "parent", other_span),
                PlainItem("child-cross-context", "file-main", "section-main", "parent-other", 5, 1, "child", span),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        expected = {
            ("item-parent-is-indexed", "child-ambiguous"): (CheckStatus.FAIL, "ambiguous duplicate item=parent-duplicate count=2"),
            ("item-parent-is-indexed", "child-missing"): (CheckStatus.FAIL, "parent_item=parent-missing"),
            ("item-parent-is-not-self", "child-self"): (CheckStatus.FAIL, "item=child-self parent_item=child-self"),
            ("item-parent-context-matches", "child-cross-context"): (
                CheckStatus.FAIL,
                "item.file_id=file-main item.section_id=section-main parent.file_id=file-other parent.section_id=section-other",
            ),
        }
        for key, ground_truth in expected.items():
            matches = [c for c in doc.checks if (c.property, c.target_id) == key]
            self.assertEqual(len(matches), 1)
            self.assertEqual((matches[0].status, matches[0].evidence), ground_truth)

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

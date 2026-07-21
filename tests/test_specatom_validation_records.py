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

    def test_check_evidence_validation_refuses_non_string_values(self):
        obligation = ValidationObligation("obligation-1", "reviewed", "target-1", "Review target.")
        doc = SpecDocument(
            validation_obligations=[obligation],
            checks=[
                CheckRecord("check-none", obligation.id, obligation.property, obligation.target_id, CheckStatus.UNKNOWN, None),
                CheckRecord("check-list", obligation.id, obligation.property, obligation.target_id, CheckStatus.UNKNOWN, ["unsafe"]),
                CheckRecord("check-valid", obligation.id, obligation.property, obligation.target_id, CheckStatus.PASS, "reviewed"),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            (record.status, record.evidence)
            for record in doc.checks
            if record.property == "check-has-evidence"
            and record.target_id in {"check-none", "check-list", "check-valid"}
        ]
        self.assertEqual(
            records,
            [
                (CheckStatus.FAIL, "unsupported check evidence=None type=NoneType"),
                (CheckStatus.FAIL, "unsupported check evidence=['unsafe'] type=list"),
                (CheckStatus.PASS, "evidence present"),
            ],
        )

    def test_check_obligation_identity_validation_refuses_non_string_values(self):
        obligation = ValidationObligation("obligation-1", "reviewed", "target-1", "Review target.")
        doc = SpecDocument(
            validation_obligations=[obligation],
            checks=[
                CheckRecord("check-none", None, obligation.property, obligation.target_id, CheckStatus.UNKNOWN, "review"),
                CheckRecord("check-list", ["unsafe"], obligation.property, obligation.target_id, CheckStatus.UNKNOWN, "review"),
                CheckRecord("check-blank", "   ", obligation.property, obligation.target_id, CheckStatus.UNKNOWN, "review"),
                CheckRecord("check-valid", obligation.id, obligation.property, obligation.target_id, CheckStatus.PASS, "reviewed"),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            (record.status, record.evidence)
            for record in doc.checks
            if record.property == "check-has-safe-obligation-id"
            and record.target_id.startswith("check-")
        ]
        self.assertEqual(
            records,
            [
                (CheckStatus.FAIL, "unsupported check obligation identity=None type=NoneType"),
                (CheckStatus.FAIL, "unsupported check obligation identity=['unsafe'] type=list"),
                (CheckStatus.FAIL, "empty check obligation identity"),
                (CheckStatus.PASS, "obligation=obligation-1"),
            ],
        )

    def test_check_property_validation_refuses_non_string_values(self):
        obligation = ValidationObligation("obligation-1", "reviewed", "target-1", "Review target.")
        doc = SpecDocument(
            validation_obligations=[obligation],
            checks=[
                CheckRecord("check-none", obligation.id, None, obligation.target_id, CheckStatus.UNKNOWN, "review"),
                CheckRecord("check-list", obligation.id, ["unsafe"], obligation.target_id, CheckStatus.UNKNOWN, "review"),
                CheckRecord("check-blank", obligation.id, "   ", obligation.target_id, CheckStatus.UNKNOWN, "review"),
                CheckRecord("check-valid", obligation.id, obligation.property, obligation.target_id, CheckStatus.PASS, "reviewed"),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            (record.status, record.evidence)
            for record in doc.checks
            if record.property == "check-has-safe-property"
            and record.target_id.startswith("check-")
        ]
        self.assertEqual(
            records,
            [
                (CheckStatus.FAIL, "unsupported check property=None type=NoneType"),
                (CheckStatus.FAIL, "unsupported check property=['unsafe'] type=list"),
                (CheckStatus.FAIL, "empty check property"),
                (CheckStatus.PASS, "property=reviewed"),
            ],
        )

    def test_check_target_validation_refuses_non_string_values(self):
        obligation = ValidationObligation("obligation-1", "reviewed", "target-1", "Review target.")
        doc = SpecDocument(
            validation_obligations=[obligation],
            checks=[
                CheckRecord("check-none", obligation.id, obligation.property, None, CheckStatus.UNKNOWN, "review"),
                CheckRecord("check-list", obligation.id, obligation.property, ["unsafe"], CheckStatus.UNKNOWN, "review"),
                CheckRecord("check-blank", obligation.id, obligation.property, "   ", CheckStatus.UNKNOWN, "review"),
                CheckRecord("check-valid", obligation.id, obligation.property, obligation.target_id, CheckStatus.PASS, "reviewed"),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            (record.status, record.evidence)
            for record in doc.checks
            if record.property == "check-has-safe-target"
            and record.target_id.startswith("check-")
        ]
        self.assertEqual(
            records,
            [
                (CheckStatus.FAIL, "unsupported check target=None type=NoneType"),
                (CheckStatus.FAIL, "unsupported check target=['unsafe'] type=list"),
                (CheckStatus.FAIL, "empty check target"),
                (CheckStatus.PASS, "target=target-1"),
            ],
        )

    def test_check_status_validation_reports_exact_unsupported_types(self):
        obligation = ValidationObligation("obligation-1", "reviewed", "target-1", "Review target.")
        doc = SpecDocument(
            validation_obligations=[obligation],
            checks=[
                CheckRecord("check-none", obligation.id, obligation.property, obligation.target_id, None, "review"),
                CheckRecord("check-string", obligation.id, obligation.property, obligation.target_id, "Pass", "review"),
                CheckRecord("check-list", obligation.id, obligation.property, obligation.target_id, ["Pass"], "review"),
                CheckRecord("check-valid", obligation.id, obligation.property, obligation.target_id, CheckStatus.PASS, "reviewed"),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            (record.status, record.evidence)
            for record in doc.checks
            if record.property == "check-status-is-known"
            and record.target_id.startswith("check-")
        ]
        self.assertEqual(
            records,
            [
                (CheckStatus.FAIL, "unsupported check status=None type=NoneType"),
                (CheckStatus.FAIL, "unsupported check status='Pass' type=str"),
                (CheckStatus.FAIL, "unsupported check status=['Pass'] type=list"),
                (CheckStatus.PASS, "status=Pass"),
            ],
        )

    def test_validation_obligation_rationale_validation_refuses_non_string_values(self):
        doc = SpecDocument(
            validation_obligations=[
                ValidationObligation("obligation-none", "reviewed", "target-none", None),
                ValidationObligation("obligation-list", "reviewed", "target-list", ["unsafe"]),
                ValidationObligation("obligation-blank", "reviewed", "target-blank", "   "),
                ValidationObligation("obligation-valid", "reviewed", "target-valid", "Review target."),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            (record.status, record.evidence)
            for record in doc.checks
            if record.property == "validation-obligation-has-reviewable-rationale"
            and record.target_id.startswith("obligation-")
        ]
        self.assertEqual(
            records,
            [
                (CheckStatus.FAIL, "unsupported validation obligation rationale=None type=NoneType"),
                (CheckStatus.FAIL, "unsupported validation obligation rationale=['unsafe'] type=list"),
                (CheckStatus.FAIL, "empty validation obligation rationale"),
                (CheckStatus.PASS, "rationale present"),
            ],
        )

    def test_validation_obligation_property_validation_refuses_non_string_values(self):
        doc = SpecDocument(
            validation_obligations=[
                ValidationObligation("obligation-none", None, "target-none", "Review target."),
                ValidationObligation("obligation-list", ["unsafe"], "target-list", "Review target."),
                ValidationObligation("obligation-blank", "   ", "target-blank", "Review target."),
                ValidationObligation("obligation-valid", "reviewed", "target-valid", "Review target."),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            (record.status, record.evidence)
            for record in doc.checks
            if record.property == "validation-obligation-has-safe-property"
            and record.target_id.startswith("obligation-")
        ]
        self.assertEqual(
            records,
            [
                (CheckStatus.FAIL, "unsupported validation obligation property=None type=NoneType"),
                (CheckStatus.FAIL, "unsupported validation obligation property=['unsafe'] type=list"),
                (CheckStatus.FAIL, "empty validation obligation property"),
                (CheckStatus.PASS, "property=reviewed"),
            ],
        )

    def test_validation_obligation_target_validation_refuses_non_string_values(self):
        doc = SpecDocument(
            validation_obligations=[
                ValidationObligation("obligation-none", "reviewed", None, "Review target."),
                ValidationObligation("obligation-list", "reviewed", ["unsafe"], "Review target."),
                ValidationObligation("obligation-blank", "reviewed", "   ", "Review target."),
                ValidationObligation("obligation-valid", "reviewed", "target-valid", "Review target."),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            (record.status, record.evidence)
            for record in doc.checks
            if record.property == "validation-obligation-has-safe-target"
            and record.target_id.startswith("obligation-")
        ]
        self.assertEqual(
            records,
            [
                (CheckStatus.FAIL, "unsupported validation obligation target=None type=NoneType"),
                (CheckStatus.FAIL, "unsupported validation obligation target=['unsafe'] type=list"),
                (CheckStatus.FAIL, "empty validation obligation target"),
                (CheckStatus.PASS, "target=target-valid"),
            ],
        )

    def test_validation_obligation_source_span_validation_refuses_unsafe_identities(self):
        doc = SpecDocument(
            validation_obligations=[
                ValidationObligation("obligation-none", "reviewed", "target-none", "Review target.", None),
                ValidationObligation("obligation-list", "reviewed", "target-list", "Review target.", ["unsafe"]),
                ValidationObligation("obligation-blank", "reviewed", "target-blank", "Review target.", "   "),
                ValidationObligation("obligation-valid", "reviewed", "target-valid", "Review target.", "span-valid"),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            (record.status, record.evidence)
            for record in doc.checks
            if record.property == "validation-obligation-has-safe-source-span-id"
            and record.target_id.startswith("obligation-")
        ]
        self.assertEqual(
            records,
            [
                (CheckStatus.PASS, "source span absent"),
                (CheckStatus.FAIL, "unsupported validation obligation source span identity=['unsafe'] type=list"),
                (CheckStatus.FAIL, "empty validation obligation source span identity"),
                (CheckStatus.PASS, "source_span=span-valid"),
            ],
        )

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

    def test_fact_validator_refuses_malformed_records_and_predicates(self):
        malformed_facts = [
            ["Requirement", "obj-malformed"],
            "Requirement",
            {0: "Requirement"},
            None,
            (1, "obj-malformed"),
            (None, "obj-malformed"),
        ]
        doc = SpecDocument(
            objects=[
                SpecObject(
                    "obj-malformed",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    None,
                    facts=malformed_facts,
                )
            ]
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            (record.status, record.evidence)
            for record in doc.checks
            if record.property == "fact-has-supported-arity"
        ]
        self.assertEqual(
            records,
            [
                (CheckStatus.FAIL, "unsupported fact record type=list"),
                (CheckStatus.FAIL, "unsupported fact record type=str"),
                (CheckStatus.FAIL, "unsupported fact record type=dict"),
                (CheckStatus.FAIL, "unsupported fact record type=NoneType"),
                (CheckStatus.FAIL, "unsupported fact predicate type=int"),
                (CheckStatus.FAIL, "unsupported fact predicate type=NoneType"),
            ],
        )

    def test_fact_validator_refuses_backend_unsafe_arguments(self):
        doc = SpecDocument(
            objects=[
                SpecObject(
                    "obj-arguments",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    None,
                    facts=[
                        ("RequirementText", "obj-arguments", ["unsafe"]),
                        ("Covers", "obj-arguments", 7),
                        ("RequirementText", "obj-arguments", "  "),
                        ("ConfidenceValue", "obj-arguments", float("nan")),
                        ("RequirementText", "obj-arguments", "safe"),
                    ],
                )
            ]
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            (record.status, record.evidence)
            for record in doc.checks
            if record.property == "fact-arguments-are-backend-safe"
        ]
        self.assertEqual(
            records,
            [
                (CheckStatus.FAIL, "argument@2 unsupported type=list"),
                (CheckStatus.FAIL, "object-reference@2 unsupported type=int"),
                (CheckStatus.FAIL, "argument@2 is empty"),
                (CheckStatus.FAIL, "argument@2 is non-finite"),
                (CheckStatus.PASS, "all fact arguments are backend-safe scalars"),
            ],
        )

    def test_fact_subject_validation_refuses_scalar_alias_of_string_object_id(self):
        doc = SpecDocument(
            objects=[
                SpecObject(
                    "7",
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.BACKEND_LOWERED,
                    None,
                    facts=[
                        ("RequirementText", 7, "unsafe alias"),
                        ("RequirementText", "7", "exact owner"),
                    ],
                )
            ]
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            (record.status, record.evidence)
            for record in doc.checks
            if record.property == "fact-subject-matches-object"
        ]
        self.assertEqual(
            records,
            [
                (CheckStatus.FAIL, "subject@1 unsupported type=int"),
                (CheckStatus.PASS, "fact subject matches owning object or is predicate-scoped"),
            ],
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

    def test_plain_file_field_validation_refuses_backend_unsafe_values(self):
        doc = SpecDocument(
            files=[
                PlainFile("file-path", None, "digest", "text"),
                PlainFile("file-digest", "bad.plain", ["digest"], "text"),
                PlainFile("file-text", "bad.plain", "digest", None),
                PlainFile("file-blank", "   ", "   ", ""),
                PlainFile("file-valid", "valid.plain", "sha256:test", "text"),
            ]
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            (record.status, record.evidence)
            for record in doc.checks
            if record.property == "plain-file-has-safe-fields"
        ]
        self.assertEqual(
            records,
            [
                (CheckStatus.FAIL, "path=None type=NoneType"),
                (CheckStatus.FAIL, "digest=['digest'] type=list"),
                (CheckStatus.FAIL, "text=None type=NoneType"),
                (CheckStatus.FAIL, "path is empty; digest is empty"),
                (CheckStatus.PASS, "path, digest, and text are backend-safe"),
            ],
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

    def test_plain_file_identity_validation_refuses_unhashable_and_blank_ids(self):
        doc = SpecDocument(
            files=[
                PlainFile(["file-unhashable"], "bad.plain", "digest", "text"),
                PlainFile("   ", "blank.plain", "digest", "text"),
                PlainFile("file-valid", "valid.plain", "digest", "text"),
            ]
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        for property_name, expected_type in (
            ("plain-file-identity-is-unique", "type=list"),
            ("plain-file-has-safe-identity", "type=list"),
        ):
            records = [record for record in doc.checks if record.property == property_name]
            self.assertTrue(any(record.status == CheckStatus.FAIL and expected_type in record.evidence for record in records))
        blank_records = [
            record for record in doc.checks
            if record.property == "plain-file-has-safe-identity" and "unsupported file identity='   '" in record.evidence
        ]
        self.assertEqual(len(blank_records), 1)
        self.assertEqual(blank_records[0].status, CheckStatus.FAIL)
        self.assertTrue(
            any(
                record.property == "plain-file-has-safe-identity"
                and record.status == CheckStatus.PASS
                and record.evidence == "file=file-valid"
                for record in doc.checks
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

    def test_source_span_validator_refuses_backend_unsafe_bound_types(self):
        doc = SpecDocument(
            files=[PlainFile("file-1", "bad.plain", "digest", "text")],
            spans=[
                SourceSpan("span-list", "file-1", [0], 1, 1, 1),
                SourceSpan("span-bool", "file-1", 0, True, 1, 1),
                SourceSpan("span-line", "file-1", 0, 1, None, 1),
                SourceSpan("span-reversed", "file-1", 2, 1, 2, 1),
                SourceSpan("span-valid", "file-1", 0, 1, 1, 1),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            (record.status, record.evidence)
            for record in doc.checks
            if record.property == "source-span-has-safe-bounds"
        ]
        self.assertEqual(
            records,
            [
                (CheckStatus.FAIL, "unsupported source span byte bounds start=[0] type=list end=1 type=int"),
                (CheckStatus.FAIL, "unsupported source span byte bounds start=0 type=int end=True type=bool"),
                (CheckStatus.FAIL, "unsupported source span line bounds start=None type=NoneType end=1 type=int"),
                (CheckStatus.FAIL, "invalid source span bounds bytes=2:1 lines=2:1"),
                (CheckStatus.PASS, "bytes=0:1 lines=1:1"),
            ],
        )

    def test_source_span_identity_validation_refuses_unhashable_and_blank_ids(self):
        doc = SpecDocument(
            files=[PlainFile("file-1", "bad.plain", "digest", "text")],
            spans=[
                SourceSpan(["span-unhashable"], "file-1", 0, 1, 1, 1),
                SourceSpan("   ", "file-1", 1, 2, 1, 1),
                SourceSpan("span-valid", "file-1", 2, 3, 1, 1),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        for property_name in (
            "source-span-identity-is-unique",
            "source-span-has-safe-identity",
        ):
            records = [record for record in doc.checks if record.property == property_name]
            self.assertTrue(
                any(record.status == CheckStatus.FAIL and "type=list" in record.evidence for record in records)
            )
        self.assertTrue(
            any(
                record.property == "source-span-has-safe-identity"
                and record.status == CheckStatus.FAIL
                and "unsupported span identity='   '" in record.evidence
                for record in doc.checks
            )
        )
        self.assertTrue(
            any(
                record.property == "source-span-has-safe-identity"
                and record.status == CheckStatus.PASS
                and record.evidence == "span=span-valid"
                for record in doc.checks
            )
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

    def test_section_field_validation_refuses_backend_unsafe_values(self):
        span = SourceSpan("span-1", "file-1", 0, 1, 1, 1)
        doc = SpecDocument(
            files=[PlainFile("file-1", "sections.plain", "digest", "text")],
            spans=[span],
            sections=[
                Section("section-kind-list", "file-1", "Bad", ["requirements"], 0, span),
                Section("section-kind-blank", "file-1", "Bad", "   ", 0, span),
                Section("section-ordinal-bool", "file-1", "Bad", "requirements", True, span),
                Section("section-ordinal-negative", "file-1", "Bad", "requirements", -1, span),
                Section("section-valid", "file-1", "Good", "requirements", 0, span),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            (record.status, record.evidence)
            for record in doc.checks
            if record.property == "section-has-safe-fields"
        ]
        self.assertEqual(
            records,
            [
                (CheckStatus.FAIL, "kind=['requirements'] type=list"),
                (CheckStatus.FAIL, "kind is empty"),
                (CheckStatus.FAIL, "ordinal=True type=bool"),
                (CheckStatus.FAIL, "ordinal=-1 is negative"),
                (CheckStatus.PASS, "kind and ordinal are backend-safe"),
            ],
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

    def test_section_file_identity_validation_refuses_backend_unsafe_values(self):
        span = SourceSpan("span-1", "file-1", 0, 1, 1, 1)
        doc = SpecDocument(
            files=[PlainFile("file-1", "sections.plain", "digest", "text")],
            spans=[span],
            sections=[
                Section("section-file-list", ["file-1"], "Bad", "requirements", 0, span),
                Section("section-file-blank", "   ", "Bad", "requirements", 1, span),
                Section("section-valid", "file-1", "Good", "requirements", 2, span),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            (record.status, record.evidence)
            for record in doc.checks
            if record.property == "section-has-safe-file-identity"
        ]
        self.assertEqual(
            records,
            [
                (CheckStatus.FAIL, "unsupported file_id=['file-1'] type=list"),
                (CheckStatus.FAIL, "unsupported file_id='   ' type=str"),
                (CheckStatus.PASS, "file_id=file-1"),
            ],
        )

    def test_plain_item_field_validation_refuses_backend_unsafe_values(self):
        span = SourceSpan("span-1", "file-1", 0, 1, 1, 1)
        section = Section("section-1", "file-1", "Items", "requirements", 0, span)
        doc = SpecDocument(
            files=[PlainFile("file-1", "items.plain", "digest", "text")],
            spans=[span],
            sections=[section],
            items=[
                PlainItem("item-ordinal-bool", "file-1", "section-1", None, True, 0, "text", span),
                PlainItem("item-ordinal-negative", "file-1", "section-1", None, -1, 0, "text", span),
                PlainItem("item-level-bool", "file-1", "section-1", None, 0, False, "text", span),
                PlainItem("item-level-negative", "file-1", "section-1", None, 0, -1, "text", span),
                PlainItem("item-text-list", "file-1", "section-1", None, 0, 0, ["text"], span),
                PlainItem("item-text-blank", "file-1", "section-1", None, 0, 0, "   ", span),
                PlainItem("item-valid", "file-1", "section-1", None, 0, 0, "text", span),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            (record.status, record.evidence)
            for record in doc.checks
            if record.property == "item-has-safe-fields"
        ]
        self.assertEqual(
            records,
            [
                (CheckStatus.FAIL, "ordinal=True type=bool"),
                (CheckStatus.FAIL, "ordinal=-1 is negative"),
                (CheckStatus.FAIL, "level=False type=bool"),
                (CheckStatus.FAIL, "level=-1 is negative"),
                (CheckStatus.FAIL, "raw_text=['text'] type=list"),
                (CheckStatus.FAIL, "raw_text is empty"),
                (CheckStatus.PASS, "ordinal, level, and raw_text are backend-safe"),
            ],
        )

    def test_plain_item_link_validation_refuses_backend_unsafe_values(self):
        span = SourceSpan("span-1", "file-1", 0, 1, 1, 1)
        section = Section("section-1", "file-1", "Items", "requirements", 0, span)
        doc = SpecDocument(
            files=[PlainFile("file-1", "items.plain", "digest", "text")],
            spans=[span],
            sections=[section],
            items=[
                PlainItem("item-file-list", ["file-1"], "section-1", None, 0, 0, "text", span),
                PlainItem("item-section-blank", "file-1", "   ", None, 1, 0, "text", span),
                PlainItem("item-parent-list", "file-1", "section-1", ["parent"], 2, 0, "text", span),
                PlainItem("item-parent-blank", "file-1", "section-1", "", 3, 0, "text", span),
                PlainItem("item-valid", "file-1", "section-1", None, 4, 0, "text", span),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            (record.status, record.evidence)
            for record in doc.checks
            if record.property == "item-has-safe-link-identities"
        ]
        self.assertEqual(
            records,
            [
                (CheckStatus.FAIL, "file_id=['file-1'] type=list"),
                (CheckStatus.FAIL, "section_id is empty"),
                (CheckStatus.FAIL, "parent_item_id=['parent'] type=list"),
                (CheckStatus.FAIL, "parent_item_id is empty"),
                (CheckStatus.PASS, "file, section, and optional parent link identities are backend-safe"),
            ],
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

    def test_section_and_item_identity_validation_refuses_unhashable_and_blank_ids(self):
        span = SourceSpan("span-main", "file-main", 0, 4, 1, 1)
        doc = SpecDocument(
            files=[PlainFile("file-main", "main.plain", "digest-main", "text")],
            spans=[span],
            sections=[
                Section(["section-unhashable"], "file-main", "Bad", "requirements", 0, span),
                Section("   ", "file-main", "Blank", "requirements", 1, span),
                Section("section-valid", "file-main", "Valid", "requirements", 2, span),
            ],
            items=[
                PlainItem(["item-unhashable"], "file-main", "section-valid", None, 0, 0, "bad", span),
                PlainItem("", "file-main", "section-valid", None, 1, 0, "blank", span),
                PlainItem("item-valid", "file-main", "section-valid", None, 2, 0, "valid", span),
            ],
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        expected = (
            ("section-identity-is-unique", "identity cannot be indexed safely: ['section-unhashable'] type=list", CheckStatus.FAIL),
            ("section-has-safe-identity", "unsupported section identity='   ' type=str", CheckStatus.FAIL),
            ("section-has-safe-identity", "section=section-valid", CheckStatus.PASS),
            ("item-identity-is-unique", "identity cannot be indexed safely: ['item-unhashable'] type=list", CheckStatus.FAIL),
            ("item-has-safe-identity", "unsupported item identity='' type=str", CheckStatus.FAIL),
            ("item-has-safe-identity", "item=item-valid", CheckStatus.PASS),
        )
        for property_name, evidence, status in expected:
            self.assertTrue(
                any(
                    record.property == property_name
                    and record.evidence == evidence
                    and record.status == status
                    for record in doc.checks
                ),
                (property_name, evidence, status),
            )

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

    def test_object_identity_validation_refuses_backend_unsafe_values(self):
        doc = SpecDocument(
            objects=[
                SpecObject(7, Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, None),  # type: ignore[arg-type]
                SpecObject(" \t ", Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, None),
                SpecObject("object-safe", Role.REQUIREMENT_OBJECT, SemanticLevel.TEMPLATE_PARSED, None),
            ]
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        checks = {
            check.target_id: (check.status, check.evidence)
            for check in doc.checks
            if check.property == "object-has-safe-identity"
        }
        self.assertEqual(
            checks,
            {
                7: (CheckStatus.FAIL, "unsupported object identity=7 type=int"),
                " \t ": (CheckStatus.FAIL, "unsupported object identity=' \\t ' type=str"),
                "object-safe": (CheckStatus.PASS, "object=object-safe"),
            },
        )

    def test_object_identity_validation_refuses_unhashable_value_without_crashing(self):
        doc = SpecDocument(
            objects=[
                SpecObject(
                    ["object-unhashable"],  # type: ignore[arg-type]
                    Role.REQUIREMENT_OBJECT,
                    SemanticLevel.TEMPLATE_PARSED,
                    None,
                )
            ]
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        checks = [
            check
            for check in doc.checks
            if check.property in {"object-identity-is-unique", "object-has-safe-identity"}
        ]
        self.assertEqual(
            [(check.property, check.status, check.evidence) for check in checks],
            [
                (
                    "object-identity-is-unique",
                    CheckStatus.FAIL,
                    "identity cannot be indexed safely: ['object-unhashable'] type=list",
                ),
                (
                    "object-has-safe-identity",
                    CheckStatus.FAIL,
                    "unsupported object identity=['object-unhashable'] type=list",
                ),
            ],
        )

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

    def test_object_semantic_level_validation_refuses_unhashable_value_without_crashing(self):
        doc = SpecDocument(
            objects=[
                SpecObject(
                    "object-unhashable-level",
                    Role.REQUIREMENT_OBJECT,
                    ["UnsupportedLevel"],  # type: ignore[arg-type]
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
            and check.target_id == "object-unhashable-level"
        ]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].status, CheckStatus.FAIL)
        self.assertEqual(
            checks[0].evidence,
            "unsupported semantic level=['UnsupportedLevel']",
        )

    def test_object_role_validation_refuses_unsupported_value_without_crashing(self):
        doc = SpecDocument(
            objects=[
                SpecObject(
                    "object-unsupported-role",
                    "UnsupportedRole",  # type: ignore[arg-type]
                    SemanticLevel.TEMPLATE_PARSED,
                    None,
                )
            ]
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        checks = [
            check
            for check in doc.checks
            if check.property == "object-has-known-role"
            and check.target_id == "object-unsupported-role"
        ]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].status, CheckStatus.FAIL)
        self.assertEqual(checks[0].evidence, "unsupported object role='UnsupportedRole'")

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

    def test_validation_layer_identity_validation_refuses_unhashable_values_without_crashing(self):
        obligation = ValidationObligation(
            ["obligation-unhashable"],  # type: ignore[arg-type]
            "property",
            "target",
            "rationale",
        )
        check = CheckRecord(
            ["check-unhashable"],  # type: ignore[arg-type]
            "obligation-reference",
            "property",
            "target",
            CheckStatus.PASS,
            "evidence",
        )
        doc = SpecDocument(validation_obligations=[obligation], checks=[check])
        from specatom_hs.validators import validate_document

        validate_document(doc)

        expected = (
            (
                "validation-obligation-identity-is-unique",
                "identity cannot be indexed safely: ['obligation-unhashable'] type=list",
            ),
            (
                "check-identity-is-unique",
                "identity cannot be indexed safely: ['check-unhashable'] type=list",
            ),
        )
        for property_name, evidence in expected:
            records = [record for record in doc.checks if record.property == property_name]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].status, CheckStatus.FAIL)
            self.assertEqual(records[0].evidence, evidence)

        safe_identity_expected = (
            (
                "validation-obligation-has-safe-identity",
                "unsupported validation obligation identity=['obligation-unhashable'] type=list",
            ),
            (
                "check-has-safe-identity",
                "unsupported check identity=['check-unhashable'] type=list",
            ),
        )
        for property_name, evidence in safe_identity_expected:
            records = [record for record in doc.checks if record.property == property_name]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].status, CheckStatus.FAIL)
            self.assertEqual(records[0].evidence, evidence)

    def test_validation_layer_safe_identity_checks_blank_and_valid_strings(self):
        obligations = [
            ValidationObligation("   ", "property", "target", "rationale"),
            ValidationObligation("obligation-valid", "property", "target", "rationale"),
        ]
        checks = [
            CheckRecord("", "obligation-valid", "property", "target", CheckStatus.PASS, "evidence"),
            CheckRecord("check-valid", "obligation-valid", "property", "target", CheckStatus.PASS, "evidence"),
        ]
        doc = SpecDocument(validation_obligations=obligations, checks=checks)
        from specatom_hs.validators import validate_document

        validate_document(doc)

        obligation_records = [
            record
            for record in doc.checks
            if record.property == "validation-obligation-has-safe-identity"
        ]
        self.assertEqual(
            [(record.status, record.evidence) for record in obligation_records],
            [
                (CheckStatus.FAIL, "unsupported validation obligation identity='   ' type=str"),
                (CheckStatus.PASS, "validation obligation=obligation-valid"),
            ],
        )
        check_records = [
            record for record in doc.checks if record.property == "check-has-safe-identity"
        ]
        self.assertEqual(
            [(record.status, record.evidence) for record in check_records],
            [
                (CheckStatus.FAIL, "unsupported check identity='' type=str"),
                (CheckStatus.PASS, "check=check-valid"),
            ],
        )

    def test_object_source_span_validation_refuses_unsafe_identities(self):
        objects = [
            SpecObject("object-none", Role.CONCEPT_OBJECT, SemanticLevel.FORMALLY_TYPED, None),
            SpecObject("object-list", Role.CONCEPT_OBJECT, SemanticLevel.FORMALLY_TYPED, ["unsafe"]),  # type: ignore[arg-type]
            SpecObject("object-blank", Role.CONCEPT_OBJECT, SemanticLevel.FORMALLY_TYPED, "   "),
            SpecObject("object-valid", Role.CONCEPT_OBJECT, SemanticLevel.FORMALLY_TYPED, "span-valid"),
        ]
        doc = SpecDocument(
            spans=[SourceSpan("span-valid", "file-valid", 0, 1, 1, 1)],
            objects=objects,
        )
        from specatom_hs.validators import validate_document

        validate_document(doc)

        records = [
            record
            for record in doc.checks
            if record.property == "object-has-safe-source-span-id"
        ]
        self.assertEqual(
            [(record.target_id, record.status, record.evidence) for record in records],
            [
                ("object-none", CheckStatus.PASS, "source_span=None"),
                (
                    "object-list",
                    CheckStatus.FAIL,
                    "unsupported object source span identity=['unsafe'] type=list",
                ),
                (
                    "object-blank",
                    CheckStatus.FAIL,
                    "unsupported object source span identity='   ' type=str",
                ),
                ("object-valid", CheckStatus.PASS, "source_span=span-valid"),
            ],
        )

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

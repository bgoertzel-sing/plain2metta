import unittest

from specatom_hs.passes import compile_source
from specatom_hs.schema import CheckRecord, CheckStatus, Role, SemanticLevel, SpecDocument, SpecObject, ValidationObligation
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


if __name__ == "__main__":
    unittest.main()

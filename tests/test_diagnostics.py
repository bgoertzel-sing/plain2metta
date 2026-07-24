import tempfile
import unittest
from pathlib import Path

from specatom_hs.backends.diagnostics import diagnostics_summary, format_diagnostics_report
from specatom_hs.backends.petta import emit_metta_file, emit_reified_atoms, emit_reified_atoms_grouped
from specatom_hs.passes import compile_path
from specatom_hs.schema import CheckRecord, CheckStatus, Role, SemanticLevel, SpecDocument, SpecObject, ValidationObligation
from specatom_hs.validators import validate_document


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "task_manager.plain"
AUTH_EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "auth_service.plain"


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.doc = compile_path(EXAMPLE)

    def test_diagnostics_summary_task_manager_example(self):
        summary = diagnostics_summary(self.doc)

        self.assertEqual(summary["total_objects"], len(self.doc.objects))
        self.assertEqual(summary["total_obligations"], len(self.doc.validation_obligations))
        self.assertEqual(summary["total_checks"], len(self.doc.checks))
        self.assertGreater(summary["pass"], 0)
        self.assertGreaterEqual(summary["unknown"], 0)
        self.assertIn("by_property", summary)
        self.assertIn("defined", summary["concepts"])
        self.assertGreater(summary["questions"], 0)
        self.assertGreaterEqual(summary["requirements"], 0)
        self.assertGreaterEqual(summary["acceptance_tests"], 0)
        self.assertGreaterEqual(summary["coverage_pass"], 0)
        self.assertGreaterEqual(summary["coverage_unknown"], 0)

    def test_format_diagnostics_report_has_expected_sections(self):
        report = format_diagnostics_report(self.doc)

        self.assertTrue(report)
        self.assertIn("SpecAtom-HS Diagnostics Report", report)
        self.assertIn("Summary Counts", report)
        self.assertIn("Per-property Breakdown", report)
        self.assertIn("FAIL Checks", report)
        self.assertIn("UNKNOWN Checks", report)
        self.assertIn("Questions", report)
        self.assertIn("Backend Refusals", report)

    def test_grouped_petta_atoms_add_comment_sections(self):
        atoms, _ = emit_reified_atoms(self.doc)
        grouped_atoms, _ = emit_reified_atoms_grouped(self.doc)

        self.assertGreater(len(grouped_atoms), len(atoms))
        self.assertIn(";;; Source Files", grouped_atoms)
        self.assertIn(";;; Validation", grouped_atoms)
        self.assertIn(";;; Refusals", grouped_atoms)

    def test_emit_metta_file_writes_grouped_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "task_manager.metta"
            emit_metta_file(self.doc, str(path))
            content = path.read_text(encoding="utf-8")

        self.assertIn(";;; Source Files", content)
        self.assertIn("(plain-file", content)
        self.assertIn(";;; Refusals", content)

    def test_auth_service_demo_surfaces_expected_review_questions(self):
        doc = compile_path(AUTH_EXAMPLE)
        summary = diagnostics_summary(doc)
        report = format_diagnostics_report(doc)
        atoms, _ = emit_reified_atoms(doc)

        self.assertGreater(summary["unknown"], 0)
        self.assertGreater(summary["questions"], 0)
        self.assertIn("DuplicateRequirementLabel", "\n".join(atoms))
        self.assertIn("MissingCoverageTarget", "\n".join(atoms))
        self.assertIn("UnresolvedConcept", "\n".join(atoms))
        self.assertIn("AUTH-2", report)
        self.assertIn("AUTH-99", report)
        self.assertIn("AuditSink", report)

    def test_diagnostics_fail_closed_on_malformed_records_and_facts(self):
        valid = SpecObject(
            "question-valid",
            Role.QUESTION_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[None, ("QuestionText", "question-valid", "Review this."), 7],
        )
        malformed_facts = SpecObject(
            "question-malformed-facts",
            Role.QUESTION_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
        )
        malformed_facts.facts = None
        doc = SpecDocument(objects=[None, valid, malformed_facts])
        validate_document(doc)
        doc.checks.insert(0, None)

        summary = diagnostics_summary(doc)
        report = format_diagnostics_report(doc)

        self.assertEqual(summary["questions"], 1)
        self.assertGreater(summary["fail"], 0)
        self.assertIn("Review this.", report)
        self.assertIn("unsupported-spec-object-record-type:NoneType", report)
        self.assertIn("unsupported-check-record-type:NoneType", report)
        self.assertIn("unsupported-object-facts-container-type:NoneType", report)

    def test_diagnostics_fail_closed_on_malformed_check_fields(self):
        obligation = ValidationObligation(
            "obligation-valid", "review", "target-valid", "Review target."
        )
        malformed = CheckRecord(
            "check-malformed",
            obligation.id,
            ["review"],
            obligation.target_id,
            ["Pass"],
            "invalid structured fields",
        )
        malformed_string_status = CheckRecord(
            "check-malformed-string-status",
            obligation.id,
            obligation.property,
            obligation.target_id,
            "Pass",
            "invalid string status",
        )
        valid = CheckRecord(
            "check-valid",
            obligation.id,
            obligation.property,
            obligation.target_id,
            CheckStatus.PASS,
            "reviewed",
        )
        doc = SpecDocument(
            validation_obligations=[obligation],
            checks=[malformed, malformed_string_status, valid],
        )

        summary = diagnostics_summary(doc)
        report = format_diagnostics_report(doc)

        self.assertEqual(summary["pass"], 1)
        self.assertEqual(summary["unknown"], 0)
        self.assertNotIn("<invalid list: ['review']>", summary["by_property"])
        self.assertEqual(summary["by_property"]["review"]["pass"], 1)
        self.assertNotIn("invalid structured fields", report)
        self.assertNotIn("invalid string status", report)
        self.assertIn("unsupported-check-property-type:list", report)
        self.assertIn("unsupported-check-status-type:str", report)

    def test_diagnostics_fail_closed_on_refused_check_scalar_fields(self):
        obligation = ValidationObligation(
            "obligation-valid", "review", "target-valid", "Review target."
        )

        def check(check_id, obligation_id, property_name, target_id, evidence):
            return CheckRecord(
                check_id,
                obligation_id,
                property_name,
                target_id,
                CheckStatus.FAIL,
                evidence,
            )

        doc = SpecDocument(
            validation_obligations=[obligation],
            checks=[
                check(
                    "check-obligation",
                    ["obligation-valid"],
                    obligation.property,
                    obligation.target_id,
                    "Do not report structured obligation.",
                ),
                check(
                    "check-property",
                    obligation.id,
                    " ",
                    obligation.target_id,
                    "Do not report blank property.",
                ),
                check(
                    "check-target",
                    obligation.id,
                    obligation.property,
                    None,
                    "Do not report missing target.",
                ),
                check(
                    "check-evidence",
                    obligation.id,
                    obligation.property,
                    obligation.target_id,
                    " ",
                ),
                CheckRecord(
                    "check-valid",
                    obligation.id,
                    obligation.property,
                    obligation.target_id,
                    CheckStatus.PASS,
                    "Report valid.",
                ),
            ],
        )

        summary = diagnostics_summary(doc)
        report = format_diagnostics_report(doc)

        self.assertEqual(summary["pass"], 1)
        self.assertEqual(summary["fail"], 0)
        self.assertNotIn("Do not report", report)
        self.assertIn("unsupported-check-obligation-id-type:list", report)
        self.assertIn("missing-check-property", report)
        self.assertIn("unsupported-check-target-id-type:NoneType", report)
        self.assertIn("missing-check-evidence", report)

    def test_diagnostics_fail_closed_on_refused_check_identities(self):
        def check(check_id, status, evidence):
            return CheckRecord(
                check_id,
                "obligation",
                "property",
                "target",
                status,
                evidence,
            )

        doc = SpecDocument(
            checks=[
                check(" ", CheckStatus.FAIL, "Do not report blank."),
                check(["check-structured"], CheckStatus.FAIL, "Do not report structured."),
                check("check-duplicate", CheckStatus.FAIL, "Do not report duplicate A."),
                check("check-duplicate", CheckStatus.FAIL, "Do not report duplicate B."),
                check("check-valid", CheckStatus.PASS, "Report valid."),
            ]
        )

        summary = diagnostics_summary(doc)
        report = format_diagnostics_report(doc)

        self.assertEqual(summary["pass"], 1)
        self.assertEqual(summary["fail"], 0)
        self.assertNotIn("Do not report blank.", report)
        self.assertNotIn("Do not report structured.", report)
        self.assertNotIn("Do not report duplicate", report)
        self.assertIn("missing-check-id", report)
        self.assertIn("unsupported-check-id-type:list", report)
        self.assertIn("duplicate-check-id", report)

    def test_diagnostics_fail_closed_on_structured_concept_status(self):
        malformed = SpecObject(
            "concept-malformed",
            Role.CONCEPT_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[("ConceptStatus", "concept-malformed", ["defined"])],
        )
        valid = SpecObject(
            "concept-valid",
            Role.CONCEPT_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[("ConceptStatus", "concept-valid", "defined")],
        )
        doc = SpecDocument(objects=[malformed, valid])
        validate_document(doc)

        summary = diagnostics_summary(doc)
        report = format_diagnostics_report(doc)

        self.assertEqual(
            summary["concepts"],
            {"defined": 1, "external": 0, "unresolved": 0},
        )
        self.assertGreater(summary["fail"], 0)
        self.assertIn(
            "unsupported-fact-argument-type:ConceptStatus:position-2:list",
            report,
        )

    def test_diagnostics_fail_closed_on_string_object_roles(self):
        malformed_question = SpecObject(
            "question-malformed-role",
            "QuestionObject",
            SemanticLevel.TEMPLATE_PARSED,
            facts=[("QuestionText", "question-malformed-role", "Do not report this.")],
        )
        malformed_requirement = SpecObject(
            "requirement-malformed-role",
            "RequirementObject",
            SemanticLevel.TEMPLATE_PARSED,
        )
        malformed_validation = SpecObject(
            "validation-malformed-role",
            "ValidationObject",
            SemanticLevel.TEMPLATE_PARSED,
            facts=[("TestKind", "validation-malformed-role", "Acceptance")],
        )
        valid_question = SpecObject(
            "question-valid",
            Role.QUESTION_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[("QuestionText", "question-valid", "Review this.")],
        )
        doc = SpecDocument(
            objects=[
                malformed_question,
                malformed_requirement,
                malformed_validation,
                valid_question,
            ]
        )
        validate_document(doc)

        summary = diagnostics_summary(doc)
        report = format_diagnostics_report(doc)

        self.assertEqual(summary["questions"], 1)
        self.assertEqual(summary["requirements"], 0)
        self.assertEqual(summary["acceptance_tests"], 0)
        self.assertIn("Review this.", report)
        self.assertNotIn("Do not report this.", report)
        self.assertIn("unsupported-object-role-type-for-reified-emission:str", report)

    def test_diagnostics_fail_closed_on_structured_question_facts(self):
        obligation = ValidationObligation(
            "obligation-valid", "review", "target-valid", "Review target."
        )
        malformed = SpecObject(
            "question-malformed",
            Role.QUESTION_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[
                ("QuestionText", "question-malformed", ["Do not report this."]),
                ("Blocks", "question-malformed", [obligation.id]),
            ],
        )
        valid = SpecObject(
            "question-valid",
            Role.QUESTION_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[
                ("QuestionText", "question-valid", "Review this."),
                ("Blocks", "question-valid", obligation.id),
            ],
        )
        doc = SpecDocument(
            objects=[malformed, valid],
            validation_obligations=[obligation],
        )
        validate_document(doc)

        summary = diagnostics_summary(doc)
        report = format_diagnostics_report(doc)
        checks = {
            (check.property, check.target_id): check
            for check in doc.checks
            if isinstance(check, CheckRecord)
        }

        self.assertEqual(summary["questions"], 2)
        self.assertEqual(
            checks[("question-has-review-text", malformed.id)].status,
            CheckStatus.FAIL,
        )
        self.assertEqual(
            checks[("question-blocks-validation-obligation", malformed.id)].status,
            CheckStatus.FAIL,
        )
        self.assertEqual(
            checks[("question-has-review-text", valid.id)].status,
            CheckStatus.PASS,
        )
        self.assertEqual(
            checks[("question-blocks-validation-obligation", valid.id)].status,
            CheckStatus.PASS,
        )
        self.assertIn("Review this.", report)
        self.assertNotIn("Do not report this.", report)
        self.assertIn(
            "unsupported-fact-argument-type:QuestionText:position-2:list",
            report,
        )
        self.assertIn(
            "unsupported-fact-argument-type:Blocks:position-2:list",
            report,
        )

    def test_diagnostics_fail_closed_on_mismatched_fact_subjects(self):
        malformed_concept = SpecObject(
            "concept-malformed",
            Role.CONCEPT_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[("ConceptStatus", "different-object", "defined")],
        )
        malformed_validation = SpecObject(
            "validation-malformed",
            Role.VALIDATION_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[("TestKind", "different-object", "Acceptance")],
        )
        malformed_question = SpecObject(
            "question-malformed",
            Role.QUESTION_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[("QuestionText", "different-object", "Do not report this.")],
        )
        valid_question = SpecObject(
            "question-valid",
            Role.QUESTION_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[("QuestionText", "question-valid", "Review this.")],
        )
        doc = SpecDocument(
            objects=[
                malformed_concept,
                malformed_validation,
                malformed_question,
                valid_question,
            ]
        )
        validate_document(doc)

        summary = diagnostics_summary(doc)
        report = format_diagnostics_report(doc)

        self.assertEqual(
            summary["concepts"],
            {"defined": 0, "external": 0, "unresolved": 0},
        )
        self.assertEqual(summary["acceptance_tests"], 0)
        self.assertIn("Review this.", report)
        self.assertNotIn("Do not report this.", report)
        self.assertIn("fact-subject-matches-object", report)
        self.assertIn("fact-subject-mismatch:TestKind", report)
        self.assertIn("fact-subject-mismatch:QuestionText", report)

    def test_diagnostics_fail_closed_on_extra_fact_arguments(self):
        malformed_concept = SpecObject(
            "concept-malformed",
            Role.CONCEPT_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[("ConceptStatus", "concept-malformed", "defined", "extra")],
        )
        malformed_validation = SpecObject(
            "validation-malformed",
            Role.VALIDATION_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[("TestKind", "validation-malformed", "Acceptance", "extra")],
        )
        malformed_question = SpecObject(
            "question-malformed",
            Role.QUESTION_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[
                (
                    "QuestionText",
                    "question-malformed",
                    "Do not report this.",
                    "extra",
                )
            ],
        )
        valid_question = SpecObject(
            "question-valid",
            Role.QUESTION_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[("QuestionText", "question-valid", "Review this.")],
        )
        doc = SpecDocument(
            objects=[
                malformed_concept,
                malformed_validation,
                malformed_question,
                valid_question,
            ]
        )
        validate_document(doc)

        summary = diagnostics_summary(doc)
        report = format_diagnostics_report(doc)

        self.assertEqual(
            summary["concepts"],
            {"defined": 0, "external": 0, "unresolved": 0},
        )
        self.assertEqual(summary["acceptance_tests"], 0)
        self.assertIn("Review this.", report)
        self.assertNotIn("Do not report this.", report)
        self.assertIn("fact-has-supported-arity", report)
        self.assertIn("unsupported-fact-arity:ConceptStatus:expected-3:got-4", report)
        self.assertIn("unsupported-fact-arity:TestKind:expected-3:got-4", report)
        self.assertIn("unsupported-fact-arity:QuestionText:expected-3:got-4", report)

    def test_diagnostics_fail_closed_on_refused_object_identities(self):
        blank = SpecObject(
            " ",
            Role.QUESTION_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[("QuestionText", " ", "Do not report blank.")],
        )
        structured = SpecObject(
            ["question-structured"],
            Role.QUESTION_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[("QuestionText", ["question-structured"], "Do not report structured.")],
        )
        duplicate_a = SpecObject(
            "question-duplicate",
            Role.QUESTION_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[("QuestionText", "question-duplicate", "Do not report duplicate A.")],
        )
        duplicate_b = SpecObject(
            "question-duplicate",
            Role.QUESTION_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[("QuestionText", "question-duplicate", "Do not report duplicate B.")],
        )
        valid = SpecObject(
            "question-valid",
            Role.QUESTION_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[("QuestionText", "question-valid", "Review this.")],
        )
        doc = SpecDocument(
            objects=[blank, structured, duplicate_a, duplicate_b, valid]
        )
        validate_document(doc)

        summary = diagnostics_summary(doc)
        report = format_diagnostics_report(doc)

        self.assertEqual(summary["questions"], 1)
        self.assertIn("Review this.", report)
        self.assertNotIn("Do not report blank.", report)
        self.assertNotIn("Do not report structured.", report)
        self.assertNotIn("Do not report duplicate", report)
        self.assertIn("missing-object-id-for-reified-emission", report)
        self.assertIn("duplicate-object-id-for-reified-emission", report)

    def test_diagnostics_fail_closed_on_refused_semantic_levels(self):
        raw_question = SpecObject(
            "question-raw",
            Role.QUESTION_OBJECT,
            SemanticLevel.RAW_TEXT_ONLY,
            facts=[("QuestionText", "question-raw", "Do not report raw text.")],
        )
        malformed_question = SpecObject(
            "question-malformed-level",
            Role.QUESTION_OBJECT,
            "TemplateParsed",
            facts=[
                (
                    "QuestionText",
                    "question-malformed-level",
                    "Do not report malformed level.",
                )
            ],
        )
        raw_concept = SpecObject(
            "concept-raw",
            Role.CONCEPT_OBJECT,
            SemanticLevel.RAW_TEXT_ONLY,
            facts=[("ConceptStatus", "concept-raw", "defined")],
        )
        raw_validation = SpecObject(
            "validation-raw",
            Role.VALIDATION_OBJECT,
            SemanticLevel.RAW_TEXT_ONLY,
            facts=[("TestKind", "validation-raw", "Acceptance")],
        )
        valid = SpecObject(
            "question-valid",
            Role.QUESTION_OBJECT,
            SemanticLevel.TEMPLATE_PARSED,
            facts=[("QuestionText", "question-valid", "Review this.")],
        )
        doc = SpecDocument(
            objects=[
                raw_question,
                malformed_question,
                raw_concept,
                raw_validation,
                valid,
            ]
        )

        summary = diagnostics_summary(doc)
        report = format_diagnostics_report(doc)

        self.assertEqual(summary["questions"], 1)
        self.assertEqual(
            summary["concepts"],
            {"defined": 0, "external": 0, "unresolved": 0},
        )
        self.assertEqual(summary["acceptance_tests"], 0)
        self.assertIn("Review this.", report)
        self.assertNotIn("Do not report raw text.", report)
        self.assertNotIn("Do not report malformed level.", report)
        self.assertIn("unsupported-semantic-level-for-reified-emission", report)
        self.assertIn(
            "unsupported-semantic-level-type-for-reified-emission:str",
            report,
        )


if __name__ == "__main__":
    unittest.main()

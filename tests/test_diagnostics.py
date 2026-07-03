import tempfile
import unittest
from pathlib import Path

from specatom_hs.backends.diagnostics import diagnostics_summary, format_diagnostics_report
from specatom_hs.backends.petta import emit_metta_file, emit_reified_atoms, emit_reified_atoms_grouped
from specatom_hs.passes import compile_path


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


if __name__ == "__main__":
    unittest.main()

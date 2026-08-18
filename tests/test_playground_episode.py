import unittest
from pathlib import Path

from specatom_hs.backends.diagnostics import diagnostics_summary, format_diagnostics_report
from specatom_hs.backends.petta import emit_reified_atoms_grouped
from specatom_hs.cli import document_json
from specatom_hs.passes import compile_path
from specatom_hs.schema import CheckStatus


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "examples" / "playground" / "task_list.plain"
EDITED = ROOT / "examples" / "playground" / "task_list_edited.plain"
QUERY_RUNNER = ROOT / "scripts" / "playground-query.sh"


class PlaygroundEpisodeTests(unittest.TestCase):
    def test_query_runner_pins_backend_and_joins_archive_coverage(self):
        text = QUERY_RUNNER.read_text(encoding="utf-8")
        self.assertIn('expected_version="0.2.10"', text)
        self.assertIn("(CoverageClaim $test TASK-ARCHIVE)", text)
        self.assertIn("(Covers $test $requirement)", text)
        self.assertIn("(RequirementLabel $requirement TASK-ARCHIVE)", text)

    def test_episode_is_bounded_and_edit_resolves_archive_coverage(self):
        base = compile_path(BASE)
        edited = compile_path(EDITED)
        base_summary = diagnostics_summary(base)
        edited_summary = diagnostics_summary(edited)

        self.assertEqual(base_summary["requirements"], 2)
        self.assertEqual(base_summary["acceptance_tests"], 1)
        self.assertEqual(edited_summary["requirements"], 2)
        self.assertEqual(edited_summary["acceptance_tests"], 2)
        self.assertEqual(base_summary["coverage_unknown"], 1)
        self.assertEqual(edited_summary["coverage_unknown"], 0)
        self.assertGreater(edited_summary["coverage_pass"], base_summary["coverage_pass"])

        archive_requirement = next(
            obj
            for obj in edited.objects
            if ("RequirementLabel", obj.id, "TASK-ARCHIVE") in obj.facts
        )
        archive_test = next(
            obj
            for obj in edited.objects
            if ("CoverageClaim", obj.id, "TASK-ARCHIVE") in obj.facts
        )
        self.assertIn(("Covers", archive_test.id, archive_requirement.id), archive_test.facts)
        self.assertTrue(
            any(
                check.property == "requirement-has-acceptance-test"
                and check.target_id == archive_requirement.id
                and check.status == CheckStatus.PASS
                for check in edited.checks
            )
        )

        edited_atoms, _ = emit_reified_atoms_grouped(edited)
        self.assertIn(
            f"(Covers {archive_test.id} {archive_requirement.id})",
            edited_atoms,
        )
        self.assertIn("TASK-ARCHIVE", document_json(edited))
        self.assertIn("coverage_unknown | 0", format_diagnostics_report(edited))

        for doc in (base, edited):
            atoms, _ = emit_reified_atoms_grouped(doc)
            self.assertLess(len(doc.checks), 1_000)
            self.assertLess(len(document_json(doc).encode()), 1_000_000)
            self.assertLess(len(("\n".join(atoms) + "\n").encode()), 500_000)
            self.assertLess(len(format_diagnostics_report(doc).encode()), 50_000)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from specatom_hs import cli


class CliTests(unittest.TestCase):
    def setUp(self):
        self.input_path = Path("examples/task_manager.plain")
        self.outputs = [
            self.input_path.with_suffix(".json"),
            self.input_path.with_suffix(".metta"),
            self.input_path.with_suffix(".diag"),
        ]
        self.cleanup_outputs()

    def tearDown(self):
        self.cleanup_outputs()

    def cleanup_outputs(self):
        for path in self.outputs:
            path.unlink(missing_ok=True)

    def test_all_writes_outputs_and_exits_zero(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = cli.main(["--all", str(self.input_path)])

        self.assertEqual(0, code, stderr.getvalue())
        for path in self.outputs:
            self.assertTrue(path.exists(), f"missing {path}")
            self.assertGreater(path.stat().st_size, 0)

    def test_json_flag_writes_valid_json_to_stdout(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(["--json", str(self.input_path)])

        self.assertEqual(0, code, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertIn("facts", payload)
        self.assertIn("checks", payload)
        self.assertEqual([], [path for path in self.outputs if path.exists()])

    def test_metta_flag_uses_grouped_reified_export(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(["--metta", str(self.input_path)])

        self.assertEqual(0, code, stderr.getvalue())
        text = stdout.getvalue()
        self.assertIn(";;; Source Files", text)
        self.assertIn(";;; Validation", text)
        self.assertIn("; backend-refusal", text)

    def test_diagnostics_flag_writes_markdown_report(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(["--diagnostics", str(self.input_path)])

        self.assertEqual(0, code, stderr.getvalue())
        report = stdout.getvalue()
        self.assertIn("# SpecAtom-HS Diagnostics Report", report)
        self.assertIn("## Per-property Breakdown", report)
        self.assertIn("## Backend Refusals", report)


if __name__ == "__main__":
    unittest.main()

import copy
import unittest

from specatom_hs.compiler_output import CompilerOutputBundle, GeneratedFile
from specatom_hs.sandbox_protocol import SandboxTestResult, TestCaseResult
from specatom_hs.traceability import (
    ProvenanceLink, build_traceability_report, traceability_report_from_dict,
    traceability_report_to_dict,
)


class TraceabilityReportTests(unittest.TestCase):
    def provenance(self):
        phases = (
            "original-spec", "elaborated-spec", "test-spec", "logical-ir",
            "compiler-output", "sandbox-handoff", "test-result",
        )
        return tuple(ProvenanceLink(phase, f"artifact-{index}", "sha256:" + f"{index:x}" * 64) for index, phase in enumerate(phases))

    def test_report_classifies_passing_failing_skipped_and_untested(self):
        bundle = CompilerOutputBundle((
            GeneratedFile("code.metta", "", ("REQ-1", "REQ-2", "REQ-3", "REQ-4")),
            GeneratedFile("tests.py", "", ("REQ-1", "REQ-2", "REQ-3"), ("T1", "T2", "T3")),
        ), "compiler")
        result = SandboxTestResult("sha256:" + "a" * 64, "adapter", (
            TestCaseResult("T1", "passed", 1, covered_spec_ids=("REQ-1",)),
            TestCaseResult("T2", "failed", 2, stderr="boom", covered_spec_ids=("REQ-2",), assertion="x == y"),
            TestCaseResult("T3", "skipped", 0, covered_spec_ids=("REQ-3",), assertion="optional"),
        ))
        report = build_traceability_report(self.provenance(), bundle, result)
        self.assertEqual(("passing", "failing", "skipped", "untested"), tuple(entry.status for entry in report.entries))
        self.assertEqual(("T2: x == y",), report.entries[1].failure_details)
        self.assertEqual(report, traceability_report_from_dict(traceability_report_to_dict(report)))

    def test_malformed_and_forged_reports_fail_closed(self):
        bundle = CompilerOutputBundle((GeneratedFile("code.metta", "", ("REQ-1",), ("T1",)),), "compiler")
        result = SandboxTestResult("sha256:" + "a" * 64, "adapter", (TestCaseResult("T1", "passed", 1, covered_spec_ids=("REQ-1",)),))
        payload = traceability_report_to_dict(build_traceability_report(self.provenance(), bundle, result))
        mutations = []
        bad_summary = copy.deepcopy(payload); bad_summary["summary"]["passing"] = 9; mutations.append(bad_summary)
        bad_list = copy.deepcopy(payload); bad_list["entries"][0]["code_locations"] = "code.metta"; mutations.append(bad_list)
        bad_hash = copy.deepcopy(payload); bad_hash["provenance"][0]["content_hash"] = "sha256:" + "z" * 64; mutations.append(bad_hash)
        unknown = copy.deepcopy(payload); unknown["host_path"] = "/tmp"; mutations.append(unknown)
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                traceability_report_from_dict(mutation)


if __name__ == "__main__":
    unittest.main()

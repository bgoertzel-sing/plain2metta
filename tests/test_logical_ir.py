import copy
import unittest

from specatom_hs.logical_ir import (
    Contract, DependencyDeclaration, FindingCategory, FindingDisposition,
    LogicalIRDocument, OperationalHole, RequirementObligation, TypeDeclaration,
    canonical_logical_ir, decide_finding, logical_ir_from_dict, logical_ir_hash,
    logical_ir_to_dict, logical_review_from_dict, logical_review_to_dict,
    review_logical_ir,
)


class LogicalIRTests(unittest.TestCase):
    def document(self, *, hole=True, tests=("TEST-1",), output="Result"):
        return LogicalIRDocument(
            "DemoModule",
            (TypeDeclaration("type.Input", "Input", ("REQ-1",)),
             TypeDeclaration("type.Result", "Result", ("REQ-1",))),
            (Contract("contract.transform", "transform", ("Input",), output,
                      ("input is valid",), ("result is returned",),
                      ("source remains unchanged",), ("REQ-1",), True),),
            (RequirementObligation("REQ-1", tests, ("REQ-1",)),),
            (DependencyDeclaration("dependency.1", "transform", "TEST-1", "tested-by", ("REQ-1",)),),
            (OperationalHole("hole.transform", "contract.transform", "Result",
                             "grounded implementation required", ("REQ-1",)),) if hole else (),
        )

    def test_strict_non_executable_schema_round_trips_and_hashes(self):
        document = self.document()
        payload = logical_ir_to_dict(document)
        self.assertIs(False, payload["executable"])
        self.assertNotIn("body", payload)
        self.assertEqual(document, logical_ir_from_dict(payload))
        self.assertEqual(logical_ir_hash(document), logical_ir_hash(logical_ir_from_dict(payload)))
        self.assertEqual(canonical_logical_ir(document), canonical_logical_ir(document))

    def test_schema_retains_contracts_dependencies_provenance_and_explicit_holes(self):
        payload = logical_ir_to_dict(self.document())
        self.assertEqual(["REQ-1"], payload["contracts"][0]["source_clause_ids"])
        self.assertEqual("tested-by", payload["dependencies"][0]["relation"])
        self.assertEqual("contract.transform", payload["operational_holes"][0]["contract_id"])

    def test_review_emits_source_linked_critical_findings_and_blocks(self):
        report = review_logical_ir(self.document(hole=False, tests=(), output="Missing"))
        self.assertTrue(report.blocks_compilation)
        self.assertEqual(
            {FindingCategory.MISSING_DEFINITION, FindingCategory.UNCOVERED_REQUIREMENT,
             FindingCategory.UNMARKED_OPERATIONAL_GAP},
            {finding.category for finding in report.findings},
        )
        self.assertTrue(all(finding.source_clause_ids == ("REQ-1",) for finding in report.findings))

    def test_repair_or_waiver_requires_identity_and_rationale(self):
        report = review_logical_ir(self.document(tests=()))
        finding = report.findings[0]
        with self.assertRaises(ValueError):
            decide_finding(report, finding.finding_id, FindingDisposition.WAIVED, "", "reason")
        decided = decide_finding(report, finding.finding_id, FindingDisposition.WAIVED, "ben", "accepted risk")
        self.assertFalse(decided.blocks_compilation)
        self.assertEqual(decided, logical_review_from_dict(logical_review_to_dict(decided)))

    def test_deferred_critical_finding_still_blocks(self):
        report = review_logical_ir(self.document(tests=()))
        decided = decide_finding(report, report.findings[0].finding_id, FindingDisposition.DEFERRED, "ben", "later")
        self.assertTrue(decided.blocks_compilation)

    def test_malformed_or_executable_envelopes_fail_closed(self):
        payload = logical_ir_to_dict(self.document())
        for mutate in (
            lambda value: value.update(executable=True),
            lambda value: value.update(body="(run-application)"),
            lambda value: value["contracts"][0].update(executable_body="(run-application)"),
            lambda value: value["contracts"][0].update(source_clause_ids=[]),
            lambda value: value["operational_holes"][0].update(contract_id="unknown"),
        ):
            malformed = copy.deepcopy(payload)
            mutate(malformed)
            with self.assertRaisesRegex(ValueError, "malformed logical IR"):
                logical_ir_from_dict(malformed)

    def test_forged_review_block_flag_and_unattributed_decision_fail_closed(self):
        report = review_logical_ir(self.document(tests=()))
        payload = logical_review_to_dict(report)
        payload["blocks_compilation"] = False
        with self.assertRaisesRegex(ValueError, "forged"):
            logical_review_from_dict(payload)
        payload = logical_review_to_dict(report)
        payload["findings"][0]["disposition"] = "waived"
        payload["blocks_compilation"] = False
        with self.assertRaisesRegex(ValueError, "reviewer and rationale"):
            logical_review_from_dict(payload)


if __name__ == "__main__":
    unittest.main()

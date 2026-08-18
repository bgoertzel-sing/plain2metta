import json
import unittest
from pathlib import Path

from specatom_hs.logical_ir import (
    FindingCategory,
    canonical_logical_ir,
    logical_ir_from_dict,
    logical_ir_to_dict,
    review_logical_ir,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "logical_ir"


class LogicalIRGoldFixtureTests(unittest.TestCase):
    def load(self, stem):
        payload = json.loads((FIXTURES / f"{stem}.logical-ir.json").read_text())
        return payload, logical_ir_from_dict(payload)

    def test_gold_fixtures_are_canonical_and_retain_complete_clause_provenance(self):
        expected = {
            "auth_service": {f"AUTH-{index}" for index in range(1, 7)},
            "ml_timeseries": {f"ML-{index}" for index in range(1, 6)},
        }
        for stem, clause_ids in expected.items():
            with self.subTest(stem=stem):
                payload, document = self.load(stem)
                self.assertEqual(payload, logical_ir_to_dict(document))
                self.assertEqual(document, logical_ir_from_dict(json.loads(canonical_logical_ir(document))))
                records = document.types + document.contracts + document.obligations + document.dependencies + document.operational_holes
                cited = {clause for record in records for clause in record.source_clause_ids}
                self.assertEqual(clause_ids, cited)
                self.assertEqual(clause_ids, {item.requirement_id for item in document.obligations})
                self.assertTrue(all(item.planned_test_ids for item in document.obligations))

    def test_every_grounded_contract_has_one_explicit_typed_operational_hole(self):
        for stem in ("auth_service", "ml_timeseries"):
            with self.subTest(stem=stem):
                _, document = self.load(stem)
                grounded = {contract.contract_id for contract in document.contracts if contract.requires_grounding}
                holes = [hole.contract_id for hole in document.operational_holes]
                self.assertEqual(grounded, set(holes))
                self.assertEqual(len(holes), len(set(holes)))
                self.assertTrue(all(hole.expected_type and hole.rationale for hole in document.operational_holes))

    def test_ml_operations_are_contracts_with_explicit_grounding_gaps(self):
        _, document = self.load("ml_timeseries")
        expected = {
            "construct_features", "split_and_normalize", "select_hyperparameters",
            "evaluate_once", "choose_model_family",
        }
        self.assertEqual(expected, {contract.name for contract in document.contracts})
        self.assertTrue(all(contract.requires_grounding for contract in document.contracts))

    def test_real_review_replay_retains_unresolved_definition_findings_and_blocks(self):
        expected_missing = {
            "auth_service": {"SupportExportPolicy"},
            "ml_timeseries": {"ModelFamily", "BaselineComparator"},
        }
        for stem, names in expected_missing.items():
            with self.subTest(stem=stem):
                _, document = self.load(stem)
                report = review_logical_ir(document)
                duplicate = review_logical_ir(logical_ir_from_dict(logical_ir_to_dict(document)))
                self.assertEqual(report, duplicate)
                self.assertTrue(report.blocks_compilation)
                missing = {
                    finding.message.rsplit(" ", 1)[-1]
                    for finding in report.findings
                    if finding.category is FindingCategory.MISSING_DEFINITION
                }
                self.assertEqual(names, missing)
                self.assertTrue(all(finding.source_clause_ids for finding in report.findings))
                self.assertFalse(any(finding.category is FindingCategory.UNMARKED_OPERATIONAL_GAP for finding in report.findings))


if __name__ == "__main__":
    unittest.main()

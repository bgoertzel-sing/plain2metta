import unittest

from specatom_hs.backends.petta import emit_reified_atoms
from specatom_hs.passes import compile_source
from specatom_hs.schema import CheckStatus, Role


class MLMethodologyValidationTests(unittest.TestCase):
    def test_ml_fixture_gets_methodology_unknowns_and_exportable_questions(self):
        doc = compile_source(
            "***definitions***\n"
            "- :PriceObservation: is an observed market price at a timestamp.\n"
            "- :ReturnLabel24h: is the 24 hour future return after a prediction time.\n"
            "***functional specifications***\n"
            "- The experiment trains a model to predict :ReturnLabel24h: from price features.\n"
            "- The data is normalized and then split into train, validation, and test.\n"
            "- Hyperparameters are chosen by validation performance.\n"
            "- Final performance is reported on the test split.\n",
            "ml-methodology.plain",
        )

        experiment = next(obj for obj in doc.objects if ("MLTimeSeriesExperiment", obj.id) in obj.facts)
        self.assertTrue(
            any(c.property == "ml-horizon-or-frequency-declared" and c.target_id == experiment.id and c.status == CheckStatus.PASS for c in doc.checks)
        )
        for property_name in {
            "ml-evaluation-metric-declared",
            "ml-reproducibility-evidence-declared",
            "ml-preprocessing-fit-scope-declared",
            "ml-preprocessing-order-reviewed",
            "ml-baseline-comparison-declared",
            "ml-uncertainty-reporting-declared",
        }:
            self.assertTrue(any(c.property == property_name and c.target_id == experiment.id and c.status == CheckStatus.UNKNOWN for c in doc.checks))

        questions = [obj for obj in doc.objects if obj.role == Role.QUESTION_OBJECT]
        self.assertTrue(any(("MissingMethodologyEvidence", q.id, "ml-preprocessing-fit-scope-declared") in q.facts for q in questions))
        self.assertTrue(any(any(fact[0] == "Blocks" and fact[2].startswith("vobl-") for fact in q.facts) for q in questions))

        atoms, refusals = emit_reified_atoms(doc)
        self.assertIn(f"(MLTimeSeriesExperiment {experiment.id})", atoms)
        self.assertTrue(any(atom.startswith("(MissingMethodologyEvidence") for atom in atoms))
        self.assertFalse(any("MissingMethodologyEvidence" in refusal.reason for refusal in refusals))

    def test_explicit_metric_reproducibility_and_train_only_scope_pass(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Train a time-series model to forecast the 24 hour return horizon.\n"
            "- Fit preprocessing on train-only data before validation and test evaluation.\n"
            "- Compare against a naive last-value baseline.\n"
            "- Report RMSE metric with confidence intervals using seed 123 and dataset snapshot v1.\n",
            "ml-methodology-pass.plain",
        )

        for property_name in {
            "ml-evaluation-metric-declared",
            "ml-horizon-or-frequency-declared",
            "ml-reproducibility-evidence-declared",
            "ml-preprocessing-fit-scope-declared",
            "ml-preprocessing-order-reviewed",
            "ml-baseline-comparison-declared",
            "ml-uncertainty-reporting-declared",
        }:
            self.assertTrue(any(c.property == property_name and c.status == CheckStatus.PASS for c in doc.checks), property_name)

    def test_preprocess_then_split_gets_explicit_leakage_review_question(self):
        doc = compile_source(
            "***functional specifications***\n"
            "- Train a model to forecast next-day demand.\n"
            "- Standardize all rows and then split into train, validation, and test.\n",
            "ml-leakage-review.plain",
        )

        check = next(c for c in doc.checks if c.property == "ml-preprocessing-order-reviewed")
        self.assertEqual(check.status, CheckStatus.UNKNOWN)
        self.assertIn("preprocess-then-split", check.evidence)
        self.assertTrue(
            any(
                ("MissingMethodologyEvidence", obj.id, "ml-preprocessing-order-reviewed") in obj.facts
                and any(fact == ("Blocks", obj.id, check.obligation_id) for fact in obj.facts)
                for obj in doc.objects
            )
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from plain_to_metta.compiler import compile_paths


ML_TEXT = """***definitions***
- :PriceObservation: is an observed market price at a timestamp.
- :ReturnLabel24h: is the 24 hour future return after a prediction time.

***functional specifications***
- The experiment trains a model to predict :ReturnLabel24h: from price features.
- The data is normalized and then split into train, validation, and test.
- Hyperparameters are chosen by validation performance.
- Final performance is reported on the test split.
"""


class MLTemplateTests(unittest.TestCase):
    def test_time_series_validation_unknown_for_normalization_scope(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ml.plain"
            path.write_text(ML_TEXT, encoding="utf-8")
            doc = compile_paths([path])
        facts = doc["facts"]
        self.assertTrue(any(f[0] == "MLTimeSeriesExperiment" for f in facts))
        self.assertTrue(any(f[0] == "RequiresValidation" and f[2] == "train-only-preprocessing-fit" for f in facts))
        self.assertTrue(any(f[0] == "CheckStatus" and f[2] == "Unknown" for f in facts))
        self.assertTrue(any(f[0] == "QuestionText" and "normalization parameters" in f[2] for f in facts))
        self.assertFalse(any(f[0] == "CheckStatus" and f[2] == "Fail" for f in facts))


if __name__ == "__main__":
    unittest.main()

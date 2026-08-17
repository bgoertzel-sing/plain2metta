import copy
import unittest
from unittest.mock import patch

from specatom_hs.vertical_acceptance import load_vertical_acceptance, mutation_report

class VerticalAcceptanceTests(unittest.TestCase):
    def setUp(self):
        load_vertical_acceptance.cache_clear()

    def test_five_examples_cover_four_shapes_and_policy_is_blocked(self):
        data = load_vertical_acceptance()
        self.assertEqual(5, len(data["examples"]))
        self.assertGreaterEqual(len({x["shape"] for x in data["examples"]}), 4)
        policy = next(x for x in data["examples"] if x["id"] == "E")
        self.assertEqual("blocked", policy["status"])
        self.assertIn("current policy", policy["holes"])
        numerical = next(x for x in data["examples"] if x["id"] == "A")
        self.assertIn("(x-a)/(b-a)", numerical["source"])
        self.assertIn("monotonicity", numerical["contract"])
        self.assertNotIn("tax", str(numerical).lower())

    def test_relevant_mutants_meet_explicit_threshold_and_survivor_is_reviewed(self):
        report = mutation_report()
        self.assertEqual("8/8", report["kill_ratio"])
        self.assertEqual(["M-A-MESSAGE"], [x["id"] for x in report["survivors"]])

    def test_malformed_duplicate_unknown_and_unresolved_execution_fail_closed(self):
        original = load_vertical_acceptance()
        mutations = []
        item=copy.deepcopy(original); item["schema"]="v2"; mutations.append(item)
        item=copy.deepcopy(original); item["examples"][1]["id"]="A"; mutations.append(item)
        item=copy.deepcopy(original); item["mutants"][0]["example"]="../A"; mutations.append(item)
        item=copy.deepcopy(original); item["examples"][-1]["status"]="executable"; mutations.append(item)
        for malformed in mutations:
            with self.subTest(malformed=malformed), patch("specatom_hs.vertical_acceptance.json.loads", return_value=malformed):
                load_vertical_acceptance.cache_clear()
                with self.assertRaises(ValueError): load_vertical_acceptance()

if __name__ == "__main__": unittest.main()

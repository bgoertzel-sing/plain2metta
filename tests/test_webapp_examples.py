import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_NAMES = (
    "01_hello_world",
    "02_counter",
    "03_bookmark_manager",
    "04_chat_system",
    "05_knowledge_graph",
)
COVERAGE_PROPERTIES = {
    "requirement-has-acceptance-test",
    "acceptance-test-covers-requirement",
}


def load_webapp():
    spec = importlib.util.spec_from_file_location(
        "plain2metta_webapp", ROOT / "webapp" / "app.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


class GraduatedWebAppExamplesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_webapp().test_client()

    def test_example_api_lists_the_graduated_suite(self):
        response = self.client.get("/api/examples")
        self.assertEqual(response.status_code, 200)
        examples = response.get_json()
        self.assertTrue(set(EXAMPLE_NAMES).issubset(examples))
        for name in EXAMPLE_NAMES:
            self.assertEqual(
                examples[name],
                (ROOT / "examples" / f"{name}.plain").read_text(encoding="utf-8"),
            )

    def test_examples_compile_without_fail_checks_and_have_full_coverage(self):
        object_counts = []
        for name in EXAMPLE_NAMES:
            with self.subTest(example=name):
                source = (ROOT / "examples" / f"{name}.plain").read_text(
                    encoding="utf-8"
                )
                response = self.client.post("/api/compile", json={"text": source})
                self.assertEqual(response.status_code, 200)
                result = response.get_json()
                self.assertEqual(result["summary"]["fail"], 0)
                self.assertGreater(result["summary"]["pass"], 0)
                self.assertTrue(result["metta"].strip())
                self.assertTrue(result["diagnostics"].startswith("# SpecAtom-HS Diagnostics"))

                document = json.loads(result["json"])
                object_counts.append(len(document["objects"]))
                coverage_checks = [
                    check
                    for check in document["checks"]
                    if check["property"] in COVERAGE_PROPERTIES
                ]
                self.assertTrue(coverage_checks)
                self.assertEqual(
                    {check["status"] for check in coverage_checks}, {"Pass"}
                )

        self.assertEqual(object_counts, sorted(object_counts))
        self.assertEqual(len(object_counts), len(set(object_counts)))


if __name__ == "__main__":
    unittest.main()

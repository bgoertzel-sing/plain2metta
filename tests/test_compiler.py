from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from plain_to_metta.compiler import compile_paths


TASK_TEXT = """***definitions***
- :Task: describes an activity that needs to be done by :User:.
  :Task: has the following attributes:
  - Name - a short description of :Task:. This is required.
  - Due Date - optional date by which :User: is supposed to complete :Task:.

***functional specifications***
- :User: should be able to add :Task:. Only valid :Task: items can be added.

  ***acceptance tests***
  - Given a valid :Task:, when :User: adds it, then it appears in the task list.
  - Given an invalid :Task:, when :User: adds it, then the system rejects it.
"""


class CompilerTests(unittest.TestCase):
    def compile_text(self, text: str):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "task.plain"
            path.write_text(text, encoding="utf-8")
            return compile_paths([path])

    def test_preserves_source_spans_and_raw_text(self):
        doc = self.compile_text(TASK_TEXT)
        plain_items = [f for f in doc["facts"] if f[0] == "PlainItem"]
        spans = [f for f in doc["facts"] if f[0] == "SourceSpan"]
        self.assertGreaterEqual(len(plain_items), 5)
        self.assertGreaterEqual(len(spans), len(plain_items))
        self.assertTrue(any(":User: should be able to add :Task:" in f[5] for f in plain_items))

    def test_emits_requirement_obligation_action_and_questions(self):
        doc = self.compile_text(TASK_TEXT)
        facts = doc["facts"]
        self.assertTrue(any(f[0] == "Requirement" for f in facts))
        self.assertTrue(any(f[0] == "Obligation" for f in facts))
        self.assertTrue(any(f[0] == "ActionSchema" for f in facts))
        self.assertTrue(any(f[0] == "UndefinedPredicate" and f[1] == "valid-task" for f in facts))
        self.assertTrue(any(f[0] == "QuestionText" and "What makes a Task valid?" in f[2] for f in facts))

    def test_validator_crisp_checks_pass_for_task_example(self):
        doc = self.compile_text(TASK_TEXT)
        statuses = {(f[1], f[2]) for f in doc["facts"] if f[0] == "CheckStatus"}
        self.assertTrue(statuses)
        self.assertFalse(any(status == "Fail" for _, status in statuses))
        self.assertTrue(any(f[0] == "CheckProperty" and f[2] == "all-objects-have-source-or-generator" for f in doc["facts"]))

    def test_single_primary_role_per_object(self):
        doc = self.compile_text(TASK_TEXT)
        roles = {}
        for f in doc["facts"]:
            if f[0] == "PrimaryRole":
                roles.setdefault(f[1], []).append(f[2])
        self.assertTrue(roles)
        self.assertTrue(all(len(v) == 1 for v in roles.values()))


if __name__ == "__main__":
    unittest.main()

import json
import copy
import tempfile
import unittest
from pathlib import Path

from specatom_hs.elaboration_protocol import ProviderProvenance
from specatom_hs.logical_ir import LogicalIRDocument, TypeDeclaration, logical_ir_to_dict
from specatom_hs.logical_ir_backend import (
    LogicalIRBackendConfig, LogicalIRCoordinator, validate_backend_config,
)
from specatom_hs.logical_ir_prompt import ProviderCompletion, RESPONSE_SCHEMA
from specatom_hs.phase3_review import Phase3Decision, Phase3ReviewLog
from specatom_hs.project_repository import FilesystemProjectRepository
from specatom_hs.projects import (
    ApprovalDecision, ArtifactKind, add_artifact, project_from_dict,
    project_to_dict, replace_source, submit_phase3_review,
)


class FakeBackend:
    def __init__(self, document, *, backend="fake", model="model-a", text=None, mutate=None):
        self.calls = []
        self.document = document
        self.backend = backend
        self.model = model
        self.text = text
        self.mutate = mutate

    def generate_logical_ir(self, prompt, config):
        self.calls.append((prompt, config))
        if self.mutate is not None:
            self.mutate()
        text = self.text or json.dumps({"schema": RESPONSE_SCHEMA, "logical_ir": logical_ir_to_dict(self.document)})
        return ProviderCompletion(text, ProviderProvenance(
            self.backend, self.model, "interaction-1", 10, 20, "2026-08-14T13:36:00Z",
        ))


class LogicalIRBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repository = FilesystemProjectRepository(Path(self.temp.name) / "projects")
        project = self.repository.create("demo", "Demo", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "[id:R-1] Work.", (source.ref,))
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = add_artifact(project, ArtifactKind.TEST_SPEC, "[covers:R-1] Verify.", (elaborated.ref,))
        tests = project.current(ArtifactKind.TEST_SPEC)
        project = submit_phase3_review(project, Phase3ReviewLog(elaborated.ref, tests.ref, (
            Phase3Decision(elaborated.ref, ApprovalDecision.APPROVED, "ben", "2026-08-14T13:35:00Z"),
            Phase3Decision(tests.ref, ApprovalDecision.APPROVED, "ben", "2026-08-14T13:35:01Z"),
        )))
        self.repository.save(project)
        self.document = LogicalIRDocument("Demo", (TypeDeclaration("type.Value", "Value", ("R-1",)),), (), (), (), ())
        self.config = LogicalIRBackendConfig("fake", "model-a", 0.0, 4096)

    def tearDown(self):
        self.temp.cleanup()

    def test_one_call_atomically_persists_ir_and_review(self):
        backend = FakeBackend(self.document)
        updated = LogicalIRCoordinator(self.repository, backend, self.config).generate_once("demo", "Stay literal.")
        self.assertEqual(1, len(backend.calls))
        self.assertEqual(self.config, backend.calls[0][1])
        self.assertIn("Stay literal.", backend.calls[0][0].messages[1].content)
        logical = updated.current(ArtifactKind.LOGICAL_IR)
        interaction = updated.current(ArtifactKind.LOGICAL_IR_LOG)
        review = updated.current(ArtifactKind.LOGICAL_REVIEW)
        self.assertIn("interaction-1", interaction.content)
        self.assertEqual(logical.upstream, interaction.upstream)
        self.assertIsNotNone(logical)
        self.assertEqual((logical.ref,), review.upstream)
        self.assertEqual(updated, self.repository.get("demo"))
        self.assertEqual(updated, project_from_dict(project_to_dict(updated)))

    def test_forged_interaction_provenance_or_ir_binding_fails_closed(self):
        updated = LogicalIRCoordinator(
            self.repository, FakeBackend(self.document), self.config,
        ).generate_once("demo")
        payload = project_to_dict(updated)
        for mutation in ("provenance", "logical_ir_hash"):
            forged = copy.deepcopy(payload)
            item = next(x for x in forged["artifacts"] if x["kind"] == "logical-ir-log")
            content = json.loads(item["content"])
            if mutation == "provenance":
                content["provenance"]["input_tokens"] = -1
            else:
                content["logical_ir_hash"] = "sha256:" + "0" * 64
            item["content"] = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            from specatom_hs.projects import _artifact_id, content_sha256
            item["content_hash"] = content_sha256(item["content"])
            item["artifact_id"] = _artifact_id("demo", ArtifactKind.LOGICAL_IR_LOG, item["version"], item["content_hash"])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                project_from_dict(forged)

    def test_failures_make_no_write_and_no_retry(self):
        cases = (
            FakeBackend(self.document, text="not json"),
            FakeBackend(self.document, backend="other"),
            FakeBackend(self.document, model="other"),
        )
        before = self.repository.get("demo")
        for backend in cases:
            with self.subTest(backend=backend), self.assertRaises(ValueError):
                LogicalIRCoordinator(self.repository, backend, self.config).generate_once("demo")
            self.assertEqual(1, len(backend.calls))
            self.assertEqual(before, self.repository.get("demo"))

    def test_adapter_failure_and_stale_reviewed_inputs_make_no_write(self):
        class Failure:
            calls = 0
            def generate_logical_ir(self, prompt, config):
                self.calls += 1
                raise TimeoutError("timeout")
        failure = Failure()
        before = self.repository.get("demo")
        with self.assertRaises(TimeoutError):
            LogicalIRCoordinator(self.repository, failure, self.config).generate_once("demo")
        self.assertEqual(1, failure.calls)
        self.assertEqual(before, self.repository.get("demo"))

        def mutate():
            current = self.repository.get("demo")
            self.repository.save(replace_source(current, "changed source"))
        backend = FakeBackend(self.document, mutate=mutate)
        with self.assertRaisesRegex(ValueError, "changed during"):
            LogicalIRCoordinator(self.repository, backend, self.config).generate_once("demo")
        self.assertEqual(1, len(backend.calls))
        self.assertIsNone(self.repository.get("demo").current(ArtifactKind.LOGICAL_IR))

    def test_configuration_and_adapter_shape_fail_closed(self):
        for config in (
            LogicalIRBackendConfig("", "model"), LogicalIRBackendConfig("fake", ""),
            LogicalIRBackendConfig("fake", "model", float("nan")),
            LogicalIRBackendConfig("fake", "model", 2.1),
            LogicalIRBackendConfig("fake", "model", 0, 0),
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_backend_config(config)
        with self.assertRaises(ValueError):
            LogicalIRCoordinator(self.repository, object(), self.config)

    def test_coordinator_has_no_retry_selection_or_credentials(self):
        coordinator = LogicalIRCoordinator(self.repository, FakeBackend(self.document), self.config)
        for name in ("retry", "fallback", "select_backend", "credentials"):
            self.assertFalse(hasattr(coordinator, name))


if __name__ == "__main__":
    unittest.main()

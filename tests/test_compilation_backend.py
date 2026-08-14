import copy
import json
import tempfile
import unittest
from pathlib import Path

from specatom_hs.compilation_backend import (
    CompilationBackendConfig, CompilationCoordinator, validate_backend_config,
)
from specatom_hs.compilation_prompt import ProviderCompletion, RESPONSE_SCHEMA
from specatom_hs.compiler_output import CompilerOutputBundle, GeneratedFile, compiler_output_to_dict
from specatom_hs.elaboration_protocol import ProviderProvenance
from specatom_hs.logical_ir import Contract, LogicalIRDocument, OperationalHole, RequirementObligation, TypeDeclaration
from specatom_hs.phase3_review import Phase3Decision, Phase3ReviewLog
from specatom_hs.project_repository import FilesystemProjectRepository
from specatom_hs.projects import (
    ApprovalDecision, ArtifactKind, add_artifact, add_logical_ir_document,
    decide, project_from_dict, project_to_dict, replace_source, submit_phase3_review,
)


class FakeBackend:
    def __init__(self, bundle, *, backend="fake", model="model-a", text=None, mutate=None):
        self.calls = []
        self.bundle = bundle
        self.backend = backend
        self.model = model
        self.text = text
        self.mutate = mutate

    def compile(self, prompt, config):
        self.calls.append((prompt, config))
        if self.mutate is not None:
            self.mutate()
        text = self.text or json.dumps({"schema": RESPONSE_SCHEMA, "compiler_output": compiler_output_to_dict(self.bundle)})
        return ProviderCompletion(text, ProviderProvenance(
            self.backend, self.model, "compile-1", 30, 40, "2026-08-14T15:20:00Z",
        ))


class CompilationBackendTests(unittest.TestCase):
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
            Phase3Decision(elaborated.ref, ApprovalDecision.APPROVED, "ben", "2026-08-14T15:19:00Z"),
            Phase3Decision(tests.ref, ApprovalDecision.APPROVED, "ben", "2026-08-14T15:19:01Z"),
        )))
        document = LogicalIRDocument(
            "Demo", (TypeDeclaration("type.Value", "Value", ("R-1",)),),
            (Contract("contract.work", "work", ("Value",), "Value", (), (), (), ("R-1",), True),),
            (RequirementObligation("R-1", ("T-1",), ("R-1",)),), (),
            (OperationalHole("hole.work", "contract.work", "Value", "grounding required", ("R-1",)),),
        )
        project = add_logical_ir_document(project, document)
        logical = project.current(ArtifactKind.LOGICAL_IR)
        project = decide(project, logical.ref, ApprovalDecision.APPROVED, "ben")
        self.repository.save(project)
        self.bundle = CompilerOutputBundle((
            GeneratedFile("demo.metta", "; [id:R-1]\n", ("R-1",)),
            GeneratedFile("tests/test_demo.py", "# [covers:R-1]\n", ("R-1",), ("T-1",)),
        ), "fake:model-a", "minimal")
        self.config = CompilationBackendConfig("fake", "model-a", 0.0, 8192)

    def tearDown(self):
        self.temp.cleanup()

    def test_one_call_atomically_persists_provenance_and_output(self):
        backend = FakeBackend(self.bundle)
        updated = CompilationCoordinator(self.repository, backend, self.config).compile_once("demo", "minimal")
        self.assertEqual(1, len(backend.calls))
        self.assertEqual(self.config, backend.calls[0][1])
        log = updated.current(ArtifactKind.COMPILATION_LOG)
        output = updated.current(ArtifactKind.COMPILER_OUTPUT)
        self.assertIn("compile-1", log.content)
        self.assertEqual(output.content_hash, json.loads(log.content)["compiler_output_hash"])
        self.assertEqual(updated, self.repository.get("demo"))
        self.assertEqual(updated, project_from_dict(project_to_dict(updated)))

    def test_failures_make_no_write_and_no_retry(self):
        before = self.repository.get("demo")
        for backend in (
            FakeBackend(self.bundle, text="not json"),
            FakeBackend(self.bundle, backend="other"),
            FakeBackend(self.bundle, model="other"),
        ):
            with self.subTest(backend=backend), self.assertRaises(ValueError):
                CompilationCoordinator(self.repository, backend, self.config).compile_once("demo", "minimal")
            self.assertEqual(1, len(backend.calls))
            self.assertEqual(before, self.repository.get("demo"))

    def test_adapter_failure_and_changed_inputs_make_no_partial_write(self):
        class Failure:
            calls = 0
            def compile(self, prompt, config):
                self.calls += 1
                raise TimeoutError("timeout")
        failure = Failure()
        before = self.repository.get("demo")
        with self.assertRaises(TimeoutError):
            CompilationCoordinator(self.repository, failure, self.config).compile_once("demo", "minimal")
        self.assertEqual(1, failure.calls)
        self.assertEqual(before, self.repository.get("demo"))

        def mutate():
            self.repository.save(replace_source(self.repository.get("demo"), "changed"))
        backend = FakeBackend(self.bundle, mutate=mutate)
        with self.assertRaises(ValueError):
            CompilationCoordinator(self.repository, backend, self.config).compile_once("demo", "minimal")
        self.assertEqual(1, len(backend.calls))
        changed = self.repository.get("demo")
        self.assertIsNone(changed.current(ArtifactKind.COMPILATION_LOG))
        self.assertIsNone(changed.current(ArtifactKind.COMPILER_OUTPUT))

    def test_forged_log_fails_reload(self):
        updated = CompilationCoordinator(
            self.repository, FakeBackend(self.bundle), self.config,
        ).compile_once("demo", "minimal")
        payload = project_to_dict(updated)
        forged = copy.deepcopy(payload)
        item = next(x for x in forged["artifacts"] if x["kind"] == "compilation-log")
        content = json.loads(item["content"])
        content["provenance"]["input_tokens"] = -1
        item["content"] = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        from specatom_hs.projects import _artifact_id, content_sha256
        item["content_hash"] = content_sha256(item["content"])
        item["artifact_id"] = _artifact_id("demo", ArtifactKind.COMPILATION_LOG, item["version"], item["content_hash"])
        with self.assertRaises(ValueError):
            project_from_dict(forged)

        partial = copy.deepcopy(payload)
        partial["artifacts"] = [x for x in partial["artifacts"] if x["kind"] != "compiler-output"]
        with self.assertRaisesRegex(ValueError, "lacks compiler output"):
            project_from_dict(partial)

    def test_configuration_and_coordinator_surface_fail_closed(self):
        for config in (
            CompilationBackendConfig("", "model"), CompilationBackendConfig("fake", ""),
            CompilationBackendConfig("fake", "model", float("nan")),
            CompilationBackendConfig("fake", "model", 2.1),
            CompilationBackendConfig("fake", "model", 0, 0),
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_backend_config(config)
        with self.assertRaises(ValueError):
            CompilationCoordinator(self.repository, object(), self.config)
        coordinator = CompilationCoordinator(self.repository, FakeBackend(self.bundle), self.config)
        for name in ("retry", "fallback", "select_backend", "credentials", "publish", "execute"):
            self.assertFalse(hasattr(coordinator, name))


if __name__ == "__main__":
    unittest.main()

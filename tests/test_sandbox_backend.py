import copy
import tempfile
import unittest
from pathlib import Path

from specatom_hs.compiler_output import CompilerOutputBundle, GeneratedFile
from specatom_hs.logical_ir import Contract, LogicalIRDocument, OperationalHole, RequirementObligation, TypeDeclaration
from specatom_hs.phase3_review import Phase3Decision, Phase3ReviewLog
from specatom_hs.project_repository import FilesystemProjectRepository
from specatom_hs.projects import (
    ApprovalDecision, ArtifactKind, add_artifact, add_compiler_output,
    add_logical_ir_document, add_sandbox_handoff, decide, replace_source,
    submit_phase3_review,
)
from specatom_hs.sandbox_backend import SandboxAdapterConfig, SandboxCoordinator, validate_adapter_config
from specatom_hs.sandbox_handoff import SandboxHandoff, SandboxLimits
from specatom_hs.sandbox_protocol import SandboxTestResult, TestCaseResult, sandbox_request_hash, test_result_to_dict


class FakeAdapter:
    def __init__(self, result, *, mutate=None, response=None):
        self.result = result
        self.mutate = mutate
        self.response = response
        self.calls = []

    def execute(self, request, config):
        self.calls.append((copy.deepcopy(request), config))
        if self.mutate:
            self.mutate()
        return self.response if self.response is not None else test_result_to_dict(self.result)


class SandboxBackendTests(unittest.TestCase):
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
            Phase3Decision(elaborated.ref, ApprovalDecision.APPROVED, "ben", "2026-08-14T16:00:00Z"),
            Phase3Decision(tests.ref, ApprovalDecision.APPROVED, "ben", "2026-08-14T16:00:01Z"),
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
        project = add_compiler_output(project, CompilerOutputBundle((
            GeneratedFile("demo.metta", "; inert\n", ("R-1",)),
            GeneratedFile("tests/test_demo.py", "pass\n", ("R-1",), ("T-1",)),
        ), "compiler:model"))
        output = project.current(ArtifactKind.COMPILER_OUTPUT)
        project = decide(project, output.ref, ApprovalDecision.APPROVED, "ben")
        self.handoff = SandboxHandoff(
            "sha256:" + "a" * 64, ("python", "-m", "pytest", "-q"),
            ("demo.metta", "tests/test_demo.py"), SandboxLimits(10, 256, 30),
        )
        project = add_sandbox_handoff(project, self.handoff)
        self.repository.save(project)
        self.config = SandboxAdapterConfig("isolated:v1")
        self.result = SandboxTestResult(
            sandbox_request_hash(self.handoff), "isolated:v1",
            (TestCaseResult("T-1", "passed", 12, "ok\n", "", ("R-1",)),),
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_one_call_exact_envelope_and_atomic_admission(self):
        adapter = FakeAdapter(self.result)
        updated = SandboxCoordinator(self.repository, adapter, self.config).execute_once("demo")
        self.assertEqual(1, len(adapter.calls))
        request, config = adapter.calls[0]
        self.assertEqual("sandbox-test-request", request["kind"])
        self.assertFalse(request["handoff"]["executed"])
        self.assertEqual(self.config, config)
        result = updated.current(ArtifactKind.TEST_RESULT)
        handoff = updated.current(ArtifactKind.SANDBOX_HANDOFF)
        self.assertEqual((handoff.ref,), result.upstream)
        self.assertEqual(updated, self.repository.get("demo"))

    def test_malformed_or_misattributed_return_makes_no_write_or_retry(self):
        before = self.repository.get("demo")
        cases = (
            FakeAdapter(self.result, response={"kind": "sandbox-test-result"}),
            FakeAdapter(SandboxTestResult(self.result.request_hash, "other", self.result.tests)),
            FakeAdapter(SandboxTestResult("sha256:" + "b" * 64, "isolated:v1", self.result.tests)),
        )
        for adapter in cases:
            with self.subTest(adapter=adapter), self.assertRaises(ValueError):
                SandboxCoordinator(self.repository, adapter, self.config).execute_once("demo")
            self.assertEqual(1, len(adapter.calls))
            self.assertEqual(before, self.repository.get("demo"))

    def test_adapter_failure_and_concurrent_change_make_no_partial_write(self):
        class Failure:
            calls = 0
            def execute(self, request, config):
                self.calls += 1
                raise TimeoutError("sandbox timed out")
        failure = Failure()
        before = self.repository.get("demo")
        with self.assertRaises(TimeoutError):
            SandboxCoordinator(self.repository, failure, self.config).execute_once("demo")
        self.assertEqual(1, failure.calls)
        self.assertEqual(before, self.repository.get("demo"))

        def mutate():
            self.repository.save(replace_source(self.repository.get("demo"), "changed"))
        adapter = FakeAdapter(self.result, mutate=mutate)
        with self.assertRaisesRegex(ValueError, "sandbox handoff"):
            SandboxCoordinator(self.repository, adapter, self.config).execute_once("demo")
        self.assertEqual(1, len(adapter.calls))
        self.assertIsNone(self.repository.get("demo").current(ArtifactKind.TEST_RESULT))

    def test_configuration_and_adapter_contract_fail_closed(self):
        for config in (None, SandboxAdapterConfig(""), SandboxAdapterConfig("  ")):
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_adapter_config(config)
        with self.assertRaisesRegex(ValueError, "execute"):
            SandboxCoordinator(self.repository, object(), self.config)

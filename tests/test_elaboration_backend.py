import tempfile
import unittest
from pathlib import Path

from specatom_hs.elaboration_backend import (
    ElaborationBackendConfig, ElaborationCoordinator, validate_backend_config,
)
from specatom_hs.elaboration_prompt import ProviderCompletion
from specatom_hs.elaboration_protocol import ProviderProvenance
from specatom_hs.project_repository import FilesystemProjectRepository
from specatom_hs.projects import ArtifactKind


class FakeBackend:
    def __init__(self, *, provenance_backend="fake", model="model-a", stale=False):
        self.calls = []
        self.provenance_backend = provenance_backend
        self.model = model
        self.stale = stale

    def elaborate(self, prompt, config):
        self.calls.append((prompt, config))
        text = '{"schema":"plain2metta-elaboration-response/v1","elaborated_spec":"***requirements***\\n","test_spec":"***acceptance tests***\\n"}'
        if self.stale:
            text = '{"schema":"wrong","elaborated_spec":"x","test_spec":"y"}'
        return ProviderCompletion(
            text, ProviderProvenance(self.provenance_backend, self.model, "interaction-1", 10, 20, "2026-08-14T11:08:00Z"),
        )


class ElaborationBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repository = FilesystemProjectRepository(Path(self.temp.name) / "projects")
        self.repository.create("demo", "Demo", "***notes***\n")
        self.config = ElaborationBackendConfig("fake", "model-a", 0.2, 4096)

    def tearDown(self):
        self.temp.cleanup()

    def test_one_configured_call_is_admitted_and_persisted(self):
        backend = FakeBackend()
        updated = ElaborationCoordinator(self.repository, backend, self.config).elaborate_once(
            "demo", "Reviewable English.", "notes",
        )
        self.assertEqual(1, len(backend.calls))
        prompt, config = backend.calls[0]
        self.assertEqual(self.config, config)
        self.assertIn("Reviewable English.", prompt.messages[1].content)
        self.assertIsNotNone(updated.current(ArtifactKind.ELABORATION_LOG))
        self.assertEqual(updated, self.repository.get("demo"))

    def test_stale_or_misattributed_response_fails_without_retry_or_write(self):
        before = self.repository.get("demo")
        for backend in (FakeBackend(stale=True), FakeBackend(provenance_backend="other"), FakeBackend(model="other-model")):
            with self.subTest(backend=backend), self.assertRaises(ValueError):
                ElaborationCoordinator(self.repository, backend, self.config).elaborate_once("demo")
            self.assertEqual(1, len(backend.calls))
            self.assertEqual(before, self.repository.get("demo"))

    def test_adapter_failure_propagates_without_state_change(self):
        class FailedBackend:
            calls = 0
            def elaborate(self, request, config):
                self.calls += 1
                raise TimeoutError("adapter timeout")
        backend = FailedBackend()
        before = self.repository.get("demo")
        with self.assertRaises(TimeoutError):
            ElaborationCoordinator(self.repository, backend, self.config).elaborate_once("demo")
        self.assertEqual(1, backend.calls)
        self.assertEqual(before, self.repository.get("demo"))

    def test_configuration_and_adapter_shape_fail_closed(self):
        for config in (
            ElaborationBackendConfig("", "model"), ElaborationBackendConfig("fake", "", 0),
            ElaborationBackendConfig("fake", "model", float("nan")), ElaborationBackendConfig("fake", "model", 2.1),
            ElaborationBackendConfig("fake", "model", 0, 0),
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_backend_config(config)
        with self.assertRaises(ValueError):
            ElaborationCoordinator(self.repository, object(), self.config)

    def test_coordinator_exposes_no_retry_or_provider_selection(self):
        coordinator = ElaborationCoordinator(self.repository, FakeBackend(), self.config)
        for name in ("retry", "fallback", "select_backend", "credentials"):
            self.assertFalse(hasattr(coordinator, name))


if __name__ == "__main__":
    unittest.main()

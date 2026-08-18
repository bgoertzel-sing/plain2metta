import json
import unittest
from dataclasses import replace

from specatom_hs.compilation_prompt import (
    RESPONSE_SCHEMA, CompilationRequest, ProviderCompletion,
    build_compilation_prompt, build_compilation_request, compilation_prompt_to_dict,
    parse_compilation_completion,
)
from specatom_hs.compiler_output import CompilerOutputBundle, GeneratedFile, compiler_output_to_dict
from specatom_hs.elaboration_protocol import ProviderProvenance
from specatom_hs.logical_ir import Contract, LogicalIRDocument, OperationalHole, RequirementObligation, TypeDeclaration
from specatom_hs.phase3_review import Phase3Decision, Phase3ReviewLog
from specatom_hs.projects import (
    ApprovalDecision, ArtifactKind, ArtifactRef, add_artifact,
    add_logical_ir_document, content_sha256, create_project, decide,
    replace_source, submit_phase3_review,
)


class CompilationPromptTests(unittest.TestCase):
    def setUp(self):
        spec = "[id:R-1] Work."
        tests = "[covers:R-1] Verify."
        logical = '{"schema":"plain2metta-logical-ir/v1"}'
        self.request = CompilationRequest(
            ArtifactRef("reviewed-spec:v1", content_sha256(spec)), spec,
            ArtifactRef("reviewed-tests:v1", content_sha256(tests)), tests,
            ArtifactRef("logical-ir:v1", content_sha256(logical)), logical,
            "Keep the implementation minimal.",
        )
        self.provenance = ProviderProvenance("fake", "model-a", "i-1", 11, 22, "2026-08-14T15:11:00Z")
        self.bundle = CompilerOutputBundle((
            GeneratedFile("demo.metta", "; [id:R-1]\n", ("R-1",)),
            GeneratedFile("tests/test_demo.py", "# [covers:R-1]\n", ("R-1",), ("T-1",)),
        ), "fake:model-a", self.request.guidance)

    def test_prompt_binds_all_three_exact_approved_inputs(self):
        encoded = compilation_prompt_to_dict(build_compilation_prompt(self.request))
        self.assertEqual("plain2metta-compilation-prompt/v1", encoded["schema"])
        user = encoded["messages"][1]["content"]
        for identity in ("reviewed-spec:v1", "reviewed-tests:v1", "logical-ir:v1"):
            self.assertIn(identity, user)
        self.assertFalse(encoded["response_schema"]["additionalProperties"])

    def admitted_project(self):
        project = create_project("demo", "Demo", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "[id:R-1] Work.", (source.ref,))
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = add_artifact(project, ArtifactKind.TEST_SPEC, "[covers:R-1] Verify.", (elaborated.ref,))
        tests = project.current(ArtifactKind.TEST_SPEC)
        log = Phase3ReviewLog(elaborated.ref, tests.ref, (
            Phase3Decision(elaborated.ref, ApprovalDecision.APPROVED, "ben", "2026-08-14T15:11:00Z"),
            Phase3Decision(tests.ref, ApprovalDecision.APPROVED, "ben", "2026-08-14T15:11:01Z"),
        ))
        project = submit_phase3_review(project, log)
        document = LogicalIRDocument(
            "Demo", (TypeDeclaration("type.Value", "Value", ("R-1",)),),
            (Contract("contract.work", "work", ("Value",), "Value", (), (), (), ("R-1",), True),),
            (RequirementObligation("R-1", ("T-1",), ("R-1",)),), (),
            (OperationalHole("hole.work", "contract.work", "Value", "grounding required", ("R-1",)),),
        )
        project = add_logical_ir_document(project, document)
        logical = project.current(ArtifactKind.LOGICAL_IR)
        return decide(project, logical.ref, ApprovalDecision.APPROVED, "ben")

    def test_request_builder_requires_exact_current_phase4_admission(self):
        project = self.admitted_project()
        request = build_compilation_request(project, "minimal")
        self.assertEqual(project.current(ArtifactKind.LOGICAL_IR).ref, request.logical_ir)
        self.assertEqual("minimal", request.guidance)
        with self.assertRaises(ValueError):
            build_compilation_request(replace_source(project, "changed"))

    def test_valid_completion_is_inert_strict_and_request_bound(self):
        text = json.dumps({"schema": RESPONSE_SCHEMA, "compiler_output": compiler_output_to_dict(self.bundle)})
        response = parse_compilation_completion(self.request, ProviderCompletion(text, self.provenance))
        self.assertEqual(self.bundle, response.compiler_output)
        self.assertEqual(self.provenance, response.provenance)

    def test_mutated_input_or_prompt_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "exact artifact hash"):
            build_compilation_prompt(replace(self.request, logical_ir_text="changed"))
        prompt = build_compilation_prompt(self.request)
        with self.assertRaises(ValueError):
            compilation_prompt_to_dict(replace(prompt, request_hash="sha256:" + "0" * 64))

    def test_malformed_expanded_executed_and_duplicate_json_fail_closed(self):
        valid = compiler_output_to_dict(self.bundle)
        bad = [
            "not json",
            json.dumps({"schema": RESPONSE_SCHEMA}),
            json.dumps({"schema": RESPONSE_SCHEMA, "compiler_output": valid, "extra": 1}),
            json.dumps({"schema": RESPONSE_SCHEMA, "compiler_output": {**valid, "executed": True}}),
            '{"schema":"%s","schema":"%s","compiler_output":{}}' % (RESPONSE_SCHEMA, RESPONSE_SCHEMA),
        ]
        for text in bad:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_compilation_completion(self.request, ProviderCompletion(text, self.provenance))

    def test_forged_provider_or_guidance_attribution_fails_closed(self):
        for bundle in (
            replace(self.bundle, compiler="other:model"),
            replace(self.bundle, guidance="different"),
        ):
            text = json.dumps({"schema": RESPONSE_SCHEMA, "compiler_output": compiler_output_to_dict(bundle)})
            with self.assertRaisesRegex(ValueError, "exact request and provider"):
                parse_compilation_completion(self.request, ProviderCompletion(text, self.provenance))


if __name__ == "__main__":
    unittest.main()

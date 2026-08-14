import copy
import unittest

from specatom_hs.projects import (
    ApprovalDecision,
    ArtifactKind,
    ArtifactState,
    Project,
    add_artifact,
    add_compiler_output,
    add_sandbox_handoff,
    add_test_result,
    add_logical_ir,
    add_logical_ir_document,
    admit_compilation,
    annotate,
    create_project,
    decide,
    decide_logical_finding,
    project_from_dict,
    project_to_dict,
    replace_source,
)
from specatom_hs.logical_ir import (
    Contract, FindingDisposition, LogicalIRDocument, OperationalHole, RequirementObligation, TypeDeclaration,
)
from specatom_hs.compiler_output import CompilerOutputBundle, GeneratedFile
from specatom_hs.sandbox_handoff import SandboxHandoff, SandboxLimits
from specatom_hs.sandbox_protocol import (
    SandboxTestResult, TestCaseResult, sandbox_request_hash, sandbox_request_to_dict,
)


class ProjectModelTests(unittest.TestCase):
    def populated(self):
        project = create_project("demo", "Demo", "***requirements***\n- old\n")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "elaborated", [source.ref])
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = add_artifact(project, ArtifactKind.TEST_SPEC, "tests", [elaborated.ref])
        return project

    def test_project_and_artifacts_are_immutable_and_content_addressed(self):
        project = create_project("demo", "Demo", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        self.assertTrue(source.content_hash.startswith("sha256:"))
        with self.assertRaises(AttributeError):
            project.name = "changed"

    def test_derived_artifact_requires_exact_current_upstream_hash(self):
        project = create_project("demo", "Demo", "source")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        bad_ref = type(source.ref)(source.artifact_id, "sha256:bad")
        with self.assertRaisesRegex(ValueError, "hash-mismatched"):
            add_artifact(project, ArtifactKind.ELABORATED_SPEC, "output", [bad_ref])

    def test_approval_binds_exact_artifact_version(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        approved = decide(project, elaborated.ref, ApprovalDecision.APPROVED, "ben", "reviewed")
        self.assertEqual(ApprovalDecision.APPROVED, approved.approvals[0].decision)
        with self.assertRaisesRegex(ValueError, "reviewer"):
            decide(project, elaborated.ref, ApprovalDecision.APPROVED)

    def test_source_mutation_transitively_invalidates_derived_state_and_approval(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = decide(project, elaborated.ref, ApprovalDecision.APPROVED, "ben")
        changed = replace_source(project, "***requirements***\n- new\n")
        self.assertEqual(2, changed.current(ArtifactKind.ORIGINAL_SPEC).version)
        self.assertIsNone(changed.current(ArtifactKind.ELABORATED_SPEC))
        self.assertIsNone(changed.current(ArtifactKind.TEST_SPEC))
        self.assertTrue(all(a.state is ArtifactState.INVALIDATED for a in changed.artifacts[:-1]))
        self.assertEqual(ApprovalDecision.INVALIDATED, changed.approvals[0].decision)

    def test_identical_source_is_a_noop(self):
        project = create_project("demo", "Demo", "source")
        self.assertIs(project, replace_source(project, "source"))

    def test_new_derived_version_invalidates_old_version_and_downstream(self):
        project = self.populated()
        old_elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = decide(project, old_elaborated.ref, ApprovalDecision.APPROVED, "ben")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        changed = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "revised", [source.ref])
        self.assertEqual(2, changed.current(ArtifactKind.ELABORATED_SPEC).version)
        self.assertIsNone(changed.current(ArtifactKind.TEST_SPEC))
        self.assertEqual(ArtifactState.INVALIDATED, changed.artifact(old_elaborated.artifact_id).state)
        self.assertEqual(ApprovalDecision.INVALIDATED, changed.approvals[0].decision)

    def test_round_trip_is_stable(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = decide(project, elaborated.ref, ApprovalDecision.CHANGES_REQUESTED, "reviewer", "clarify")
        project = annotate(project, elaborated.ref, "reviewer", "Clarify this section.", "section:requirements")
        self.assertEqual(project, project_from_dict(project_to_dict(project)))

    def test_annotations_bind_exact_current_artifact_and_survive_invalidation_as_history(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = annotate(project, elaborated.ref, "ben", "Define the boundary.", "item:PRED-1")
        self.assertEqual("item:PRED-1", project.annotations[0].target)
        changed = replace_source(project, "changed")
        self.assertEqual(project.annotations, changed.annotations)
        with self.assertRaisesRegex(ValueError, "exact current"):
            annotate(changed, elaborated.ref, "ben", "stale")

    def test_annotations_reject_malformed_review_fields(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        for reviewer, comment, target in (("", "note", None), ("ben", " ", None), ("ben", "note", " ")):
            with self.subTest(reviewer=reviewer, comment=comment, target=target):
                with self.assertRaises(ValueError):
                    annotate(project, elaborated.ref, reviewer, comment, target)

    def test_logical_ir_requires_both_exact_current_approvals(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        tests = project.current(ArtifactKind.TEST_SPEC)
        with self.assertRaisesRegex(ValueError, "explicit approval"):
            add_logical_ir(project, "logical")
        project = decide(project, elaborated.ref, ApprovalDecision.APPROVED, "ben")
        with self.assertRaisesRegex(ValueError, "explicit approval"):
            add_logical_ir(project, "logical")
        project = decide(project, tests.ref, ApprovalDecision.APPROVED, "ben")
        project = add_logical_ir(project, "logical")
        logical = project.current(ArtifactKind.LOGICAL_IR)
        self.assertEqual((elaborated.ref, tests.ref), logical.upstream)

    def test_generic_artifact_api_cannot_bypass_logical_ir_review_gate(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        with self.assertRaisesRegex(ValueError, "add_logical_ir"):
            add_artifact(project, ArtifactKind.LOGICAL_IR, "logical", [elaborated.ref])

    def test_structured_logical_ir_persists_hash_bound_review(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        tests = project.current(ArtifactKind.TEST_SPEC)
        project = decide(project, elaborated.ref, ApprovalDecision.APPROVED, "ben")
        project = decide(project, tests.ref, ApprovalDecision.APPROVED, "ben")
        document = LogicalIRDocument(
            "Demo", (TypeDeclaration("type.Value", "Value", ("REQ-1",)),),
            (Contract("contract.work", "work", ("Value",), "Value", (), (), (), ("REQ-1",), True),),
            (RequirementObligation("REQ-1", ("TEST-1",), ("REQ-1",)),), (),
            (OperationalHole("hole.work", "contract.work", "Value", "grounding required", ("REQ-1",)),),
        )
        project = add_logical_ir_document(project, document)
        logical = project.current(ArtifactKind.LOGICAL_IR)
        review = project.current(ArtifactKind.LOGICAL_REVIEW)
        self.assertEqual((logical.ref,), review.upstream)
        self.assertEqual(project, project_from_dict(project_to_dict(project)))

    def test_deserialization_rejects_logical_review_bound_to_forged_hash(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        tests = project.current(ArtifactKind.TEST_SPEC)
        project = decide(project, elaborated.ref, ApprovalDecision.APPROVED, "ben")
        project = decide(project, tests.ref, ApprovalDecision.APPROVED, "ben")
        document = LogicalIRDocument(
            "Demo", (TypeDeclaration("type.Value", "Value", ("REQ-1",)),), (), (), (), (),
        )
        payload = project_to_dict(add_logical_ir_document(project, document))
        review = next(item for item in payload["artifacts"] if item["kind"] == "logical-review")
        import json
        review_payload = json.loads(review["content"])
        review_payload["logical_ir_hash"] = "sha256:" + "0" * 64
        review["content"] = json.dumps(review_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        from specatom_hs.projects import content_sha256
        review["content_hash"] = content_sha256(review["content"])
        # Its content-derived ID also changes; this leaves a structurally plausible forgery.
        from specatom_hs.projects import _artifact_id
        review["artifact_id"] = _artifact_id("demo", ArtifactKind.LOGICAL_REVIEW, review["version"], review["content_hash"])
        with self.assertRaisesRegex(ValueError, "logical review hash mismatch"):
            project_from_dict(payload)

    def test_persisted_finding_transition_and_exact_compile_admission(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        tests = project.current(ArtifactKind.TEST_SPEC)
        project = decide(project, elaborated.ref, ApprovalDecision.APPROVED, "ben")
        project = decide(project, tests.ref, ApprovalDecision.APPROVED, "ben")
        document = LogicalIRDocument(
            "Demo", (TypeDeclaration("type.Value", "Value", ("REQ-1",)),), (),
            (RequirementObligation("REQ-1", (), ("REQ-1",)),), (), (),
        )
        project = add_logical_ir_document(project, document)
        logical = project.current(ArtifactKind.LOGICAL_IR)
        first_review = project.current(ArtifactKind.LOGICAL_REVIEW)
        with self.assertRaisesRegex(ValueError, "explicit approval"):
            admit_compilation(project)
        project = decide(project, logical.ref, ApprovalDecision.APPROVED, "ben")
        with self.assertRaisesRegex(ValueError, "unresolved critical"):
            admit_compilation(project)
        import json
        from specatom_hs.logical_ir import logical_review_from_dict
        report = logical_review_from_dict(json.loads(first_review.content))
        project = decide_logical_finding(
            project, report.findings[0].finding_id, FindingDisposition.WAIVED,
            "ben", "accepted uncovered requirement for this verification slice",
        )
        current_review = project.current(ArtifactKind.LOGICAL_REVIEW)
        self.assertEqual(2, current_review.version)
        self.assertEqual(ArtifactState.INVALIDATED, project.artifact(first_review.artifact_id).state)
        self.assertEqual(logical, admit_compilation(project))
        self.assertEqual(project, project_from_dict(project_to_dict(project)))

    def admitted_project(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        tests = project.current(ArtifactKind.TEST_SPEC)
        project = decide(project, elaborated.ref, ApprovalDecision.APPROVED, "ben")
        project = decide(project, tests.ref, ApprovalDecision.APPROVED, "ben")
        document = LogicalIRDocument(
            "Demo", (TypeDeclaration("type.Value", "Value", ("REQ-1",)),),
            (Contract("contract.work", "work", ("Value",), "Value", (), (), (), ("REQ-1",), True),),
            (RequirementObligation("REQ-1", ("TEST-1",), ("REQ-1",)),), (),
            (OperationalHole("hole.work", "contract.work", "Value", "grounding required", ("REQ-1",)),),
        )
        project = add_logical_ir_document(project, document)
        logical = project.current(ArtifactKind.LOGICAL_IR)
        return decide(project, logical.ref, ApprovalDecision.APPROVED, "ben")

    def test_compiler_output_is_inert_persisted_and_bound_to_admitted_ir(self):
        project = self.admitted_project()
        logical = project.current(ArtifactKind.LOGICAL_IR)
        bundle = CompilerOutputBundle((
            GeneratedFile("demo.metta", "; generated, not executed\n", ("REQ-1",)),
            GeneratedFile("tests/test_demo.py", "raise RuntimeError('must not run')\n", ("REQ-1",), ("TEST-1",)),
        ), "model:test")
        project = add_compiler_output(project, bundle)
        output = project.current(ArtifactKind.COMPILER_OUTPUT)
        self.assertEqual((logical.ref,), output.upstream)
        self.assertIn('"executed":false', output.content)
        self.assertEqual(project, project_from_dict(project_to_dict(project)))

    def test_compiler_output_requires_admission_and_cannot_use_generic_api(self):
        project = self.populated()
        bundle = CompilerOutputBundle((GeneratedFile("demo.metta", "", ("REQ-1",)),), "model:test")
        with self.assertRaises(ValueError):
            add_compiler_output(project, bundle)
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        with self.assertRaisesRegex(ValueError, "add_compiler_output"):
            add_artifact(project, ArtifactKind.COMPILER_OUTPUT, "{}", (source.ref,))

    def test_compiler_output_rejects_unsafe_or_untraceable_files(self):
        project = self.admitted_project()
        for generated in (
            GeneratedFile("../escape.py", "", ("REQ-1",)),
            GeneratedFile("demo.py", "", ()),
        ):
            with self.subTest(path=generated.path), self.assertRaises(ValueError):
                add_compiler_output(project, CompilerOutputBundle((generated,), "model:test"))

    def test_deserialization_rejects_executed_or_forged_compiler_output(self):
        import json
        from specatom_hs.projects import _artifact_id, content_sha256
        project = add_compiler_output(
            self.admitted_project(),
            CompilerOutputBundle((GeneratedFile("demo.metta", "", ("REQ-1",)),), "model:test"),
        )
        for mutation in ("executed", "unknown"):
            payload = project_to_dict(project)
            output = next(item for item in payload["artifacts"] if item["kind"] == "compiler-output")
            body = json.loads(output["content"])
            if mutation == "executed":
                body["executed"] = True
            else:
                body["command"] = "python demo.py"
            output["content"] = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            output["content_hash"] = content_sha256(output["content"])
            output["artifact_id"] = _artifact_id("demo", ArtifactKind.COMPILER_OUTPUT, 1, output["content_hash"])
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "invalid compiler output"):
                project_from_dict(payload)

    def test_revoking_logical_ir_approval_invalidates_compiler_output(self):
        project = add_compiler_output(
            self.admitted_project(),
            CompilerOutputBundle((GeneratedFile("demo.metta", "", ("REQ-1",)),), "model:test"),
        )
        logical = project.current(ArtifactKind.LOGICAL_IR)
        output = project.current(ArtifactKind.COMPILER_OUTPUT)
        changed = decide(project, logical.ref, ApprovalDecision.CHANGES_REQUESTED, "ben", "revise IR")
        self.assertIsNone(changed.current(ArtifactKind.COMPILER_OUTPUT))
        self.assertEqual(ArtifactState.INVALIDATED, changed.artifact(output.artifact_id).state)

    def approved_output_project(self):
        project = add_compiler_output(
            self.admitted_project(),
            CompilerOutputBundle((
                GeneratedFile("demo.metta", "; inert\n", ("REQ-1",)),
                GeneratedFile("tests/test_demo.py", "pass\n", ("REQ-1",), ("TEST-1",)),
            ), "model:test"),
        )
        output = project.current(ArtifactKind.COMPILER_OUTPUT)
        return decide(project, output.ref, ApprovalDecision.APPROVED, "ben", "reviewed generated files")

    def handoff(self):
        return SandboxHandoff(
            "sha256:" + "a" * 64,
            ("python", "-m", "pytest", "-q"),
            ("demo.metta", "tests/test_demo.py"),
            SandboxLimits(10, 256, 30),
        )

    def test_approved_output_creates_inert_exact_sandbox_handoff(self):
        project = self.approved_output_project()
        output = project.current(ArtifactKind.COMPILER_OUTPUT)
        project = add_sandbox_handoff(project, self.handoff())
        handoff = project.current(ArtifactKind.SANDBOX_HANDOFF)
        self.assertEqual((output.ref,), handoff.upstream)
        self.assertIn('"executed":false', handoff.content)
        self.assertIn('"opt_in_required":true', handoff.content)
        self.assertEqual(project, project_from_dict(project_to_dict(project)))

    def test_handoff_requires_exact_output_approval_and_file_set(self):
        unapproved = add_compiler_output(
            self.admitted_project(),
            CompilerOutputBundle((GeneratedFile("demo.metta", "", ("REQ-1",)),), "model:test"),
        )
        with self.assertRaisesRegex(ValueError, "explicit approval"):
            add_sandbox_handoff(unapproved, self.handoff())
        approved = self.approved_output_project()
        bad = SandboxHandoff(self.handoff().image_digest, ("pytest",), ("demo.metta",), self.handoff().limits)
        with self.assertRaisesRegex(ValueError, "exactly match"):
            add_sandbox_handoff(approved, bad)
        output = approved.current(ArtifactKind.COMPILER_OUTPUT)
        with self.assertRaisesRegex(ValueError, "add_sandbox_handoff"):
            add_artifact(approved, ArtifactKind.SANDBOX_HANDOFF, "{}", (output.ref,))

    def test_handoff_rejects_weak_isolation_execution_and_forgery(self):
        import json
        from specatom_hs.projects import _artifact_id, content_sha256
        project = add_sandbox_handoff(self.approved_output_project(), self.handoff())
        for mutation in ("executed", "network", "files", "unknown"):
            payload = project_to_dict(project)
            artifact = next(item for item in payload["artifacts"] if item["kind"] == "sandbox-handoff")
            body = json.loads(artifact["content"])
            if mutation == "executed":
                body["executed"] = True
            elif mutation == "network":
                body["isolation"]["network"] = True
            elif mutation == "files":
                body["files"] = ["demo.metta"]
            else:
                body["environment"] = {"TOKEN": "secret"}
            artifact["content"] = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            artifact["content_hash"] = content_sha256(artifact["content"])
            artifact["artifact_id"] = _artifact_id("demo", ArtifactKind.SANDBOX_HANDOFF, 1, artifact["content_hash"])
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "sandbox handoff"):
                project_from_dict(payload)

    def test_revoking_output_approval_invalidates_handoff(self):
        project = self.approved_output_project()
        output = project.current(ArtifactKind.COMPILER_OUTPUT)
        project = add_sandbox_handoff(project, self.handoff())
        handoff = project.current(ArtifactKind.SANDBOX_HANDOFF)
        changed = decide(project, output.ref, ApprovalDecision.CHANGES_REQUESTED, "ben", "revise output")
        self.assertIsNone(changed.current(ArtifactKind.SANDBOX_HANDOFF))
        self.assertEqual(ArtifactState.INVALIDATED, changed.artifact(handoff.artifact_id).state)

    def test_protocol_is_inert_and_result_is_bound_to_exact_handoff(self):
        project = add_sandbox_handoff(self.approved_output_project(), self.handoff())
        request = sandbox_request_to_dict(self.handoff())
        self.assertEqual("sandbox-test-request", request["kind"])
        self.assertFalse(request["handoff"]["executed"])
        result = SandboxTestResult(
            sandbox_request_hash(self.handoff()), "isolated-adapter:v1",
            (
                TestCaseResult("TEST-1", "passed", 12, "ok\n", "", ("REQ-1",)),
                TestCaseResult("TEST-2", "skipped", 0, "", "", ("REQ-1",), "optional backend"),
            ),
        )
        project = add_test_result(project, result)
        artifact = project.current(ArtifactKind.TEST_RESULT)
        handoff = project.current(ArtifactKind.SANDBOX_HANDOFF)
        self.assertEqual((handoff.ref,), artifact.upstream)
        self.assertIn('"passed":1', artifact.content)
        self.assertIn('"skipped":1', artifact.content)
        self.assertEqual(project, project_from_dict(project_to_dict(project)))

    def test_result_rejects_missing_stale_or_mismatched_handoff(self):
        result = SandboxTestResult("sha256:" + "b" * 64, "adapter", (TestCaseResult("T", "passed", 1),))
        with self.assertRaisesRegex(ValueError, "current sandbox handoff"):
            add_test_result(self.approved_output_project(), result)
        project = add_sandbox_handoff(self.approved_output_project(), self.handoff())
        with self.assertRaisesRegex(ValueError, "exact sandbox request"):
            add_test_result(project, result)
        handoff = project.current(ArtifactKind.SANDBOX_HANDOFF)
        with self.assertRaisesRegex(ValueError, "add_test_result"):
            add_artifact(project, ArtifactKind.TEST_RESULT, "{}", (handoff.ref,))

    def test_result_rejects_malformed_and_forged_state(self):
        import json
        from specatom_hs.projects import _artifact_id, content_sha256
        project = add_sandbox_handoff(self.approved_output_project(), self.handoff())
        valid = SandboxTestResult(
            sandbox_request_hash(self.handoff()), "adapter", (TestCaseResult("T", "failed", 2, stderr="boom", assertion="x == y"),),
        )
        for invalid in (
            SandboxTestResult(valid.request_hash, "adapter", (TestCaseResult("T", "unknown", 1),)),
            SandboxTestResult(valid.request_hash, "adapter", (TestCaseResult("T", "passed", 1), TestCaseResult("T", "failed", 2))),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                add_test_result(project, invalid)
        project = add_test_result(project, valid)
        for mutation in ("summary", "unknown", "request_hash"):
            payload = project_to_dict(project)
            artifact = next(item for item in payload["artifacts"] if item["kind"] == "test-result")
            body = json.loads(artifact["content"])
            if mutation == "summary":
                body["summary"]["passed"] = 99
            elif mutation == "unknown":
                body["host_pid"] = 1
            else:
                body["request_hash"] = "sha256:" + "c" * 64
            artifact["content"] = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            artifact["content_hash"] = content_sha256(artifact["content"])
            artifact["artifact_id"] = _artifact_id("demo", ArtifactKind.TEST_RESULT, 1, artifact["content_hash"])
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "test result"):
                project_from_dict(payload)

    def test_replacing_handoff_invalidates_prior_test_result(self):
        project = add_sandbox_handoff(self.approved_output_project(), self.handoff())
        result = SandboxTestResult(sandbox_request_hash(self.handoff()), "adapter", (TestCaseResult("T", "passed", 1),))
        project = add_test_result(project, result)
        old = project.current(ArtifactKind.TEST_RESULT)
        replacement = SandboxHandoff(self.handoff().image_digest, ("python", "-m", "pytest", "-v"), self.handoff().files, self.handoff().limits)
        project = add_sandbox_handoff(project, replacement)
        self.assertIsNone(project.current(ArtifactKind.TEST_RESULT))
        self.assertEqual(ArtifactState.INVALIDATED, project.artifact(old.artifact_id).state)

    def test_compile_admission_rejects_deferred_and_stale_review(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        tests = project.current(ArtifactKind.TEST_SPEC)
        project = decide(project, elaborated.ref, ApprovalDecision.APPROVED, "ben")
        project = decide(project, tests.ref, ApprovalDecision.APPROVED, "ben")
        document = LogicalIRDocument(
            "Demo", (TypeDeclaration("type.Value", "Value", ("REQ-1",)),), (),
            (RequirementObligation("REQ-1", (), ("REQ-1",)),), (), (),
        )
        project = add_logical_ir_document(project, document)
        logical = project.current(ArtifactKind.LOGICAL_IR)
        review = project.current(ArtifactKind.LOGICAL_REVIEW)
        project = decide(project, logical.ref, ApprovalDecision.APPROVED, "ben")
        import json
        from specatom_hs.logical_ir import logical_review_from_dict
        finding = logical_review_from_dict(json.loads(review.content)).findings[0]
        project = decide_logical_finding(project, finding.finding_id, FindingDisposition.DEFERRED, "ben", "later")
        with self.assertRaisesRegex(ValueError, "unresolved critical"):
            admit_compilation(project)
        with self.assertRaisesRegex(ValueError, "exact current"):
            decide_logical_finding(
                Project(project.project_id, project.name, tuple(a for a in project.artifacts if a.kind is not ArtifactKind.LOGICAL_REVIEW), project.approvals, project.annotations),
                "missing", FindingDisposition.WAIVED, "ben", "reason",
            )

    def test_deserialization_rejects_dropped_or_rewritten_logical_finding(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        tests = project.current(ArtifactKind.TEST_SPEC)
        project = decide(project, elaborated.ref, ApprovalDecision.APPROVED, "ben")
        project = decide(project, tests.ref, ApprovalDecision.APPROVED, "ben")
        document = LogicalIRDocument(
            "Demo", (TypeDeclaration("type.Value", "Value", ("REQ-1",)),), (),
            (RequirementObligation("REQ-1", (), ("REQ-1",)),), (), (),
        )
        import json
        from specatom_hs.projects import _artifact_id, content_sha256
        for mutation in ("drop", "rewrite"):
            payload = project_to_dict(add_logical_ir_document(project, document))
            review = next(item for item in payload["artifacts"] if item["kind"] == "logical-review")
            body = json.loads(review["content"])
            if mutation == "drop":
                body["findings"] = []
                body["blocks_compilation"] = False
            else:
                body["findings"][0]["message"] = "forged finding"
            review["content"] = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            review["content_hash"] = content_sha256(review["content"])
            review["artifact_id"] = _artifact_id("demo", ArtifactKind.LOGICAL_REVIEW, 1, review["content_hash"])
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "does not match logical IR"):
                project_from_dict(payload)

    def test_revoking_input_approval_invalidates_logical_ir(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        tests = project.current(ArtifactKind.TEST_SPEC)
        project = decide(project, elaborated.ref, ApprovalDecision.APPROVED, "ben")
        project = decide(project, tests.ref, ApprovalDecision.APPROVED, "ben")
        project = add_logical_ir(project, "logical")
        logical = project.current(ArtifactKind.LOGICAL_IR)
        changed = decide(project, elaborated.ref, ApprovalDecision.CHANGES_REQUESTED, "ben", "revise")
        self.assertIsNone(changed.current(ArtifactKind.LOGICAL_IR))
        self.assertEqual(ArtifactState.INVALIDATED, changed.artifact(logical.artifact_id).state)

    def test_deserialization_rejects_logical_ir_without_approvals(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        tests = project.current(ArtifactKind.TEST_SPEC)
        project = decide(project, elaborated.ref, ApprovalDecision.APPROVED, "ben")
        project = decide(project, tests.ref, ApprovalDecision.APPROVED, "ben")
        payload = project_to_dict(add_logical_ir(project, "logical"))
        payload["approvals"] = []
        with self.assertRaisesRegex(ValueError, "lacks exact input approvals"):
            project_from_dict(payload)

    def test_deserialization_rejects_mutated_content(self):
        payload = project_to_dict(create_project("demo", "Demo", "source"))
        payload["artifacts"][0]["content"] = "tampered"
        with self.assertRaisesRegex(ValueError, "invalid content hash"):
            project_from_dict(payload)

    def test_deserialization_rejects_unknown_enums_and_missing_fields(self):
        payload = project_to_dict(create_project("demo", "Demo", "source"))
        payload["artifacts"][0]["state"] = "maybe"
        with self.assertRaisesRegex(ValueError, "malformed project state"):
            project_from_dict(payload)
        missing = project_to_dict(create_project("demo", "Demo", "source"))
        del missing["artifacts"][0]["content_hash"]
        with self.assertRaisesRegex(ValueError, "malformed project state"):
            project_from_dict(missing)

    def test_deserialization_rejects_forged_approval_binding(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        payload = project_to_dict(decide(project, elaborated.ref, ApprovalDecision.APPROVED, "ben"))
        payload["approvals"][0]["artifact"]["content_hash"] = "sha256:forged"
        with self.assertRaisesRegex(ValueError, "approval hash mismatch"):
            project_from_dict(payload)

    def test_deserialization_rejects_forged_or_malformed_annotation(self):
        project = self.populated()
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = annotate(project, elaborated.ref, "ben", "review", "item:PRED-1")
        forged = project_to_dict(project)
        forged["annotations"][0]["artifact"]["content_hash"] = "sha256:forged"
        with self.assertRaisesRegex(ValueError, "annotation hash mismatch"):
            project_from_dict(forged)
        malformed = project_to_dict(project)
        malformed["annotations"][0]["comment"] = " "
        with self.assertRaisesRegex(ValueError, "comment is blank"):
            project_from_dict(malformed)


if __name__ == "__main__":
    unittest.main()

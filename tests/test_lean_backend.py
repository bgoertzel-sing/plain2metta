import copy
import os
import tempfile
import unittest
from pathlib import Path

from specatom_hs.lean_backend import *

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/"lean/Plain2MeTTaSemanticKernel"
TOOLS=Path("/home/openclaw/research-agent/projects/specatom-hs/experiments/20260817T040300Z-plain2metta-stage0-tlc-lean/artifacts/tools/lean-4.33.0-linux/bin")
LEAN=str(TOOLS/"lean"); LAKE=str(TOOLS/"lake")

class LeanBackendTests(unittest.TestCase):
    def approved_project(self):
        from tests.test_validation_plan import ValidationPlanTests
        from specatom_hs.projects import ApprovalDecision, ArtifactKind
        from specatom_hs.validation_plan import PlanReview, ValidationPlanCoordinator, submit_plan_review
        fixture=ValidationPlanTests(); fixture.setUp()
        project=ValidationPlanCoordinator(fixture.adapter()).synthesize(fixture.project)
        plan=project.current(ArtifactKind.VALIDATION_PLAN)
        return submit_plan_review(project, PlanReview(plan.ref, ApprovalDecision.APPROVED, "reviewer", "approve exact Lean kernel", "2026-08-17T09:27:00Z"))

    def test_manifest_is_strict_reviewable_and_has_no_extra_trust(self):
        value=package_manifest(PACKAGE)
        self.assertEqual([],value["axioms"]); self.assertEqual([],value["unsafe_declarations"])
        self.assertIn("pure_nonnegative_identity",value["source_map"])
        self.assertIn("counter_step_preserves_invariant",value["source_map"])

    def test_pinned_kernel_builds_and_is_deterministically_attributed(self):
        if not Path(LAKE).exists(): self.skipTest("pinned Lean unavailable")
        project=self.approved_project(); request=lower_lean_request(project,PACKAGE)
        result=run_lean_request(request,PACKAGE,LEAN,LAKE)
        self.assertTrue(result["kernel_checked"]); self.assertEqual(0,result["exit_status"])
        self.assertEqual(request["manifest"],result["manifest"])

    def test_false_theorem_is_rejected_by_kernel(self):
        if not Path(LEAN).exists(): self.skipTest("pinned Lean unavailable")
        false=Path(tempfile.mkdtemp())/"False.lean"
        false.write_text("example : (1 : Nat) = 2 := by decide\n",encoding="utf-8")
        completed=__import__("subprocess").run((LEAN,str(false)),capture_output=True,text=True)
        self.assertNotEqual(0,completed.returncode)

    def test_forbidden_trust_and_path_confusion_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            import shutil; shutil.copytree(PACKAGE,Path(directory)/"pkg",dirs_exist_ok=True)
            basic=Path(directory)/"pkg/Plain2MeTTaSemanticKernel/Basic.lean"
            basic.write_text(basic.read_text()+"\naxiom bad : False\n")
            with self.assertRaisesRegex(ValueError,"forbidden"): package_manifest(Path(directory)/"pkg")
        with self.assertRaises(ValueError): package_manifest(PACKAGE/"../escape")

    def test_malformed_hash_mismatch_and_failed_kernel_do_not_admit(self):
        from specatom_hs.projects import ArtifactKind
        project=self.approved_project(); request=lower_lean_request(project,PACKAGE)
        valid=run_lean_request(request,PACKAGE,LEAN,LAKE)
        variants=[]
        bad=copy.deepcopy(valid); bad["schema"]="unknown/v9"; variants.append(bad)
        bad=copy.deepcopy(valid); bad["request_hash"]="sha256:"+"0"*64; variants.append(bad)
        bad=copy.deepcopy(valid); bad["exit_status"]=1; bad["kernel_checked"]=False; variants.append(bad)
        for bad in variants:
            with self.assertRaises(ValueError): LeanCoordinator(lambda _,bad=bad:bad,PACKAGE).run(project)
            self.assertIsNone(project.current(ArtifactKind.RUNTIME_EVIDENCE))

    def test_exact_ancestry_admits_and_source_change_invalidates(self):
        from specatom_hs.projects import ArtifactKind, replace_source
        project=self.approved_project()
        result=LeanCoordinator(lambda request:run_lean_request(request,PACKAGE,LEAN,LAKE),PACKAGE).run(project)
        self.assertIsNotNone(result.current(ArtifactKind.RUNTIME_EVIDENCE))
        self.assertIsNone(replace_source(result,"[id:R-1] Changed source byte\n").current(ArtifactKind.RUNTIME_EVIDENCE))

if __name__ == "__main__": unittest.main()

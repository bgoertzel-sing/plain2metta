import copy
import os
import unittest

from specatom_hs.tlc_backend import (
    JAVA_SHA256, PROFILE, SCHEMA, TLC_ENGINE_VERSION, TLC_JAR_SHA256, TLC_VERSION, render_tlc_bundle,
    request_hash, run_tlc_request,
)

ROOT = "/home/openclaw/research-agent/projects/specatom-hs/experiments/20260817T040300Z-plain2metta-stage0-tlc-lean/artifacts/tools"
JAVA = ROOT + "/jdk-21.0.12+8-jre/bin/java"
JAR = ROOT + "/tla2tools.jar"


def request(models):
    return {"schema":SCHEMA, "tlc_version":TLC_VERSION, "tlc_engine_version":TLC_ENGINE_VERSION,
        "tlc_jar_hash":TLC_JAR_SHA256, "java_hash":JAVA_SHA256, "profile":PROFILE,
        "plan":{"artifact_id":"plan-1","content_hash":"sha256:"+"1"*64}, "review":{"artifact_id":"review-1","content_hash":"sha256:"+"2"*64},
        "ancestry":[{"artifact_id":"source-1","content_hash":"sha256:"+"3"*64},{"artifact_id":"contract-1","content_hash":"sha256:"+"4"*64},{"artifact_id":"plan-1","content_hash":"sha256:"+"1"*64},{"artifact_id":"review-1","content_hash":"sha256:"+"2"*64}], "models":models}


def model(model_id, protocol, mutant="none"):
    return {"model_id":model_id, "source_clause_refs":["R-1"], "protocol":protocol, "scope":{"max_steps":12,"actors":2}, "mutant":mutant}


class TLCBackendTests(unittest.TestCase):
    def test_canonical_bundles_are_deterministic_and_typed(self):
        value=request([model("auth","authentication-ordering"),model("idem","idempotency-recovery")])
        self.assertEqual(render_tlc_bundle(value),render_tlc_bundle(value))
        self.assertIn("AuthenticationOrdered",render_tlc_bundle(value)[0]["module"])
        self.assertIn("AtMostOneDebit",render_tlc_bundle(value)[1]["module"])
        self.assertEqual(request_hash(value),request_hash(copy.deepcopy(value)))

    def test_exact_admission_stability_is_a_closed_finite_model(self):
        bundle = render_tlc_bundle(request([model("admission", "exact-admission-stability")]))[0]
        self.assertIn("AdmissionStable == admitted", bundle["module"])
        self.assertEqual(["admitted"], bundle["source_map"]["variables"])

    def test_correct_models_pass_and_mutants_have_source_linked_traces(self):
        if not os.path.exists(JAVA): self.skipTest("pinned Stage-0 TLC unavailable")
        good=run_tlc_request(request([model("auth","authentication-ordering"),model("idem","idempotency-recovery")]),JAVA,JAR)
        self.assertTrue(all(item["invariant_satisfied"] for item in good["results"]),good)
        mutants=run_tlc_request(request([model("order-mutant","authentication-ordering","ordering"),model("debit-mutant","idempotency-recovery","duplicate-debit"),model("recovery-mutant","idempotency-recovery","recovery")]),JAVA,JAR)
        self.assertTrue(all(not item["invariant_satisfied"] and item["counterexample_trace"] for item in mutants["results"]),mutants)
        self.assertTrue(all(item["source_clause_refs"]==["R-1"] for item in mutants["results"]))

    def test_unknown_version_unsupported_prose_path_confusion_and_bad_scope_fail(self):
        good=request([model("auth","authentication-ordering")])
        variants=[]
        item=copy.deepcopy(good); item["schema"]="unknown/v9"; variants.append(item)
        item=copy.deepcopy(good); item["models"][0]["protocol"]="free prose"; variants.append(item)
        item=copy.deepcopy(good); item["models"][0]["model_id"]="../escape"; variants.append(item)
        item=copy.deepcopy(good); item["models"][0]["scope"]["actors"]=999; variants.append(item)
        for value in variants:
            with self.assertRaises(ValueError): render_tlc_bundle(value)

    def test_tlc_hash_mismatch_fails_before_execution(self):
        if not os.path.exists(JAVA): self.skipTest("pinned Stage-0 TLC unavailable")
        with self.assertRaisesRegex(ValueError,"hash mismatch"):
            run_tlc_request(request([model("auth","authentication-ordering")]),JAVA,__file__)


if __name__ == "__main__": unittest.main()

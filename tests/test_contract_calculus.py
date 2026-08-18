import copy
import unittest

from specatom_hs.contract_calculus import (
    CALCULUS, EvaluationContext, Event, check_contract, interpret_contract,
    project_contract_to_metta, type_check,
)
from specatom_hs.projects import ArtifactRef
from specatom_hs.semantic_artifacts import build_semantic_artifact


SOURCE = ArtifactRef("reviewed-source", "sha256:" + "1" * 64)
PROVENANCE = {"producer":"stage2-fixture","version":"1","operation":"contract-author","timestamp":"2026-08-17T07:51:00Z","input_hashes":[SOURCE.content_hash]}


def lit(typ, value): return {"op":"literal","type":typ,"value":value}
def var(name): return {"op":"var","name":name}


def contract(name, inputs, output, *, pre=(), post=(), inv=(), temporal=(), effects=("pure",), assumptions=(), holes=()):
    payload = {
        "contract_id":f"contract:{name}", "source_clause_refs":[f"clause:{name}"], "name":name,
        "inputs":[{"name":n,"type":t} for n,t in inputs], "output":output,
        "preconditions":list(pre), "postconditions":list(post), "invariants":list(inv),
        "effects":list(effects), "temporal_constraints":list(temporal),
        "nondeterminism":{"policy":"deterministic","ownership_locus":"reference-interpreter"},
        "environment_assumptions":[{"ref":a} for a in assumptions], "unresolved_holes":list(holes),
    }
    return build_semantic_artifact("SemanticContract", SOURCE, [], PROVENANCE, payload)


class ContractCalculusTests(unittest.TestCase):
    def test_pure_bounded_quantifier_is_deterministic_and_projected_with_types(self):
        predicate = {"op":"for-all","var":"x","var_type":"Int","domain":var("values"),"predicate":{"op":"ge","left":var("x"),"right":lit("Int",0)}}
        doc = contract("pure", [("values",{"List":"Int"})], "Bool", post=(predicate,))
        context = EvaluationContext({"values":[0,1,2],"result":True}, {})
        first = interpret_contract(doc, context)
        self.assertEqual(first, interpret_contract(doc, context))
        self.assertTrue(first["satisfied"])
        projection = project_contract_to_metta(doc)
        self.assertIn(CALCULUS, projection)
        self.assertIn('(List Int)', projection)
        self.assertIn('(for-all ("x" Int)', projection)

        decimal_predicate = {"op":"for-all","var":"x","var_type":"Decimal","domain":var("values"),"predicate":{"op":"ge","left":var("x"),"right":lit("Decimal","0.0")}}
        decimal_doc = contract("pure-decimal", [("values",{"List":"Decimal"})], "Bool", post=(decimal_predicate,))
        self.assertTrue(interpret_contract(decimal_doc, EvaluationContext({"values":["0.0","1.5"],"result":True}, {}))["satisfied"])

    def test_stateful_trace_contract(self):
        trace = ({"op":"exactly-once","event":"debited"}, {"op":"eq","left":{"op":"state","key":"balance","type":"Int"},"right":lit("Int",90)})
        doc = contract("stateful", [], "Unit", inv=trace, effects=("state-read","trace-read"))
        ctx = EvaluationContext({"result":None},{"balance":90},(Event("debited","2026-08-17T00:00:01Z",{}),))
        self.assertTrue(interpret_contract(doc,ctx)["satisfied"])

    def test_temporal_before_uses_explicit_utc_time(self):
        doc = contract("temporal", [], "Unit", temporal=({"op":"before","first":"authenticated","second":"served"},), effects=("trace-read","time-read"))
        ctx = EvaluationContext({"result":None},{},(Event("authenticated","2026-08-17T00:00:00Z",{}),Event("served","2026-08-17T00:00:01Z",{})))
        self.assertTrue(interpret_contract(doc,ctx)["satisfied"])
        reverse = EvaluationContext(ctx.variables,{},(Event("served","2026-08-17T00:00:00Z",{}),Event("authenticated","2026-08-17T00:00:01Z",{})))
        self.assertFalse(interpret_contract(doc,reverse)["satisfied"])

    def test_approximate_decimal_contract(self):
        approx = {"op":"approximately","expected":lit("Decimal","1.00"),"observed":var("result"),"tolerance":lit("Decimal","0.05")}
        doc = contract("approx", [], "Decimal", post=(approx,))
        self.assertTrue(interpret_contract(doc,EvaluationContext({"result":"1.04"},{}))["satisfied"])
        self.assertFalse(interpret_contract(doc,EvaluationContext({"result":"1.06"},{}))["satisfied"])

    def test_assumptions_are_exact_approved_references(self):
        predicate = {"op":"assumption","ref":"policy:retention-v1"}
        doc = contract("assumed", [], "Bool", pre=(predicate,), assumptions=("policy:retention-v1",))
        with self.assertRaisesRegex(ValueError,"assumption"):
            interpret_contract(doc,EvaluationContext({"result":True},{},assumptions=frozenset()))
        self.assertTrue(interpret_contract(doc,EvaluationContext({"result":True},{},assumptions=frozenset({"policy:retention-v1"})))["satisfied"])

    def test_unresolved_contract_is_typed_but_never_executed_or_projected(self):
        hole = {"hole_id":"hole:policy","type":"Bool","reason":"authorization policy is undefined"}
        doc = contract("unresolved", [], "Bool", holes=(hole,))
        self.assertEqual(check_contract(doc).unresolved_holes[0]["type"],"Bool")
        with self.assertRaisesRegex(ValueError,"unresolved"):
            interpret_contract(doc,EvaluationContext({"result":True},{}))
        with self.assertRaisesRegex(ValueError,"unresolved"):
            project_contract_to_metta(doc)

    def test_free_prose_unsupported_and_type_confusion_fail_closed(self):
        bad_terms = ["result must be safe", {"op":"call-shell","command":"true"}, {"op":"eq","left":lit("Int",1),"right":lit("Text","1")}]
        for term in bad_terms:
            doc = contract("bad", [], "Bool", post=(term,))
            with self.assertRaises(ValueError): check_contract(doc)

    def test_malformed_effect_owner_time_and_quantifier_bounds_fail_closed(self):
        doc = contract("bad-effect", [], "Bool", effects=("network",))
        with self.assertRaisesRegex(ValueError,"effects"): check_contract(doc)
        doc = contract("bounded", [("values",{"List":"Int"})], "Bool", post=({"op":"for-all","var":"x","var_type":"Int","domain":var("values"),"predicate":{"op":"eq","left":var("x"),"right":var("x")}},))
        with self.assertRaisesRegex(ValueError,"exceeds"):
            interpret_contract(doc,EvaluationContext({"values":list(range(1025)),"result":True},{}))
        malformed = copy.deepcopy(doc); malformed["payload"]["nondeterminism"]["ownership_locus"]="free-prose"; malformed["artifact_id"]="forged"
        with self.assertRaises(ValueError): check_contract(malformed)

    def test_projection_refuses_hole_term_even_without_hole_manifest(self):
        term = {"op":"hole","hole_id":"hole:x","type":"Bool","reason":"meaning absent"}
        doc = contract("hidden-hole", [], "Bool", post=(term,))
        with self.assertRaisesRegex(ValueError,"hole"):
            project_contract_to_metta(doc)


if __name__ == "__main__": unittest.main()

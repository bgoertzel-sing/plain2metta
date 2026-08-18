import copy
import json
import unittest

from specatom_hs.phase3_review import Phase3Decision, Phase3ReviewLog
from specatom_hs.projects import (
    ApprovalDecision, ArtifactKind, add_artifact, add_semantic_artifact,
    create_project, project_from_dict, project_to_dict, replace_source,
    submit_phase3_review,
)
from specatom_hs.semantic_artifacts import (
    build_semantic_artifact, canonical_semantic_artifact,
    semantic_artifact_from_dict,
)


class SemanticArtifactTests(unittest.TestCase):
    def setUp(self):
        project = create_project("semantic", "Semantic", "[id:R-1] Return the greeting.\n")
        source = project.current(ArtifactKind.ORIGINAL_SPEC)
        project = add_artifact(project, ArtifactKind.ELABORATED_SPEC, "[id:R-1] Return the greeting.\n", (source.ref,))
        elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
        project = add_artifact(project, ArtifactKind.TEST_SPEC, "[covers:R-1] Expect greeting.\n", (elaborated.ref,))
        tests = project.current(ArtifactKind.TEST_SPEC)
        project = submit_phase3_review(project, Phase3ReviewLog(
            elaborated.ref, tests.ref,
            (Phase3Decision(elaborated.ref, ApprovalDecision.APPROVED, "reviewer", "2026-08-17T00:00:00Z"),
             Phase3Decision(tests.ref, ApprovalDecision.APPROVED, "reviewer", "2026-08-17T00:00:01Z")),
        ))
        self.project = project
        self.source = project.current(ArtifactKind.REVIEWED_ELABORATED_SPEC)
        self.provenance = {
            "producer": "stage1-test", "version": "1.0", "operation": "contract-author",
            "timestamp": "2026-08-17T00:00:02Z", "input_hashes": [self.source.content_hash],
        }

    def contract_payload(self):
        return {
            "contract_id": "contract:R-1", "source_clause_refs": ["R-1"], "name": "Greeting",
            "inputs": [], "output": {"type": "Text"}, "preconditions": [],
            "postconditions": [{"op": "eq", "left": "result", "right": "hello"}],
            "invariants": [], "effects": [], "temporal_constraints": [],
            "nondeterminism": "deterministic", "environment_assumptions": [], "unresolved_holes": [],
        }

    def contract(self):
        return build_semantic_artifact("SemanticContract", self.source.ref, [], self.provenance, self.contract_payload())

    def test_contract_round_trip_and_project_storage(self):
        document = self.contract()
        self.assertEqual(document, semantic_artifact_from_dict(json.loads(canonical_semantic_artifact(document))))
        project = add_semantic_artifact(self.project, document)
        self.assertEqual(document, json.loads(project.current(ArtifactKind.SEMANTIC_CONTRACT).content))
        self.assertEqual(project, project_from_dict(project_to_dict(project)))

    def test_all_stage1_types_have_strict_versioned_schemas(self):
        project = add_semantic_artifact(self.project, self.contract())
        contract = project.current(ArtifactKind.SEMANTIC_CONTRACT)
        cases = {
            "ValidationObligation": {"obligation_id":"obligation:R-1","contract_ref":{"artifact_id":contract.artifact_id,"content_hash":contract.content_hash},"source_clause_refs":["R-1"],"claim":{"op":"eq"},"required_grade":"G3","admissible_methods":["example"],"domain":{"kind":"finite"},"assumptions":[],"severity":"major","unresolved":False},
            "ValidationPlan": {"plan_id":"plan:R-1","reviewed_contract_refs":[{"artifact_id":contract.artifact_id,"content_hash":contract.content_hash}],"author_provenance":{"role":"validation-author","request_hash":"sha256:"+"2"*64,"backend":"fixture","model":"fixture","interaction_id":"fixture-1"},"examples":[],"generators":[],"properties":[],"metamorphic_relations":[],"state_models":[],"differential_oracles":[],"formal_tasks":[],"coverage_claims":[]},
            "InputGenerator": {"generator_id":"generator:R-1","domain":{"kind":"finite"},"budget":10,"distribution":"enumerated","shrinker":"none","seed":1},
            "ValidationOracle": {"oracle_id":"oracle:R-1","method":"example","obligation_refs":[],"semantics":{"op":"eq"},"ownership_locus":"reference-interpreter","bounds":{"cases":1},"expected_observations":["hello"]},
            "RuntimeEvidence": {"evidence_id":"evidence:R-1","runtime":"python","runtime_hash":"sha256:"+"1"*64,"resource_bounds":{"seconds":1},"case_id":"case-1","seed":None,"observations":["hello"],"exit_status":0,"artifact_hashes":[contract.content_hash],"started_at":"2026-08-17T00:00:00Z","finished_at":"2026-08-17T00:00:01Z"},
            "Counterexample": {"counterexample_id":"counterexample:R-1","obligation_ref":{"artifact_id":contract.artifact_id,"content_hash":contract.content_hash},"evidence_ref":{"artifact_id":contract.artifact_id,"content_hash":contract.content_hash},"case":{"input":"x"},"observations":["wrong"],"shrinking":{"steps":0},"replay":"run case-1"},
            "ValidationVerdict": {"verdict_id":"verdict:R-1","obligation_ref":{"artifact_id":contract.artifact_id,"content_hash":contract.content_hash},"implementation_ref":{"artifact_id":contract.artifact_id,"content_hash":contract.content_hash},"validation_plan_ref":{"artifact_id":contract.artifact_id,"content_hash":contract.content_hash},"runtime_evidence_refs":[{"artifact_id":contract.artifact_id,"content_hash":contract.content_hash}],"grade_achieved":"G3","status":"unknown","counterexample_refs":[],"residual_risk":"fixture references are illustrative","assumptions_used":[]},
        }
        for artifact_type, payload in cases.items():
            provenance = dict(self.provenance, input_hashes=[self.source.content_hash, contract.content_hash])
            document = build_semantic_artifact(artifact_type, self.source.ref, [contract.ref], provenance, payload)
            self.assertEqual(document, semantic_artifact_from_dict(document))

    def test_unknown_version_partial_extra_duplicate_and_path_confusion_fail_closed(self):
        base = self.contract()
        mutations = []
        item = copy.deepcopy(base); item["schema"] = "plain2metta-semantic-artifact/v2"; mutations.append(item)
        item = copy.deepcopy(base); del item["payload"]["output"]; mutations.append(item)
        item = copy.deepcopy(base); item["payload"]["extra"] = True; mutations.append(item)
        item = copy.deepcopy(base); item["upstream_refs"].append(item["upstream_refs"][0]); mutations.append(item)
        item = copy.deepcopy(base); item["reviewed_source_ref"]["artifact_id"] = "../source"; mutations.append(item)
        for item in mutations:
            with self.assertRaises(ValueError):
                semantic_artifact_from_dict(item)

    def test_forged_id_hash_and_stale_ancestry_fail_closed(self):
        forged = self.contract(); forged["payload"]["name"] = "forged"
        with self.assertRaisesRegex(ValueError, "artifact_id"):
            add_semantic_artifact(self.project, forged)
        mismatch = self.contract(); mismatch["reviewed_source_ref"]["content_hash"] = "sha256:" + "0" * 64
        with self.assertRaises(ValueError):
            add_semantic_artifact(self.project, mismatch)
        project = replace_source(self.project, "[id:R-1] Changed one byte!\n")
        with self.assertRaisesRegex(ValueError, "current reviewed source"):
            add_semantic_artifact(project, self.contract())

    def test_upstream_byte_change_transitively_invalidates_semantic_chain(self):
        project = add_semantic_artifact(self.project, self.contract())
        contract = project.current(ArtifactKind.SEMANTIC_CONTRACT)
        obligation = build_semantic_artifact(
            "ValidationObligation", self.source.ref, [contract.ref],
            dict(self.provenance, operation="obligation-author", input_hashes=[self.source.content_hash, contract.content_hash]),
            {"obligation_id":"obligation:R-1","contract_ref":{"artifact_id":contract.artifact_id,"content_hash":contract.content_hash},"source_clause_refs":["R-1"],"claim":{"op":"eq"},"required_grade":"G3","admissible_methods":["example"],"domain":{"kind":"finite"},"assumptions":[],"severity":"major","unresolved":False},
        )
        project = add_semantic_artifact(project, obligation)
        obligation_artifact = project.current(ArtifactKind.VALIDATION_OBLIGATION)
        plan = build_semantic_artifact(
            "ValidationPlan", self.source.ref, [contract.ref, obligation_artifact.ref],
            dict(self.provenance, operation="plan-author", input_hashes=[self.source.content_hash, contract.content_hash, obligation_artifact.content_hash]),
            {"plan_id":"plan:R-1","reviewed_contract_refs":[{"artifact_id":contract.artifact_id,"content_hash":contract.content_hash}],"author_provenance":{"role":"validation-author","request_hash":"sha256:"+"2"*64,"backend":"fixture","model":"fixture","interaction_id":"fixture-1"},"examples":[],"generators":[],"properties":[],"metamorphic_relations":[],"state_models":[],"differential_oracles":[],"formal_tasks":[],"coverage_claims":[]},
        )
        project = add_semantic_artifact(project, plan)
        plan_artifact = project.current(ArtifactKind.VALIDATION_PLAN)
        evidence = build_semantic_artifact(
            "RuntimeEvidence", self.source.ref, [contract.ref, obligation_artifact.ref, plan_artifact.ref],
            dict(self.provenance, operation="runtime", input_hashes=[self.source.content_hash, contract.content_hash, obligation_artifact.content_hash, plan_artifact.content_hash]),
            {"evidence_id":"evidence:R-1","runtime":"python","runtime_hash":"sha256:"+"1"*64,"resource_bounds":{"seconds":1},"case_id":"case-1","seed":None,"observations":["hello"],"exit_status":0,"artifact_hashes":[contract.content_hash],"started_at":"2026-08-17T00:00:00Z","finished_at":"2026-08-17T00:00:01Z"},
        )
        project = add_semantic_artifact(project, evidence)
        evidence_artifact = project.current(ArtifactKind.RUNTIME_EVIDENCE)
        verdict = build_semantic_artifact(
            "ValidationVerdict", self.source.ref,
            [contract.ref, obligation_artifact.ref, plan_artifact.ref, evidence_artifact.ref],
            dict(self.provenance, operation="verdict", input_hashes=[self.source.content_hash, contract.content_hash, obligation_artifact.content_hash, plan_artifact.content_hash, evidence_artifact.content_hash]),
            {"verdict_id":"verdict:R-1","obligation_ref":{"artifact_id":obligation_artifact.artifact_id,"content_hash":obligation_artifact.content_hash},"implementation_ref":{"artifact_id":contract.artifact_id,"content_hash":contract.content_hash},"validation_plan_ref":{"artifact_id":plan_artifact.artifact_id,"content_hash":plan_artifact.content_hash},"runtime_evidence_refs":[{"artifact_id":evidence_artifact.artifact_id,"content_hash":evidence_artifact.content_hash}],"grade_achieved":"G3","status":"pass","counterexample_refs":[],"residual_risk":"bounded example only","assumptions_used":[]},
        )
        project = add_semantic_artifact(project, verdict)
        self.assertTrue(all(project.current(kind) is not None for kind in (
            ArtifactKind.SEMANTIC_CONTRACT, ArtifactKind.VALIDATION_OBLIGATION,
            ArtifactKind.VALIDATION_PLAN, ArtifactKind.RUNTIME_EVIDENCE,
            ArtifactKind.VALIDATION_VERDICT,
        )))
        changed = replace_source(project, "[id:R-1] Return a different greeting.\n")
        self.assertTrue(all(changed.current(kind) is None for kind in (
            ArtifactKind.SEMANTIC_CONTRACT, ArtifactKind.VALIDATION_OBLIGATION,
            ArtifactKind.VALIDATION_PLAN, ArtifactKind.RUNTIME_EVIDENCE,
            ArtifactKind.VALIDATION_VERDICT,
        )))

    def test_stored_envelope_ancestry_mismatch_fails_closed(self):
        project = add_semantic_artifact(self.project, self.contract())
        payload = project_to_dict(project)
        item = next(a for a in payload["artifacts"] if a["kind"] == "semantic-contract")
        item["upstream"] = []
        with self.assertRaisesRegex(ValueError, "semantic artifact envelope"):
            project_from_dict(payload)


if __name__ == "__main__":
    unittest.main()

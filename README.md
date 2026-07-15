# specatom-hs

Local-only prototype scaffold for SpecAtom-HS, a source-preserving Plain-like specification IR before any executable code generation.

This repository currently contains two layers:

- `plain_to_metta`: the earlier stdlib MVP compiler used by the project notebook examples.
- `specatom_hs`: the minimal scaffold recommended by the SpecAtom-HS source summary, with small modules for schema, source indexing, pass registry, validation records, and conservative PeTTa backend gates.

## What is intentionally supported

- stable source IDs, SHA-256 file digests, sections, bullet items, and exact byte/line spans, including marker spans on continuation lines;
- source-file/source-span validation obligations for reproducible file digests, indexed-file byte bounds, byte-offset-derived line numbers, section/item links to indexed PlainFiles, and file-consistency between sections/items/spans;
- first-class validation-obligation and check records (`Pass`, `Fail`, `Unknown`);
- scaffold fact-arity, object-subject, and declared-reference validation for supported predicates, with Unknown predicate checks turned into explicit profile questions;
- PeTTa reified-profile semantic-level validation, turning unsupported levels such as `RawTextOnly` into explicit blocking questions before backend export;
- validation-layer self-checks that ensure validation obligations cite known source/target provenance, each check record cites an existing obligation, uses a declared status, preserves non-empty evidence, and matches its declared property/target, and each question object has non-empty review text plus known blocked validation obligations;
- conservative concept markers (`:Concept:`, `[def:Concept]`, `[ref:Concept]`, `[concept:Concept]`, and definition/glossary `Concept:` bullets);
- shallow requirement/test coverage obligations with Pass/Unknown checks, document-scoped explicit `[id:...]`/`[covers:...]` label matching, duplicate-label ambiguity checks, missing-test questions, orphan-test questions, and unresolved/ambiguous coverage-target questions;
- first Phase 2/3 semantic-object slice for explicit `Scope:`/`Context:`, `Epistemic status:`/`Status:`, `Confidence:`, `Evidence:`, `Proof:`, `Rationale:`, `Interpretation:`, `Bridge:`, `Revision:`, `Decision:`, `Outcome:`, `Observation:`, `Counterexample:`, `Example:`, `Citation:`/`Reference:`, `Metric:`, `Validation:`/`Verification:`/`Check:`, `Witness:`/`Backend artifact:`, `Process:`, `Resource:`, `Dependency:`, `Risk:`, `Mitigation:`, `Priority:`, `Deadline:`/`Due:`, `Owner:`/`Assignee:`, `Limitation:`, `NonGoal:`/`Non-goal:`, `Deprecated:`/`Deprecation:`, `Replacement:`, `Acceptance Criterion:`/`Acceptance Criteria:`, `TODO:`/`To-do:`, `Open issue:`/`Issue:`, `Question:`, `Assumption:`, `Invariant:`, `Constraint:`, `Claim:`, `Axiom:`, `Hypothesis:`, `Precondition:`, and `Postcondition:` markers, producing stable source-provenance-backed objects with exact occurrence source spans (including repeated markers and continuation-line markers) plus conservative Pass/Unknown checks/questions for unsupported status labels, out-of-range or non-numeric confidence values, arbitrary unsupported bridge ontology labels, non-conservative bridge relations such as `identical`, source-provenance-preserved observations/outcomes without validation-success inference, source-provenance-preserved counterexamples without automatic claim rejection/proof, proof markers without concrete proof artifacts/procedures, interpretations/assumptions/invariants/constraints/claims/axioms/hypotheses/preconditions/postconditions without explicit same-item evidence or proof, non-concrete TODO/raw-text-only witness placeholders, extensionless build artifacts such as `Dockerfile`/`Makefile`, script/config process artifacts, resource artifact paths, vague process/resource/dependency placeholders, risks without explicit mitigation/control evidence, unsupported/placeholder priority values, vague/placeholder deadlines, owner/assignee placeholders without concrete accountability, limitations without explicit mitigation/workaround/disposition evidence, source-provenance-preserved non-goal exclusions, deprecations without explicit replacement/migration/sunset/removal disposition, placeholder acceptance criteria, reviewable examples versus placeholder example questions, reviewable citation/reference identifiers versus placeholder citation questions, concrete validation metrics versus placeholder metric questions, concrete validation/check procedures versus placeholder validation questions, explicit TODOs, explicit open issues, and explicit unanswered review questions;
- conservative ML/time-series methodology obligations for metric declaration, metric/task appropriateness review, horizon/frequency declaration, reproducibility evidence, train-only preprocessing fit scope, preprocess-then-split leakage review, future/label-as-feature leakage review, prediction-time feature availability review, real-time/current feature freshness review, temporal split-order review, baseline comparison, named baseline comparator review, uncertainty/error-bar reporting, and named uncertainty-method review, with missing evidence surfaced as blocking questions;
- conservative security/privacy obligation scaffolding for secrets handling, secret log-exposure review, credential rotation/expiry/revocation review, PII/privacy handling, data/sensitivity classification, encryption-scope/key-management review, lawful-basis/consent review, retention/deletion review, purpose-limitation review, data-subject rights review, PII access audit/logging review, PII incident-response/breach-notification review, data-residency/cross-border transfer review, third-party/vendor/processor sharing review, access-boundary declarations, privilege-escalation review, authentication/session-management review, authentication/API abuse-protection review, API authorization/scope review, authentication/API transport-protection review, API/webhook input-validation review, webhook/callback request-authenticity review, API/webhook error-disclosure review, and destructive-action safety review, with missing evidence surfaced as blocking questions;
- PeTTa profile refusal records for `RawTextOnly`, unsupported semantic levels, unsupported predicates, malformed fact arity, object-fact subject mismatches, and non-string object references;
- syntax-safe PeTTa scalar serialization that quotes whitespace, delimiters, semicolons, and ASCII control characters so source/fact text cannot be truncated or contain raw control bytes;
- profile-filtered source provenance manifest atoms, object facts, validation obligations, rationales, check records, check-obligation links, and check evidence only when supported by `petta_reified_v0`;
- exact source-span provenance for `DataFlowEdge` and `TemporalOrderEdge` atoms, with `edge-has-item-level-source-provenance` validation checks ensuring each edge object cites an exact or item-contained source span for where the edge was found.
- information-flow validation with component-level data-path edge extraction (`DataFlowEdge` atoms, including `reads from`, `writes to`, `sends to`, `receives ... from`, `consumes ... from`, `pulls ... from`, `ingests ... from`, `produces ... to`, `pushes ... to`, `emits ... to`, `feeds into`, and `depends on` forms), duplicate/parallel edge review, transitive dependency chain detection, graph-based cycle detection, fan-out/fan-in concentration detection, bottleneck node detection (high fan-in AND fan-out), source/sink identification, source and sink reachability analysis, isolated component detection, connected components detection, redundant path detection, temporal ordering impossibility detection, cross-layer data-flow/temporal consistency checks, dependency depth / critical path length detection, and `TemporalOrderEdge` atoms, with missing evidence surfaced as blocking questions;
- document-validation-summary atom in the PeTTa reified export with Pass/Fail/Unknown check counts and QuestionObject count.

## What is intentionally not supported

- full Plain grammar;
- deep English semantics;
- inferred semantic objects without explicit markers;
- executable skeleton generation from raw text;
- remote/published repository workflows.

## Run tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Minimal scaffold API

```python
from specatom_hs.passes import compile_source
from specatom_hs.backends.petta import emit_reified_atoms, refuse_executable_skeleton

doc = compile_source("***definitions***\n- :Task: is work.\n", "minimal.plain")
atoms, refusals = emit_reified_atoms(doc)
skeleton_refusals = refuse_executable_skeleton(doc.objects)
```

## CLI usage

Compile a Plain spec to all scaffold outputs beside the input:

```bash
PYTHONPATH=src python3 -m specatom_hs.cli examples/auth_service.plain
PYTHONPATH=src python3 -m specatom_hs.cli --all examples/auth_service.plain
```

Write one output format to stdout:

```bash
PYTHONPATH=src python3 -m specatom_hs.cli --json examples/task_manager.plain
PYTHONPATH=src python3 -m specatom_hs.cli --metta examples/task_manager.plain
PYTHONPATH=src python3 -m specatom_hs.cli --diagnostics examples/task_manager.plain
```

Run the bundled demo over all examples:

```bash
bash scripts/demo.sh
```

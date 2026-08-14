# Plain2Metta

Plain2Metta is a source-preserving, fail-closed compiler and validation toolkit
for translating Plain-like specifications into reviewable SpecAtom-HS JSON and
PeTTa/MeTTa reified atoms before any executable code generation.

The public repository is named **Plain2Metta**. The internal intermediate
representation and Python package retain the technical name `specatom_hs`.

This repository currently contains two layers:

- `plain_to_metta`: the earlier stdlib MVP compiler used by the project notebook examples.
- `specatom_hs`: the minimal scaffold recommended by the SpecAtom-HS source summary, with small modules for schema, source indexing, pass registry, validation records, and conservative PeTTa backend gates.

The Plain2MeTTa v2 seams are `specatom_hs.projects` and
`specatom_hs.logical_ir`: immutable project and
artifact versions, SHA-256 content provenance, approvals bound to exact
artifact versions, transitive invalidation after an upstream change, and a
strict versioned dictionary representation, plus a non-executable logical-IR
schema and hash-bound machine-readable review findings. It does not yet perform
LLM elaboration, executable compilation, or execution.

## What is intentionally supported

- stable source IDs, SHA-256 file digests, sections, bullet items, and exact byte/line spans, including marker spans on continuation lines;
- source-file/source-span validation obligations for concrete `PlainFile` record types, reproducible file digests, indexed-file byte bounds, byte-offset-derived line numbers, backend-safe Section kinds/ordinals and PlainItem ordinals/nesting depths, section/item links to indexed PlainFiles, and file-consistency between sections/items/spans;
- first-class validation-obligation and check records (`Pass`, `Fail`, `Unknown`), including fail-closed malformed validation-obligation record handling, backend-safe non-blank obligation/check properties and target identities, NFC/NFKC-canonical object-scoped subtargets with refusal of control/format/mark/private-use/unassigned characters, absent-or-safe obligation source-span identities, plus reviewable rationale/evidence checks;
- scaffold fact-arity, object-subject, and declared-reference validation for supported predicates, with Unknown predicate checks turned into explicit profile questions;
- PeTTa reified-profile semantic-level validation, turning unsupported levels such as `RawTextOnly` into explicit blocking questions before backend export;
- validation-layer self-checks that ensure validation obligations cite known source/target provenance, each check record cites an existing obligation, uses a declared status, preserves non-empty evidence, and matches its declared property/target, and each question object has non-empty review text plus known blocked validation obligations;
- conservative concept markers (`:Concept:`, `[def:Concept]`, `[ref:Concept]`, `[concept:Concept]`, and definition/glossary `Concept:` bullets);
- shallow requirement/test coverage obligations with Pass/Unknown checks, document-scoped explicit `[id:...]`/`[covers:...]` label matching, duplicate-label ambiguity checks, missing-test questions, orphan-test questions, and unresolved/ambiguous coverage-target questions;
- first Phase 2/3 semantic-object slice for explicit `Scope:`/`Context:`, `Epistemic status:`/`Status:`, `Confidence:`, `Evidence:`, `Proof:`, `Rationale:`, `Interpretation:`, `Bridge:`, `Revision:`, `Decision:`, `Outcome:`, `Observation:`, `Counterexample:`, `Example:`, `Citation:`/`Reference:`, `Metric:`, `Validation:`/`Verification:`/`Check:`, `Witness:`/`Backend artifact:`, `Process:`, `Resource:`, `Dependency:`, `Risk:`, `Mitigation:`, `Priority:`, `Deadline:`/`Due:`, `Owner:`/`Assignee:`, `Limitation:`, `NonGoal:`/`Non-goal:`, `Deprecated:`/`Deprecation:`, `Replacement:`, `Acceptance Criterion:`/`Acceptance Criteria:`, `TODO:`/`To-do:`, `Open issue:`/`Issue:`, `Question:`, `Assumption:`, `Invariant:`, `Constraint:`, `Claim:`, `Axiom:`, `Hypothesis:`, `Precondition:`, and `Postcondition:` markers, producing stable source-provenance-backed objects with exact occurrence source spans (including repeated markers and continuation-line markers) plus conservative Pass/Unknown checks/questions for unsupported status labels, out-of-range or non-numeric confidence values, arbitrary unsupported bridge ontology labels, non-conservative bridge relations such as `identical`, source-provenance-preserved observations/outcomes without validation-success inference, source-provenance-preserved counterexamples without automatic claim rejection/proof, proof markers without concrete proof artifacts/procedures, interpretations/assumptions/invariants/constraints/claims/axioms/hypotheses/preconditions/postconditions without explicit same-item evidence or proof, non-concrete TODO/raw-text-only witness placeholders, extensionless build artifacts such as `Dockerfile`/`Makefile`, script/config process artifacts, resource artifact paths, vague process/resource/dependency placeholders, risks without explicit mitigation/control evidence, unsupported/placeholder priority values, vague/placeholder deadlines, owner/assignee placeholders without concrete accountability, limitations without explicit mitigation/workaround/disposition evidence, source-provenance-preserved non-goal exclusions, deprecations without explicit replacement/migration/sunset/removal disposition, placeholder acceptance criteria, reviewable examples versus placeholder example questions, reviewable citation/reference identifiers versus placeholder citation questions, concrete validation metrics versus placeholder metric questions, concrete validation/check procedures versus placeholder validation questions, explicit TODOs, explicit open issues, and explicit unanswered review questions;
- conservative ML/time-series methodology obligations for metric declaration, metric/task appropriateness review, horizon/frequency declaration, reproducibility evidence, train-only preprocessing fit scope, preprocess-then-split leakage review, future/label-as-feature leakage review, prediction-time feature availability review, real-time/current feature freshness review, temporal split-order review, baseline comparison, named baseline comparator review, uncertainty/error-bar reporting, and named uncertainty-method review, with missing evidence surfaced as blocking questions;
- conservative security/privacy obligation scaffolding for secrets handling, secret log-exposure review, credential rotation/expiry/revocation review, PII/privacy handling, data/sensitivity classification, encryption-scope/key-management review, lawful-basis/consent review, retention/deletion review, purpose-limitation review, data-subject rights review, PII access audit/logging review, PII incident-response/breach-notification review, data-residency/cross-border transfer review, third-party/vendor/processor sharing review, access-boundary declarations, privilege-escalation review, authentication/session-management review, authentication/API abuse-protection review, API authorization/scope review, authentication/API transport-protection review, API/webhook input-validation review, webhook/callback request-authenticity review, API/webhook error-disclosure review, and destructive-action safety review, with missing evidence surfaced as blocking questions;
- PeTTa profile refusal records for malformed source-manifest record types (`PlainFile`, `SourceSpan`, `Section`, and `PlainItem`), malformed source-span identities/file links/byte bounds/line bounds, source spans linked to missing or refused PlainFiles, `RawTextOnly`, unsupported semantic levels, unsupported predicates, non-string predicate values, malformed fact record types/arity, object-fact subject mismatches, non-string or duplicate object IDs, malformed or duplicate validation-obligation/check IDs, validation-obligation target IDs and rationales, check-to-obligation IDs, links to obligations that were not emitted, check properties and evidence, undeclared check-status values, non-string or whitespace-only object and validation-obligation source-span IDs, and non-string object references;
- fail-closed source-manifest link gates that suppress sections and Plain items whose files, spans, parent sections, or parent items were not emitted, or whose emitted provenance/parent item belongs to a different file or section;
- fail-closed object and validation-obligation provenance when a source manifest is present: semantic objects with explicit non-emitted span references are suppressed with their facts, and `derived-from` atoms are emitted only for source spans admitted by the manifest gates, while absent optional provenance remains allowed;
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
- automatic publication, deployment, or executable generation workflows.

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

## Plain2MeTTa v2 project-state API

```python
from specatom_hs.projects import (
    ApprovalDecision, ArtifactKind, add_artifact, add_logical_ir,
    admit_compilation, annotate, create_project, decide, decide_logical_finding,
)

project = create_project("task-list", "Task list", source_text)
source = project.current(ArtifactKind.ORIGINAL_SPEC)
project = add_artifact(
    project,
    ArtifactKind.ELABORATED_SPEC,
    elaborated_text,
    upstream=[source.ref],
)
# Review comments are bound to exact artifact bytes and may target an item/section.
elaborated = project.current(ArtifactKind.ELABORATED_SPEC)
project = annotate(project, elaborated.ref, "reviewer", "Looks precise.", "item:REQ-1")
```

`add_logical_ir(project, content)` is the only logical-IR creation seam. It
fails closed until both the exact current elaborated spec and exact current
test spec have explicit `APPROVED` decisions with reviewer identities. A
later source/artifact edit or approval revocation transitively invalidates the
logical IR. Generic `add_artifact` calls cannot bypass this gate.

Use `project_to_dict` and `project_from_dict` for the versioned JSON-ready
boundary. Deserialization recomputes content hashes and rejects malformed or
forged provenance and approval bindings.

`add_logical_ir_document(project, document)` is the structured Phase 4 seam.
It accepts only typed declarations, contracts, obligations, dependencies,
provenance, and explicit operational holes; no executable-body field exists.
It atomically adds canonical logical-IR content and a hash-bound logical-review
artifact. `review_logical_ir` reports source-linked critical missing-definition,
uncovered-requirement, and unmarked-operational-gap findings. Critical open or
deferred findings set the derived `blocks_compilation` flag; repair and waiver
decisions require reviewer identity and rationale.

`decide_logical_finding` persists each attributed disposition as a new
immutable logical-review version. `admit_compilation` returns the exact current
logical-IR artifact only when it is explicitly approved, its exact hash-bound
review is present, and no critical finding is open or deferred. Deserialization
regenerates the baseline report and rejects dropped or rewritten findings.

`add_compiler_output(project, bundle)` is the inert Phase 5 persistence seam.
It accepts a strict `CompilerOutputBundle` only after `admit_compilation`
succeeds, binds the artifact to that exact logical-IR hash, requires per-file
spec traceability, and records `executed: false`. It stores generated text but
does not publish files, import Python, evaluate MeTTa, spawn processes, or run
tests. Unsafe paths, unknown fields, forged execution state, and stale compile
admission fail closed.

`sandbox_request_to_dict(handoff)` exposes the narrow Phase 6 adapter message
without invoking an adapter. `add_test_result(project, result)` accepts strict
per-test pass/fail/error/skip records only when their request digest binds to
the exact current sandbox handoff. Results include captured output, duration,
covered spec IDs, and a derived summary. The core package still contains no
host executor, generated-file publisher, or adapter invocation.

`add_traceability_report(project)` is the pure Phase 7 reporting transition.
It joins the exact original/elaborated/test/logical/output/handoff/result chain
to compiler-declared code locations and sandbox-returned test coverage. Each
spec ID is classified as passing, failing, skipped, or untested, with failure
details. Unknown test/spec IDs and forged or incomplete provenance fail closed.

For local persistence, `FilesystemProjectRepository` exposes only create, get,
save, and list-status operations. Project IDs are storage-safe lowercase slugs;
writes publish fully flushed JSON documents atomically, and malformed files,
unexpected entries, symlinks, or forged state fail closed.

`ProjectQueryService` is the narrow read-only boundary corresponding to project
list/status, version history, and trace inspection. It returns JSON-serializable
metadata, omits artifact bodies from history, and permits exact `spec_id`
filtering of the current traceability report. It has no rollback, mutation,
provider, network, or execution capability.

`ProjectCommandService` is the framework-neutral write boundary for the first
author/review operations. It exposes only persisted project creation, exact
hash-bound annotations, declared approval decisions, and optimistic
submission of elaborated-spec and test-spec versions. Each submission names
the exact current upstream artifact ID and content hash; stale or wrong-stage
references fail without a write. It has no generic artifact write, LLM
elaboration, compilation, provider, or execution method.

`specatom_hs.elaboration_protocol` defines the pure Phase 2 adapter messages.
Requests bind source text to an exact original-spec identity; responses bind to
the canonical request and require backend/model, interaction ID, token counts,
and timestamp provenance. `admit_elaboration` records deterministic validation
summaries and admits output only when every original `[id:...]`, `[covers:...]`,
and `:Concept:` marker remains in the elaborated spec and neither output has a
validation failure or blocking question. This module does not invoke or retry a
provider and does not persist returned content.

`ElaborationAdmissionService` is the adapter-independent return seam. It runs
the existing SpecAtom-HS validator over the combined elaborated-spec/test-spec
review corpus, rejects failures, blocking questions, marker loss, stale source
identity, or forged provenance, then commits the canonical interaction log and
both derived artifacts with one atomic repository save. Deserialization
re-runs validation and rejects rewritten diagnostics or interaction evidence.
It does not invoke a provider.

`ElaborationRequestService.build_request` is the corresponding read-only
outbound seam. It loads the exact current original-spec version and constructs
a content-hash-checked request with optional guidance and section scope. It
does not save state, select or invoke a provider, retry, or execute returned
content.

`ElaborationCoordinator` is the deliberately small provider invocation seam.
It receives an explicitly selected `ElaborationBackend` adapter and immutable
backend/model/temperature/token configuration, makes exactly one call, checks
returned provenance against that configuration, and routes the exact response
through `ElaborationAdmissionService`. It has no retry, fallback, provider
selection, credential, or partial-persistence policy.

`ReadOnlyProjectApplication` is a server-independent WSGI adapter for that
service. It exposes only `GET /api/projects`, `GET /api/projects/:id`,
`GET /api/versions/:id`, and `GET /api/trace/:id` (with an optional single
`spec_id` query). It does not bind a socket or add mutation, execution, LLM, or
provider capabilities; an external deployment may mount it deliberately.

`ProjectCommandApplication` is the separate POST-only WSGI adapter for the
command service. It accepts exact `application/json` bodies with an explicit
canonical `Content-Length` of at most 1 MiB, rejects duplicate/unknown fields,
and exposes only project creation, exact-upstream spec submission, and exact
artifact-bound annotation and decision routes. It starts no listener and has
no generic artifact mutation, compile, provider, or execution route.

```python
from specatom_hs.project_repository import FilesystemProjectRepository
from specatom_hs.project_queries import ProjectQueryService
from specatom_hs.project_commands import ProjectCommandService
from specatom_hs.project_transport import ProjectCommandApplication, ReadOnlyProjectApplication

projects = FilesystemProjectRepository("./plain2metta-projects")
project = projects.create("task-list", "Task list", source_text)
status = projects.list_statuses()[0]
queries = ProjectQueryService(projects)
commands = ProjectCommandService(projects)
history = queries.version_history("task-list")
application = ReadOnlyProjectApplication(queries)
command_application = ProjectCommandApplication(commands)
```

## CLI usage

Install the frozen v0.1 alpha into an isolated environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --no-build-isolation .
.venv/bin/plain2metta --all examples/auth_service.plain
```

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

# SpecAtom-HS v0.1 Target Profile (Frozen)

Date frozen: 2026-07-02
Status: frozen for the v0.1 demo milestone

## Purpose

The v0.1 profile is a conservative, auditable Plain-like input to SpecAtom-HS JSON and PeTTa/MeTTa reified-atom profile. It deliberately favors source provenance, explicit Unknown/Question records, and backend refusals over inferred semantics or executable generation.

## Supported in v0.1

### Source provenance

- `PlainFile` records with preserved UTF-8 source text and reproducible SHA-256 digests.
- `SourceSpan` records with byte-precise `start_byte`/`end_byte`, line numbers, and file links.
- `Section` records linked to indexed files and source spans.
- `PlainItem` records linked to sections, files, and source spans.
- Validation that source spans, file digests, and section/item file links are internally consistent.

### Concepts

- Concept definitions and references from explicit markers and conservative aliases:
  - `:Concept:`
  - `[def:...]`
  - `[ref:...]`
  - `[concept:...]`
  - `[external:...]`
  - bare definition/glossary-style definitions
- External concept links.
- Unresolved concepts represented as questions rather than silently accepted references.
- Exact occurrence spans for concept markers, including references on multi-line item continuations.

### Requirements and acceptance tests

- Requirement objects.
- Acceptance-test objects.
- Coverage claims linking tests to requirements.
- Explicit labels via `[id:...]` and `[covers:...]`.
- Document-scoped coverage-label resolution, including forward references.
- Duplicate-label ambiguity detection.
- Orphan acceptance-test detection.

### Validation

The v0.1 profile includes all current structural validators:

- Plain file digest validation.
- Source-span byte-bound and line-number validation.
- Section/item file, section, and source-span link validation.
- Object semantic-level and source/generated provenance validation.
- PeTTa reified-profile semantic-level support validation.
- Object fact arity validation.
- Object fact subject validation.
- Object fact declared-reference validation.
- Validation-obligation source-provenance and target validation.
- Check-record status, evidence, obligation-link, and target/property consistency validation.

### PeTTa reified profile

- Profile-filtered reified atom emission for supported semantic levels and fact predicates.
- Source provenance manifest atoms: files, spans, sections, items, and derived-from links.
- Reified validation obligations, rationales, checks, check-obligation links, and evidence.
- Backend refusal records for unsupported facts, malformed facts, unsupported semantic levels, and executable skeleton requests.

### Refusals

v0.1 explicitly refuses or blocks:

- `RawTextOnly` export through the PeTTa reified profile.
- Unsupported fact predicates.
- Malformed fact arity.
- Fact subject mismatches.
- Executable skeleton generation.

## Not supported in v0.1

The following are intentionally deferred and must not be implied by v0.1 outputs:

- Full Plain grammar.
- Deep English semantics.
- Executable code skeleton generation.
- SUMO/EXPO/Hyperseed bridge tables.
- PLN confidence propagation.
- Rholang process profiles.
- MeTTa-IL profile.
- Information-flow or temporal validation.
- Phase 2 objects: `Scope`, `EpistemicStatus`, `Evidence`, `Interpretation`, and `Bridge`.
- Phase 3 facets: witnesses/backend artifacts, process/resource placeholders, and revisions.

## Unknown/Question behavior in v0.1

v0.1 converts underspecified or unsupported material into auditable `QuestionObject` records when possible:

- Unsupported fact predicates become `QuestionObject` records.
- Unsupported semantic levels become `QuestionObject` records.
- Unresolved concepts become `QuestionObject` records.
- Missing or ambiguous coverage becomes `QuestionObject` records.
- Orphan acceptance tests become `QuestionObject` records.

These questions are expected outputs, not compiler crashes. They mark profile gaps and preserve provenance for later review.

## Success criteria

Given a Plain-like input containing concepts, requirements, acceptance tests, and at least one intentional gap, v0.1 succeeds when it produces:

1. SpecAtom-HS JSON.
2. `.metta` reified atoms for the conservative PeTTa profile.
3. A diagnostics report with Pass/Fail/Unknown checks.

All Pass/Fail/Unknown checks must be auditable with evidence, and the pipeline must not hallucinate executable semantics.

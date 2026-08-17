# General semantic validation: Stage 0 interface and trust map

Status: draft Stage 0 freeze for specification revision 0.2. This document
describes the interfaces at public task-branch baseline `752debd`; it does not
introduce Stage 1 artifacts.

## Canonical evidence vocabulary

The normative vocabulary is G0 preserved, G1 structured, G2 executable, G3
examples, G4 properties, G5 proved, and G6 observed
(`plain2metta-general-semantic-validation-spec.tex`, lines 66-91). Grades are
per obligation and form a vector; none is silently promoted to another. The
current UI's `semantically_validated` Boolean is compatibility-only and means
that an exact curated example-specific G3 oracle passed in both runtimes. It
is not the future general verdict representation.

## Current interfaces

| Boundary | Current source | Frozen behavior and trust consequence |
|---|---|---|
| Immutable project chain | `src/specatom_hs/projects.py:16-109`, `620-986` | Versioned content-addressed artifacts, exact upstream refs, approvals, transitive invalidation, and fail-closed deserialization are the trusted persistence spine. |
| Logical IR | `src/specatom_hs/logical_ir.py:40-118`, `141-238`, `242-468` | Schema v1 contains declarations, contracts, requirement obligations, dependencies, operational holes, and review findings. It is non-executable and must remain readable during migration. |
| Compiler output | `src/specatom_hs/compilation_protocol.py` and `src/specatom_hs/projects.py:369-440` | Compilation is admitted only from the exact approved reviewed chain. Output is inert, path-bounded, content hashed, and marked unexecuted. |
| Sandbox result | `src/specatom_hs/sandbox_protocol.py:18-120`, `src/specatom_hs/projects.py:441-481` | An injected adapter receives an exact handoff. Result records are request-hash and adapter bound; the core has no ambient executor authority. |
| Traceability | `src/specatom_hs/traceability.py:13-171`, `src/specatom_hs/projects.py:482-521` | The report reconstructs the complete ordered provenance chain and rejects incomplete, reordered, stale, or forged inputs. |
| Evaluation composition | `src/specatom_hs/evaluation.py:31-293` | Three exact reviewed profiles generate MeTTa/Python and compare complete normalized output. Unknown/reworded inputs execute only as trace checks and fail closed for semantic validation. This is curated G3 evidence, not general validation. |
| Web boundary | `webapp/app.py:13-54` | Flask accepts bounded UTF-8 Plain input (128,000 bytes), serves examples/health, and returns evaluation JSON. It must not gain command, credential, or arbitrary-path inputs. |
| Hyperon runtime | `src/specatom_hs/reference_runtime.py` | The adapter invokes an exact executable under timeout/resource bounds and checks pinned version 0.2.10. Runtime success alone is only G2. |
| Python runtime | `src/specatom_hs/reference_runtime.py` | A bounded isolated subprocess executes generated Python; exact independent expected output is required for curated G3. |

## Role separation and trust boundaries

The revision 0.2 roles are interpretation author, implementation author,
validation author, and evidence runner (specification lines 95-121). Future
interfaces must record each role's provenance independently. A validation
author may read approved source and contracts but not generated implementation
bodies by default. The evidence runner may execute only immutable admitted
artifacts and has no authority to interpret, approve, compile, or mutate them.

Trusted inside the core are canonical serialization, hash calculation, strict
schema validation, exact-chain reconstruction, and invalidation. Untrusted are
Plain prose, provider/model output, generated code, validation plans, runtime
stdout/stderr, solver/model-checker output, uploaded filenames, and PR text.
Hyperon, Python, Hypothesis, TLC, Z3, Lean, Mathlib, and their launchers are
identified external dependencies, not part of the semantic trusted core.
Network, secrets, arbitrary host paths, and shell commands remain outside all
runtime adapters.

## Compatibility and migration rules

1. Existing schema-v1 logical IR, compiler output, sandbox result, and
   traceability payloads remain byte-readable and retain their present meaning.
2. New semantic artifacts use new kinds and explicit schema versions; fields
   are never retrofitted into an old envelope with changed meaning.
3. The current curated result remains representable as G0/G1/G2/G3 evidence
   with an explicit `curated-exact-profile` method and shared-dependency note.
   It must not be upgraded to G4 or G5.
4. New verdicts bind exact reviewed source, contract, plan, implementation,
   runtime, and evidence hashes. Any byte change invalidates downstream state.
5. Unknown grades, methods, statuses, duplicate fields/IDs, partial records,
   stale refs, alternate paths, or unsupported schema versions fail closed.
6. Existing read routes and default metadata responses stay compatible.
   Semantic-plan/result bodies require new narrow routes and separate bounds.
7. Runtime adapters remain injected and command-free. Tool upgrades create new
   runtime identities and invalidate dependent evidence; they never rewrite
   prior evidence.
8. The legacy `semantically_validated` Boolean is derived only for old clients.
   New clients consume per-obligation grade vectors and status
   pass/fail/unknown/blocked.
9. Stage 1 may add immutable semantic artifact kinds only after this Stage 0
   toolchain and regression gate passes.

## Stage 0 pinned toolchain

- Hypothesis 6.138.15 and Z3 4.15.3 in an experiment-local Python environment.
- TLC 1.7.4 (`tla2tools.jar` SHA-256 `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`)
  under project-local Temurin JRE 21.0.12+8 (archive SHA-256
  `8a379a67c91a3ae61ffb33d46e0a40c7ba35e70713c4db31cfca30492f792eff`).
- Lean 4.33.0 (archive SHA-256 `4b3fb03c29a1e0a253fb1d11f9bae3725f19a0dc6fc09b3ea16d2c9df3349e2c`)
  with Mathlib v4.33.0 at `db584cd6d46c92f209a44c0f1c829460d327499d`.
- Hyperon CLI 0.2.10 from the existing evaluation runtime environment.

The unchanged upstream DieHard TLC example reproduced its expected
counterexample, and Mathlib's documented cache fetch plus unchanged
`lake build` completed all 8705 jobs.

## Stage 0 residual risks

- Tool distributions remain external immutable inputs and must be fetched by
  recorded URL and verified by hash; they are not vendored into the repository.
- The existing exact-profile generator and oracle share deterministic profile
  data, so correlated-error risk is explicit and limits the evidence to G3.
- A live Tailnet service is operational evidence only for its recorded replay;
  it is not a public endpoint or G6 production observation.

# Evaluation vertical route/service contract

Status: frozen Gate 1 contract for revision 0.2. This document defines the
replacement contract for `POST /api/evaluate`; it does not claim that the
legacy implementation currently satisfies it.

## Route boundary

`POST /api/evaluate` accepts exactly one duplicate-free JSON object,
`{"text": <UTF-8 string>}`, with both the complete request and decoded source
bounded to 128,000 bytes. The source must byte-match one of the three reviewed
files returned by `GET /api/examples`. Reworded, mutated, blank, malformed, or
otherwise unsupported input fails closed without a promoted downstream
artifact. The compatibility evaluator may remain at a separately named and
explicitly labelled legacy route during migration, but it is not admissible
evidence for this contract.

The route calls one server-side vertical service. The client supplies neither
artifact identities, plans, approvals, implementations, backend selections,
expected observations, grades, credentials, nor download authority. A fresh
request creates an isolated canonical project chain; no artifact from a failed
request is promoted as current.

## Exact stage mapping

For each supported source the service performs the following ordered work and
returns only data reloaded from the canonical artifact repository:

1. Stage 1 stores the exact source and canonical `SemanticContract` and
   `ValidationObligation` documents. Every identity and SHA-256 content hash is
   returned with its source-clause ancestry.
2. Stage 2 validates, lowers, and deterministically interprets the typed finite
   contract calculus. A typed hole or unsupported operation blocks execution;
   it is never replaced by prose or an invented value.
3. Stage 3 creates exactly one independently authored validation plan, stores
   its review, and requires an approval bound to the exact plan, contracts,
   obligations, and source hashes. Missing, rejected, edited, stale, or
   mismatched plans/reviews/approvals invalidate all downstream state.
4. Stages 4--7 execute only plan-authorized adapters: pinned Hypothesis,
   bounded TLC, bounded Z3, pinned Lean, pinned Hyperon, and bounded Python.
   Each admitted result retains request hash, tool identity/hash/version,
   resource bounds, inputs, observations, and exact ancestry. Inapplicable
   tools produce a justified `Unknown`/non-applicability record; absence is not
   a pass. Timeouts, malformed or misattributed evidence, hash mismatches,
   counterexamples, proof/model/property failures, and runtime disagreement
   remain conservative evidence.
5. Stage 8 composes each obligation's verdict from admitted evidence using the
   cross-tool composer. The returned `grade_achieved.vector` contains exactly
   Boolean `G0` through `G6`; status, counterexamples, assumptions, holes, and
   residual risk are composer output. Neither the route nor JavaScript infers
   or fills grades.
6. Stage 9 projects the stored chain as `ancestry`, containing canonical nodes
   for every applicable Stage 1--8 artifact and edges equal to their stored
   upstream references. The response also includes plan/review/approval state,
   backend attribution, verdicts, and release metadata. Artifact bodies remain
   available only through the existing exact-ID, exact-hash, authorized
   download gate. The browser renders only these server-returned fields.

`ancestry.stages` must report the traversed stage numbers `1` through `8`, and
every node contains `stage`, `kind`, `artifact_id`, `content_hash`, `state`, and
`upstream`. `verdicts` is non-empty and each verdict binds its obligation,
implementation, approved plan, evidence references, and exact G0--G6 vector.

## Release metadata and acceptance

Stage 10 is not rerun per request. The repository-shipped
`plain2metta-vertical-acceptance/v1` corpus, mutation threshold/result, corpus
content hash, and calibration release identifier are immutable release
metadata. Startup/service construction validates them once; each response
returns their exact identifiers and hash as `release_metadata.stage10`, and
the verdict policy binds that metadata. A missing, malformed, changed, or
unbound calibration artifact makes the service unavailable rather than
silently selecting defaults.

Stage 11 is never a runtime stage. It is the clean-checkout acceptance gate
which instruments this UI request path, proves traversal of Stages 1--9 and
consumption of Stage 10 metadata, replays adversarial invalidation and pinned
backends, and obtains an independent code-path audit.

## Bounds and atomic failure

The service inherits the checked-in adapter bounds: Hypothesis 3 seconds
(2 CPU seconds, 128 MiB, 1 MiB file, one process), TLC 8 seconds (5 CPU
seconds, 3 GiB, 8 MiB file, one worker), Z3 5 seconds (4 CPU seconds,
512 MiB, 4 MiB file), Lean 45 seconds (30 CPU seconds, 8 GiB, 64 MiB file,
one thread), Hyperon 2 seconds, and Python 2 seconds (2 CPU seconds, 128 MiB,
1 MiB file, one process). No retry, fallback provider, host-shell authority, network access,
client-selectable executable, or partial promotion is allowed. Backend
unavailability is explicit `Unknown` when the approved plan permits
non-applicability; required evidence that is unavailable prevents the required
grade. Repository write failure, concurrent ancestry change, invalid evidence,
or any trust-boundary error aborts the request atomically.

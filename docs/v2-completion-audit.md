# Plain2MeTTa v2 completion audit

Source: `plain2metta-spec-v2-revised-logical-ir.pdf`, SHA-256
`10969aabb39d4de057ca06cce151b780c07b381802a079f411814826665b2c4c`.
Audit date: 2026-08-14. Branch: `agent/plain2metta-v2-logical-ir`.

## Implemented and acceptance-tested

- PDF §§3.2–3.8: immutable, content-addressed artifacts span original,
  elaborated, reviewed, logical-IR, compiler-output, sandbox, result, and
  traceability phases. Exact upstream changes invalidate derived state.
- PDF §3.3: provider-neutral elaboration envelopes, marker/coverage validation,
  one-call adapter seam, atomic admission, provenance logs, and auth/ML gold
  fixtures.
- PDF §3.4: exact-version review decisions, comments, reviewer/timestamp data,
  edited or byte-identical reviewed snapshots, and strict GET/POST boundaries.
- PDF §3.5: typed non-executable logical IR, contracts, obligations, explicit
  operational holes, all eight named critical-finding categories, exact finding
  decisions, and compile blocking until findings are resolved or waived.
- PDF §§3.6–3.8: exact-input compilation envelopes and atomic inert output,
  opt-in sandbox adapter/result admission, metadata-only result retrieval, and
  deterministic nine-artifact trace reconstruction.
- PDF §§4.3 and 5.4: narrow framework-neutral API/storage primitives exist for
  the implemented phases; malformed, stale, expanded, or alternate identities
  fail closed.
- PDF §6 verification intent: the original compiler remains unchanged and the
  provider-free suite passes, including an end-to-end persisted-chain replay
  and upstream-mutation invalidation test.

## Deliberately incomplete

- PDF §4.2 web UI components (workflow bar, editors, logical review, generated
  code, test-output drill-down, and version sidebar) are not implemented.
- PDF §§5.1 and 6 Steps 2–3: no concrete OpenClaw/OpenAI/Anthropic/Ollama
  provider is bundled. Only explicitly injected provider-neutral seams exist.
- PDF §§3.6 and 6 Step 6: generated output is admitted as inert artifacts; a
  concrete production compiler and post-generation MeTTa/Python execution
  validator remain future work.
- PDF §§5.3 and 6 Step 7: no built-in host/container executor is provided. The
  sandbox boundary requires an explicit external adapter and preserves the
  zero-trust, opt-in policy.
- PDF §5.2 automatic retry is intentionally not implemented: current behavior
  is one-call and fail-closed to keep provider spend and mutation bounded.
- The PDF's legacy route names and automatic default guidance are not treated
  as satisfied by the narrower version-bound routes and explicit guidance.

The revised logical-IR core is therefore acceptance-complete as a provider-free,
non-executing artifact pipeline, but the overall PDF product plan is not complete.

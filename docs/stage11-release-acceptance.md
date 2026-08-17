# Stage 11 release acceptance

This document records the release-candidate boundary for revision 0.2. It is
an acceptance record, not a release authorization and not a proof that
arbitrary natural-language requirements are correct.

## Reproduction

From a clean checkout of the Stage 11 commit recorded in the final experiment,
run:

```sh
scripts/run-stage11-acceptance.sh
```

Pinned Hypothesis, TLC, Z3, Lean, Hyperon, and Python replay additionally uses
the project-local tools and hashes recorded by the Stage 0--10 experiment
chain. No system installation, network fetch, or elevated privilege is part of
the replay. The final experiment records the exact commands and tool hashes.

## Threat-model matrix

| Threat or acceptance property | Required outcome | Regression boundary |
| --- | --- | --- |
| Source, contract, obligation, plan, or approval byte changes | All downstream evidence and verdicts become stale | semantic artifact, plan, backend, and verdict tests |
| Malformed, partial, duplicated, path-confused, hash-mismatched, or unknown-version artifacts | Reject atomically with no partial writes | strict schema/API/backend tests |
| Unsupported or unresolved executable meaning | `Blocked` or `Unknown`; never semantic validation | calculus, plan, vertical-policy, and UI tests |
| Wrong output or cross-runtime divergence | `Fail`; exit zero cannot override observations | dual-runtime and verdict tests |
| Timeout or resource exhaustion | `Unknown` or `Blocked`, with exact bounds retained | bounded sandbox and backend tests |
| Validation author sees generated implementation bodies | Reject role-confused input | validation-plan role-separation tests |
| Missing authorization or stale review approval | Reject before execution or download | semantic API authorization tests |
| Duplicate request framing or oversized request | Reject deterministically | API framing and bound tests |
| Artifact download identity mismatch | Reject; immutable exact-hash download only | semantic API download tests |
| A single backend passes while required evidence is missing | Grade cannot be promoted | conservative G0--G6 verdict tests |
| TLC/Z3 evidence represented as Lean proof | Reject evidence kind mismatch | Lean/verdict attribution tests |
| Mutation survivor | Review and classify; never convert score to correctness probability | vertical acceptance mutation report |

## Honest claim boundary

G0--G6 grades are per-obligation evidence vectors with explicit assumptions,
holes, bounds, and shared dependencies. A grade is not a blanket label for the
input document. Unsupported arbitrary input remains unvalidated. Finite tests,
bounded model checking, SMT results, and kernel-checked theorems retain their
distinct trust and scope.

## Recovery

The evaluation service is unprivileged and Tailnet-only. Stop it with
`tmux kill-session -t plain2metta-eval`. Restart it from the reviewed checkout
using the recorded Stage 9 service command, then confirm `/api/health` before
evaluation. If any ancestry, tool hash, or replay result differs, discard the
new evidence, retain the immutable prior artifacts, and rerun from a clean
checkout; never edit an admitted artifact in place.

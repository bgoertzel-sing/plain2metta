# Plain2Metta PR #3 merge and VM2 deployment

- Project: `specatom-hs`
- Started: `2026-08-18T15:33:37Z`
- Finished: `2026-08-18T16:26:41Z`
- Status: `succeeded`
- Local or remote: `local + existing ASI:Cloud VM2`
- Source PR: `bgoertzel-sing/plain2metta#3`
- Accepted source commit: `1755dddcb31dc02c04d7db35dec01ba1fb6b9215`

## Objective

Merge the already accepted evaluation-UI vertical to `main`, then deploy the
exact merged result to the existing VM2 and verify the real browser/API route.

## Resource and safety bounds

- Use only the already-running VM2; do not provision, start, resize, or expand
  storage and do not alter provider billing state.
- Transfer only the public Plain2Metta repository/artifacts required to run the
  UI. Do not transfer OpenClaw state, unrelated project data, or credentials.
- Capture the existing checkout, process, listener, and supervisor state before
  mutation and preserve an explicit rollback target.
- Bind only to the already approved private/Tailnet or localhost interface
  unless Ben separately authorizes public exposure.

## Acceptance

Record the merged commit and clean Git state; verify exactly one intended VM2
service; verify GET `/`; and POST all three bundled examples to `/api/evaluate`,
checking server-derived ancestry, Stage 9 projection, Stage 10 metadata, and
G0--G6 verdict vectors. Roll back if the production smoke fails.

## Evidence files

Commands, non-secret environment and topology, raw smoke output, Git identity,
rollback status, and final interpretation will be added during execution.

## Result

PR #3 merged without altering its accepted head. GitHub and `origin/main`
agree on merge commit `5ce102cb02e72f377314205b28f102e5fc39911f`.
VM2 records that commit in the immutable release directory and runs one
enabled/active `plain2metta-vm2.service` worker bound only to
`127.0.0.1:8081`.

The first canary failed closed because root-owned Lean cache trace files were
not readable by the unprivileged service; rollback passed before diagnosis.
After the cache permission repair, an initial retry also returned 422 because
the canary's shell substitution stripped the exact example's trailing newline;
rollback passed again. The corrected JSON-preserving canary passed GET `/`,
health, examples, and POST `/api/evaluate` for `01_greeting`, `02_task_list`,
and `03_forecast`. Each response contains Stage 1--8 ancestry, Stage-9 schema
`plain2metta-evaluation-evidence/v1`, Stage-10 release
`plain2metta-r02-stage10-20260817`, and all G0--G6 server-derived keys.

Final topology at `2026-08-18T16:26:41Z`: service enabled and active, one
localhost listener, one Plain2Metta process. Release and diagnostic artifacts
are preserved under `/opt/plain2metta/releases/`; no provider resource was
created, started, resized, or otherwise changed.

# Run 20260818T072517Z-plain2metta-evaluation-stage11-clean-checkout: plain2metta-evaluation-stage11-clean-checkout

- Project: `specatom-hs`
- Started: `2026-08-18T07:25:17Z`
- Finished: `2026-08-18T07:30:22Z`
- Status: `succeeded`
- Local or remote: `local`
- Working directory: `<research-workspace>`

## Question

Does the pushed task branch pass the updated Stage 11 vertical acceptance
script from a fresh temporary clone with no inherited repository build state?

## Hypothesis or expected behavior

The fresh clone should resolve local and remote task-branch identities to the
same exact commit, rebuild the pinned Lean package, pass the focused real-route
vertical suite and complete provider-free suite, and pass every repository
hygiene check.

## Inputs

- Git state: `git.txt`
- Environment: `env.txt`
- Command: `command.sh`
- Random seeds/data identifiers: record here when relevant.

## Results

- Exit status: 0
- Standard output: `stdout.log`
- Standard error: `stderr.log`
- Machine status: `status.json`
- Artifacts: `artifacts/`

The clone reported local and remote commit
`1755dddcb31dc02c04d7db35dec01ba1fb6b9215`. The pinned Lean build completed
3015 jobs. The focused phase passed 106/106 tests in 54.455 seconds and full
discovery passed 777/777 tests in 70.111 seconds. The script then completed
compilation, diff, credential-pattern, large-file, and untracked-file checks
and exited 0. Total recorded wall time, including clone and clean Lean build,
was 305 seconds.

Artifact SHA-256:

- `stdout.log`: `3be23a76d0a5a8d2b9232fc029eb0f41a1756d1c76bd5aa646d01de1dc8aa76a`
- `stderr.log`: `8a6416a7f6831833e3ad458f0dfc5bfc60ff944d2530342765185b8f34afab08`
- `command.sh`: `8a77621d9409b16f280e33fdaba17fa33841790f6987b752497bd39e9b22e86e`

## Interpretation

Observed: the source checkout was a clean clone of only
`agent/plain2metta-public-evaluation-ui`; its checked-out and remote-tracking
commit IDs matched exactly. The complete Stage 11 script exited 0 with the
test counts and timings above. A post-run `git status --short --branch` remained
clean and aligned with the remote.

Inferred: the Stage 11 vertical gate is reproducible without inherited Git or
Lean build state at the pushed task-branch commit. This does not provide the
required independent code-path audit, so the vertical task is not complete.

## Reproduction

Run `command.sh` in the recorded environment after reviewing it. It creates a
new unique scratch clone and runs `scripts/run-stage11-acceptance.sh` there.

## Follow-up

Perform one independent read-only code-path audit proving that the browser's
`POST /api/evaluate` request traverses Stages 1--9, consumes immutable Stage 10
metadata, and contains no client-side grade synthesis. Do not mark the task
complete unless that audit passes.

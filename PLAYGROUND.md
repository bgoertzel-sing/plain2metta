# Plain2Metta Monday playground

This is a compact lab bench for compiling a readable Plain task-list
specification into source-preserving JSON, conservative reified MeTTa, and a
diagnostics report. It then asks a real MeTTa backend whether the edited
specification contains exactly one acceptance test covering `TASK-ARCHIVE`.

## Prerequisites and one-command run

Use Python 3 with `venv` support and the Hyperon MeTTa CLI version `0.2.10`.
The runner deliberately refuses another MeTTa version rather than silently
changing query semantics. From a fresh checkout, run:

```bash
bash scripts/run-playground.sh
```

The command creates an isolated Python environment under
`build/monday-playground/`, installs this checkout without build isolation,
compiles both bundled inputs, runs the pinned query, and prints the diagnostic
delta. It does not use a hosted model or paid compute.

The successful query line is:

```text
TASK-ARCHIVE coverage: [(<acceptance-test-id> <requirement-id>)]
```

The two opaque IDs are stable source-derived identifiers. The surrounding
single-element list is significant: the MeTTa query joins a
`CoverageClaim`, `Covers`, and `RequirementLabel` and requires exactly one
matching test/requirement pair.

## The episode

[`examples/playground/task_list.plain`](examples/playground/task_list.plain)
contains two requirements and one acceptance test. The archive requirement has
no test, so its concise diagnostics include:

```text
requirements | 2
acceptance_tests | 1
coverage_unknown | 1
```

[`examples/playground/task_list_edited.plain`](examples/playground/task_list_edited.plain)
adds this one human-checkable line:

```plain
- [covers:TASK-ARCHIVE] Given a completed task, when the user archives it, then it leaves the active task list.
```

The edited diagnostics therefore report two acceptance tests and
`coverage_unknown | 0`. Its JSON and `.metta` outputs also gain the archive
test object, `CoverageClaim`, and concrete `Covers` relation used by the query.
Both inputs compile with zero failing checks.

Generated files are in `build/monday-playground/`:

- `task_list.json`, `task_list.metta`, and `task_list.diag`
- `task_list_edited.json`, `task_list_edited.metta`, and
  `task_list_edited.diag`

The regression ceiling for each input is fewer than 1,000 checks, 1 MB of
JSON, 500 KB of MeTTa, and 50 KB of diagnostics. These bounds keep the default
episode practical to inspect and guard against combinatorial self-check
growth.

## Things to edit

Change a requirement label after `[id:...]`, change a coverage target after
`[covers:...]`, remove the added archive test, or add another short requirement
and matching test. Re-run the command after editing the bundled files. For
scratch work that leaves the default build alone, choose another output
directory:

```bash
PLAYGROUND_WORK_DIR=/tmp/plain2metta-playground bash scripts/run-playground.sh
```

`PYTHON_BIN` selects a Python interpreter and `METTA_BIN` selects the MeTTa
executable. The latter must still report exactly `0.2.10`.

## Model and limits

Plain2Metta recognizes a conservative, shallow Plain profile. It preserves
source files, spans, sections, items, explicit semantic markers, validation
obligations, and checks. MeTTa output is reified for review and querying; it is
not generated application code.

This playground demonstrates explicit label-based requirement coverage, not
deep natural-language understanding or proof that an implementation passes a
test. Unknown checks are review prompts, while Fail checks make the compiler
exit nonzero. The compiler intentionally does not infer missing acceptance
tests from prose, generate executable skeletons, publish artifacts, or invoke
remote services.

## Revision

The pinned backend/query baseline is repository commit
`b4bbfc1aa4802690e9e47cfc7facce102eef00ac` with Hyperon MeTTa `0.2.10`.
Every run prints the exact checkout revision; the clean-room experiment
records the final immutable milestone revision together with hashes, timings,
sizes, and observed semantics.

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
- conservative ML/time-series methodology obligations for metric declaration, metric/task appropriateness review, horizon/frequency declaration, reproducibility evidence, train-only preprocessing fit scope, preprocess-then-split leakage review, future/label-as-feature leakage review, prediction-time feature availability review, temporal split-order review, baseline comparison, named baseline comparator review, uncertainty/error-bar reporting, and named uncertainty-method review, with missing evidence surfaced as blocking questions;
- conservative security/privacy obligation scaffolding for secrets handling, secret log-exposure review, PII/privacy handling, data/sensitivity classification, lawful-basis/consent review, retention/deletion review, purpose-limitation review, data-subject rights review, data-residency/cross-border transfer review, third-party/vendor/processor sharing review, access-boundary declarations, privilege-escalation review, and destructive-action safety review, with missing evidence surfaced as blocking questions;
- PeTTa profile refusal records for `RawTextOnly`, unsupported semantic levels, unsupported predicates, malformed fact arity, and object-fact subject mismatches;
- profile-filtered source provenance manifest atoms, object facts, validation obligations, rationales, check records, check-obligation links, and check evidence only when supported by `petta_reified_v0`.

## What is intentionally not supported

- full Plain grammar;
- deep English semantics;
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

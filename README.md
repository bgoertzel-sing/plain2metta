# specatom-hs

Local-only prototype scaffold for SpecAtom-HS, a source-preserving Plain-like specification IR before any executable code generation.

This repository currently contains two layers:

- `plain_to_metta`: the earlier stdlib MVP compiler used by the project notebook examples.
- `specatom_hs`: the minimal scaffold recommended by the SpecAtom-HS source summary, with small modules for schema, source indexing, pass registry, validation records, and conservative PeTTa backend gates.

## What is intentionally supported

- stable source IDs, SHA-256 file digests, sections, bullet items, and byte/line spans;
- first-class validation-obligation and check records (`Pass`, `Fail`, `Unknown`);
- scaffold fact-arity and declared-reference validation for supported predicates, with Unknown predicate checks turned into explicit profile questions;
- validation-layer self-checks that ensure each check record cites an existing obligation and matches its declared property/target;
- conservative concept markers (`:Concept:`, `[def:Concept]`, `[ref:Concept]`, `[concept:Concept]`, and definition/glossary `Concept:` bullets);
- shallow requirement/test coverage obligations with Pass/Unknown checks and missing-test questions;
- PeTTa profile refusal records for `RawTextOnly`, unsupported semantic levels, unsupported predicates, and malformed fact arity;
- profile-filtered reified object facts plus validation obligations, rationales, check records, check-obligation links, and check evidence only when supported by `petta_reified_v0`.

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

# Graduated Plain examples

The numbered files are a progression for the web playground. Choose them from
the **Load an example** menu, compile them unchanged, then alter one definition,
requirement, or `[covers:...]` link and compare the diagnostics, MeTTa atoms,
and JSON.

| File | Level | What to explore |
| --- | --- | --- |
| `01_hello_world.plain` | Minimal | One concept-bearing requirement and one covering acceptance test. |
| `02_counter.plain` | Basic | Nested attribute bullets, three requirements, and a boundary condition. |
| `03_bookmark_manager.plain` | Intermediate | Multiple related concepts, search behavior, deletion, and five coverage links. |
| `04_chat_system.plain` | Advanced | External systems, persistence, notifications, time constraints, and multiple tests for one requirement. |
| `05_knowledge_graph.plain` | Most complex | Typed graph entities, rules, external AtomSpace/PLN dependencies, integrity constraints, batch import, and weighted inference. |

Validation for this suite deliberately distinguishes structural failure from
review questions. Every numbered example must:

- be returned by `GET /api/examples`;
- compile through `POST /api/compile` with HTTP 200;
- emit parseable JSON and nonempty MeTTa/diagnostics output;
- have zero `Fail` checks; and
- have only `Pass` results for requirement/test coverage checks.

`Unknown` checks and backend refusals are expected: the current compiler is
conservative and asks for evidence it cannot safely infer from prose. They are
useful prompts for experimentation rather than evidence that compilation
failed.

# Reproducibility records for the expanded Plain2Metta report

This directory publishes the bounded evidence package used by
`docs/reports/plain2metta-architecture-and-worked-examples-expanded.{tex,pdf}`.
It is intended to let a reviewer or another AI inspect the claims in the
report alongside the exact code on this branch.

## Contents

- `stage11-vertical/`: the accepted-branch Stage 11 run (106 focused route
  tests, 777 complete provider-free tests, Lean build, and hygiene gates).
- `stage11-clean-checkout/`: repetition from a fresh clone at exact commit
  `1755dddcb31dc02c04d7db35dec01ba1fb6b9215`.
- `independent-audit/`: read-only audit of the server/browser path and release
  acceptance wiring.
- `deployment-canary/`: the final non-secret health and three-example canary
  summary for merged commit
  `5ce102cb02e72f377314205b28f102e5fc39911f`.
- `report-build/`: Tectonic/PDF/text/section checks and three sampled page
  renderings for the revised report.

Each run retains its human-readable `RUN.md`, machine status, and selected raw
stdout/stderr. The report-build record also retains visual samples. Raw
environment captures, unrelated repository status, private host topology,
deployment scripts, and full API response bodies were intentionally omitted:
they are not needed to reproduce the code-path claims and can expose irrelevant
machine details. Local absolute paths in retained logs were normalized to
`<research-workspace>` or `<checkout>`.

## Reproduction

From a clean checkout of this branch, inspect and run:

```bash
bash scripts/run-stage11-acceptance.sh
```

To rebuild the report, install Tectonic and run:

```bash
tectonic docs/reports/plain2metta-architecture-and-worked-examples-expanded.tex \
  --outdir docs/reports
pdfinfo docs/reports/plain2metta-architecture-and-worked-examples-expanded.pdf
pdftotext docs/reports/plain2metta-architecture-and-worked-examples-expanded.pdf - | wc -w
```

Recorded report hashes:

- LaTeX: `f085e0392ba21bb0e64fce9239c49a0eb6d14f9d5aa7b3e8e03443551addfe6c`
- PDF: `1c9d6a564bb3c73f84acea92dbcd34a8ad7244fc8ac387c02f9cf0ed4c34da88`

## Claim boundaries

The evidence establishes behavior for the recorded finite corpus, pinned
tools, exact examples, and bounded runs. It does not establish unrestricted
Plain-language understanding, universal equivalence between arbitrary Plain
and MeTTa programs, or permanent production correctness. The benchmark tasks
in the report's appendix are design guidance, not completed benchmark results.

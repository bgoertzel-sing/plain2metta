# Run 20260819T153624Z-plain2metta-expanded-r2-compile: plain2metta-expanded-r2-compile

- Project: `specatom-hs`
- Started: `2026-08-19T15:36:24Z`
- Finished: `2026-08-19T15:36:28Z`
- Status: `succeeded`
- Local or remote: `local`
- Working directory: `<research-workspace>`

## Question

Does the revised expanded Plain2Metta report compile into an intact,
extractable PDF containing the new conceptual introduction, four benchmark
design briefs, and both requested work plans?

## Hypothesis or expected behavior

Tectonic should exit zero; `pdfinfo` should report an unencrypted readable
PDF; extracted text should contain all requested sections; and sampled title,
benchmark, and work-plan pages should be visually readable.

## Inputs

- Git state: `git.txt`
- Environment: `env.txt`
- Command: `command.sh`
- Input: `docs/plain2metta-architecture-and-worked-examples-expanded.tex`
- Random seeds/data identifiers: none.

## Results

- Exit status: 0
- Standard output: `stdout.log`
- Standard error: `stderr.log`
- Machine status: `status.json`
- Artifacts: `artifacts/`
- PDF: 30 pages, 139,354 bytes, unencrypted, PDF 1.5.
- Extracted text: 12,802 words over 1,624 lines.
- SHA-256 (TeX):
  `f085e0392ba21bb0e64fce9239c49a0eb6d14f9d5aa7b3e8e03443551addfe6c`.
- SHA-256 (PDF):
  `1c9d6a564bb3c73f84acea92dbcd34a8ad7244fc8ac387c02f9cf0ed4c34da88`.
- Visual samples: `artifacts/page-01.png`, `page-22.png`, and `page-27.png`.

## Interpretation

**Observed:** compilation exited zero; PDF metadata and text extraction passed;
all requested section markers were found; the three sampled pages were readable
and unclipped.  Tectonic emitted underfull/overfull box warnings, including
warnings inherited from long identifiers in the earlier report and narrow
cells in the new planning table.

**Interpretation:** the revised report is suitable for delivery.  The sampled
pages show no material rendering defect.  The compilation check does not
independently validate every conceptual recommendation; those are explicitly
presented as guidance for future benchmark authors, not completed benchmark
results.

## Reproduction

Run `command.sh` in the recorded environment after reviewing it.

## Follow-up

Write and independently review the full benchmark specifications before using
them as implementation acceptance contracts.

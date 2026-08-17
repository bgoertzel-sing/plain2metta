#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_dir"

export PYTHONPATH=src

# A clean checkout has no package-local Lean cache. Warm it with the exact
# Stage 0 toolchain before the bounded kernel-evidence tests execute.
lean_tools=/home/openclaw/research-agent/projects/specatom-hs/experiments/20260817T040300Z-plain2metta-stage0-tlc-lean/artifacts/tools/lean-4.33.0-linux/bin
if [[ -x "$lean_tools/lake" ]]; then
  (
    cd lean/Plain2MeTTaSemanticKernel
    PATH="$lean_tools:/usr/bin:/bin" LEAN_NUM_THREADS=1 timeout 180 "$lean_tools/lake" build
  )
fi

python3 -m unittest \
  tests.test_semantic_artifacts \
  tests.test_contract_calculus \
  tests.test_validation_plan \
  tests.test_hypothesis_backend \
  tests.test_tlc_backend \
  tests.test_smt_backend \
  tests.test_lean_backend \
  tests.test_verdict_composition \
  tests.test_semantic_api \
  tests.test_vertical_acceptance

python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q src tests
git diff --check

if rg -n --hidden -g '!*.pdf' -g '!*.png' -g '!*.jpg' \
  '(BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY|ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,})' .; then
  echo 'credential-like material found' >&2
  exit 1
fi

large=$(find . -type f \
  -not -path './.git/*' \
  -not -path './lean/Plain2MeTTaSemanticKernel/.lake/*' \
  -size +5M -print)
if [[ -n "$large" ]]; then
  printf 'unexpected files larger than 5 MiB:\n%s\n' "$large" >&2
  exit 1
fi

unexpected=$(git ls-files --others --exclude-standard)
if [[ -n "$unexpected" ]]; then
  printf 'unexpected untracked files:\n%s\n' "$unexpected" >&2
  exit 1
fi

#!/usr/bin/env bash
# Run the playground's semantic coverage query with the pinned Hyperon CLI.
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  echo "usage: playground-query.sh COMPILED.metta" >&2
  exit 2
fi

compiled_metta="$1"
metta_bin="${METTA_BIN:-metta}"
expected_version="0.2.10"

test -s "$compiled_metta"
actual_version="$("$metta_bin" --version)"
if [[ "$actual_version" != "$expected_version" ]]; then
  echo "expected Hyperon MeTTa $expected_version, got $actual_version" >&2
  exit 3
fi

query_file="$(mktemp)"
trap 'rm -f "$query_file"' EXIT
cp "$compiled_metta" "$query_file"
cat >>"$query_file" <<'METTA'

!(match &self
  (, (CoverageClaim $test TASK-ARCHIVE)
     (, (Covers $test $requirement)
        (RequirementLabel $requirement TASK-ARCHIVE)))
  ($test $requirement))
METTA

result="$("$metta_bin" "$query_file")"
if [[ ! "$result" =~ ^\[\([^[:space:]\(\)]+[[:space:]][^[:space:]\(\)]+\)\]$ ]]; then
  echo "expected exactly one TASK-ARCHIVE coverage pair, got: $result" >&2
  exit 4
fi
printf 'TASK-ARCHIVE coverage: %s\n' "$result"

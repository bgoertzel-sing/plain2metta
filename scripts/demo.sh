#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

printf 'SpecAtom-HS CLI demo\n'
printf '====================\n'

for input in examples/auth_service.plain examples/task_manager.plain examples/ml_timeseries.plain; do
  printf '\n>>> %s\n' "$input"
  PYTHONPATH=src python3 -m specatom_hs.cli --all "$input"
  printf '\n--- %s ---\n' "${input%.plain}.metta"
  cat "${input%.plain}.metta"
  printf '\n--- %s diagnostics summary ---\n' "${input%.plain}.diag"
  sed -n '1,4p' "${input%.plain}.diag"
done

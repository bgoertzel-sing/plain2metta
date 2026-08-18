#!/usr/bin/env bash
# Build and run the complete Monday playground episode from a fresh checkout.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work_dir="${PLAYGROUND_WORK_DIR:-$repo_root/build/monday-playground}"
python_bin="${PYTHON_BIN:-python3}"

mkdir -p "$work_dir"
"$python_bin" -m venv "$work_dir/venv"
"$work_dir/venv/bin/python" -m pip install --no-build-isolation --quiet "$repo_root"

cp "$repo_root/examples/playground/task_list.plain" "$work_dir/task_list.plain"
cp "$repo_root/examples/playground/task_list_edited.plain" "$work_dir/task_list_edited.plain"

"$work_dir/venv/bin/plain2metta" --all "$work_dir/task_list.plain"
"$work_dir/venv/bin/plain2metta" --all "$work_dir/task_list_edited.plain"
"$repo_root/scripts/playground-query.sh" "$work_dir/task_list_edited.metta"

printf '\nDiagnostic delta:\n'
grep -E 'requirements |acceptance_tests |coverage_(pass|unknown) ' \
  "$work_dir/task_list.diag" "$work_dir/task_list_edited.diag"
printf '\nArtifacts: %s\n' "$work_dir"
printf 'Revision: %s\n' "$(git -C "$repo_root" rev-parse HEAD)"

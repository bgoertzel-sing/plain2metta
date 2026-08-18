#!/usr/bin/env bash
# Fresh-install integration gate for the frozen Plain2Metta v0.1 profile.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:?usage: usability-gate.sh OUTPUT_DIR}"
python_bin="${PYTHON_BIN:-python3}"

if [[ -e "$output_dir" ]]; then
  echo "refusing to overwrite existing output directory: $output_dir" >&2
  exit 2
fi
mkdir -p "$output_dir"
"$python_bin" -m venv --system-site-packages "$output_dir/venv"
"$output_dir/venv/bin/python" -m pip install --no-use-pep517 "$repo_root"

for spec in auth_service task_manager ml_timeseries; do
  case "$spec" in
    auth_service) expected=0 ;;
    task_manager) expected=0 ;;
    ml_timeseries) expected=0 ;;
  esac
  mkdir -p "$output_dir/$spec"
  cp "$repo_root/examples/$spec.plain" "$output_dir/$spec/$spec.plain"
  set +e
  "$output_dir/venv/bin/plain2metta" --all "$output_dir/$spec/$spec.plain" \
    >"$output_dir/$spec/stdout.log" 2>"$output_dir/$spec/stderr.log"
  status=$?
  set -e
  if [[ "$status" -ne "$expected" ]]; then
    echo "$spec: expected exit $expected, got $status" >&2
    exit 1
  fi
  for extension in json metta diag; do
    test -s "$output_dir/$spec/$spec.$extension"
  done
  grep -q 'SpecAtom-HS Diagnostics Report' "$output_dir/$spec/$spec.diag"
done

"$output_dir/venv/bin/python" - <<'PY' "$output_dir"
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1])
summary = {}
for name in ("auth_service", "task_manager", "ml_timeseries"):
    spec = root / name / f"{name}.plain"
    data = json.loads(spec.with_suffix(".json").read_text(encoding="utf-8"))
    diag = spec.with_suffix(".diag").read_text(encoding="utf-8")
    summary[name] = {
        "source_sha256": hashlib.sha256(spec.read_bytes()).hexdigest(),
        "json_sha256": hashlib.sha256(spec.with_suffix(".json").read_bytes()).hexdigest(),
        "metta_sha256": hashlib.sha256(spec.with_suffix(".metta").read_bytes()).hexdigest(),
        "diagnostics_sha256": hashlib.sha256(diag.encode()).hexdigest(),
        "object_count": len(data["objects"]),
        "check_count": len(data["checks"]),
        "diagnostics_head": diag.splitlines()[:4],
    }
(root / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

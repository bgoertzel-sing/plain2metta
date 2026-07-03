"""Command-line interface for SpecAtom-HS scaffold outputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from specatom_hs.backends.diagnostics import format_diagnostics_report
from specatom_hs.backends.petta import emit_reified_atoms_grouped, refuse_executable_skeleton
from specatom_hs.passes import compile_path
from specatom_hs.schema import CheckStatus


def _json_ready(value):
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dict__"):
        return _json_ready(vars(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_json_ready(v) for v in value]
    if isinstance(value, list):
        return [_json_ready(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_ready(v) for k, v in value.items()}
    return value


def document_json(doc) -> str:
    payload = {
        "files": doc.files,
        "sections": doc.sections,
        "items": doc.items,
        "spans": doc.spans,
        "objects": doc.objects,
        "validation_obligations": doc.validation_obligations,
        "checks": doc.checks,
        "facts": doc.facts(),
    }
    return json.dumps(_json_ready(payload), indent=2, sort_keys=True) + "\n"


def metta_text(atoms: list[str], refusals: list[object]) -> str:
    lines = list(atoms)
    for refusal in refusals:
        lines.append("; backend-refusal " + json.dumps(_json_ready(refusal), sort_keys=True))
    return "\n".join(lines) + "\n"


def check_counts(doc) -> dict[str, int]:
    counts = {CheckStatus.PASS.value: 0, CheckStatus.FAIL.value: 0, CheckStatus.UNKNOWN.value: 0}
    for check in doc.checks:
        status = check.status.value if hasattr(check.status, "value") else str(check.status)
        counts[status] = counts.get(status, 0) + 1
    return counts


def diagnostics_text(doc, refusals: list[object]) -> str:
    counts = check_counts(doc)
    lines = [
        "SpecAtom-HS diagnostics",
        f"objects: {len(doc.objects)}",
        f"checks: Pass={counts.get('Pass', 0)} Fail={counts.get('Fail', 0)} Unknown={counts.get('Unknown', 0)}",
        f"refusals: {len(refusals)}",
    ]
    for check in doc.checks:
        status = check.status.value if hasattr(check.status, "value") else str(check.status)
        lines.append(f"- {status}: {check.property} target={check.target_id} evidence={check.evidence}")
    for refusal in refusals:
        lines.append(f"- Refusal: {refusal.reason} target={refusal.target} object={refusal.object_id}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile a .plain file to SpecAtom-HS JSON, MeTTa atoms, and diagnostics.")
    parser.add_argument("path", help="Input .plain file")
    parser.add_argument("--json", action="store_true", help="Write SpecAtom-HS JSON to stdout")
    parser.add_argument("--metta", action="store_true", help="Write .metta atoms to stdout")
    parser.add_argument("--diagnostics", action="store_true", help="Write diagnostics report to stdout")
    parser.add_argument("--all", action="store_true", help="Write .json, .metta, and .diag files alongside input")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    path = Path(args.path)
    write_all = args.all or not (args.json or args.metta or args.diagnostics)

    try:
        doc = compile_path(path)
    except Exception as exc:
        print(f"parse error: {exc}", file=sys.stderr)
        return 2

    atoms, reified_refusals = emit_reified_atoms_grouped(doc)
    refusals = reified_refusals + refuse_executable_skeleton(doc.objects)
    counts = check_counts(doc)

    json_output = document_json(doc)
    metta_output = metta_text(atoms, refusals)
    diag_output = format_diagnostics_report(doc) + "\n"

    if write_all:
        path.with_suffix(".json").write_text(json_output, encoding="utf-8")
        path.with_suffix(".metta").write_text(metta_output, encoding="utf-8")
        path.with_suffix(".diag").write_text(diag_output, encoding="utf-8")
    else:
        if args.json:
            sys.stdout.write(json_output)
        if args.metta:
            sys.stdout.write(metta_output)
        if args.diagnostics:
            sys.stdout.write(diag_output)

    print(
        f"{path.name}: objects={len(doc.objects)} checks Pass={counts.get('Pass', 0)} "
        f"Fail={counts.get('Fail', 0)} Unknown={counts.get('Unknown', 0)} refusals={len(refusals)}",
        file=sys.stderr,
    )
    return 1 if counts.get(CheckStatus.FAIL.value, 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())

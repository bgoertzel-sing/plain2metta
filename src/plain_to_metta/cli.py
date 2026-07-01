from __future__ import annotations

import argparse
import os
from pathlib import Path

from .compiler import compile_paths
from .emit import write_json, write_sexpr


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile Plain-like specs to a SpecAtom-HS MVP graph.")
    parser.add_argument("plain_files", nargs="+", help="Plain-like input files")
    parser.add_argument("--project-id", default="plain-metta-specatom")
    parser.add_argument("--out", default="out/specatom", help="Output path prefix or directory")
    args = parser.parse_args(argv)

    doc = compile_paths(args.plain_files, project_id=args.project_id)
    out = Path(args.out)
    if out.suffix:
        prefix = out.with_suffix("")
        out_dir = prefix.parent
    else:
        out_dir = out
        prefix = out / "specatom"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(doc, str(prefix) + ".json")
    write_sexpr(doc, str(prefix) + ".metta")
    print(f"wrote {str(prefix)}.json")
    print(f"wrote {str(prefix)}.metta")
    print(f"facts: {len(doc['facts'])}; objects: {len(doc['objects'])}; diagnostics: {len(doc['diagnostics'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

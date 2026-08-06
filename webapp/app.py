"""Plain2MeTTa Web — paste a Plain spec, see compilation results instantly."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

# Ensure the src directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from flask import Flask, render_template, request, jsonify

from specatom_hs.passes import compile_source
from specatom_hs.backends.petta import emit_reified_atoms_grouped, refuse_executable_skeleton
from specatom_hs.backends.diagnostics import format_diagnostics_report
from specatom_hs.cli import document_json, check_counts

app = Flask(__name__, template_folder="templates", static_folder="static")


def _compile(plain_text: str, filename: str = "input.plain"):
    """Compile plain text and return all output formats."""
    doc = compile_source(plain_text, filename)
    atoms, reified_refusals = emit_reified_atoms_grouped(doc)
    refusals = reified_refusals + refuse_executable_skeleton(doc.objects)
    counts = check_counts(doc)

    json_output = document_json(doc)
    metta_lines = list(atoms)
    for refusal in refusals:
        metta_lines.append("; backend-refusal " + json.dumps(
            {k: v.value if hasattr(v, "value") else v for k, v in vars(refusal).items()},
            sort_keys=True
        ))
    metta_output = "\n".join(metta_lines)
    diagnostics_output = format_diagnostics_report(doc)

    return {
        "json": json_output,
        "metta": metta_output,
        "diagnostics": diagnostics_output,
        "summary": {
            "objects": len(doc.objects),
            "pass": counts.get("Pass", 0),
            "fail": counts.get("Fail", 0),
            "unknown": counts.get("Unknown", 0),
            "refusals": len(refusals),
        },
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/docs")
def docs():
    return render_template("docs.html")


@app.route("/api/compile", methods=["POST"])
def api_compile():
    body = request.get_json(silent=True) or {}
    plain_text = body.get("text", "")
    if not plain_text.strip():
        return jsonify({"error": "Empty input — paste a Plain spec to compile."}), 400
    try:
        result = _compile(plain_text)
        return jsonify(result)
    except Exception as exc:
        return jsonify({
            "error": f"Compilation error: {exc}",
            "traceback": traceback.format_exc(),
        }), 422


@app.route("/api/examples")
def api_examples():
    """Return bundled example specs."""
    examples_dir = Path(__file__).resolve().parent.parent / "examples"
    examples = {}
    for f in sorted(examples_dir.glob("*.plain")):
        examples[f.stem] = f.read_text(encoding="utf-8")
    return jsonify(examples)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Plain2MeTTa Web App")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()
    print(f"🚀 Plain2MeTTa Web running at http://localhost:{args.port}")
    print(f"📖 Documentation at http://localhost:{args.port}/docs")
    app.run(host=args.host, port=args.port, debug=args.debug)

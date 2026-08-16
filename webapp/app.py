"""Private evaluation UI for the Plain2MeTTa v2 pipeline."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from flask import Flask, jsonify, render_template, request
from specatom_hs.evaluation import evaluate_plain

app = Flask(__name__)


@app.get("/api/health")
def health():
    """Cheap readiness probe that does not execute generated code."""
    return jsonify(
        status="ready",
        service="plain2metta-v2-evaluation",
        generator="deterministic-reference:v1",
        sandbox="bounded-local-python:v1",
    )


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/examples")
def examples():
    root = Path(__file__).resolve().parents[1] / "examples"
    return jsonify({path.stem: path.read_text(encoding="utf-8") for path in sorted(root.glob("*.plain"))})


@app.post("/api/evaluate")
def evaluate():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {"text"}:
        return jsonify(error="body must be exactly {text: string}"), 400
    try:
        return jsonify(evaluate_plain(body["text"]))
    except (TypeError, ValueError) as error:
        return jsonify(error=str(error)), 422


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=False)

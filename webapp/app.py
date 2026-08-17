"""Private evaluation UI for the Plain2MeTTa v2 pipeline."""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from flask import Flask, Response, jsonify, render_template, request
from specatom_hs.evaluation import evaluate_plain
from specatom_hs.evaluation_vertical import build_stage_1_through_8

app = Flask(__name__)
MAX_SPEC_BYTES = 128_000
# Bound the complete JSON request as well as the decoded specification below.
app.config["MAX_CONTENT_LENGTH"] = MAX_SPEC_BYTES + 4_096


def _semantic_api_response():
    """Delegate only configured semantic routes; production wiring stays injected."""
    semantic = app.config.get("SEMANTIC_VALIDATION_APPLICATION")
    if semantic is None:
        return jsonify(error="semantic validation API is not configured"), 503
    raw = request.get_data(cache=False)
    environ = dict(request.environ)
    environ["wsgi.input"] = io.BytesIO(raw)
    environ["CONTENT_LENGTH"] = str(len(raw))
    captured = {}
    chunks = semantic(environ, lambda status, headers: captured.update(status=status, headers=headers))
    return Response(b"".join(chunks), status=int(captured["status"].split()[0]), headers=dict(captured["headers"]))


@app.get("/api/health")
def health():
    """Cheap readiness probe that does not execute generated code."""
    return jsonify(
        status="ready",
        service="plain2metta-v2-evaluation",
        generator="deterministic-reference:v1",
        sandbox="bounded-local-dual-runtime:v1",
        metta_runtime="hyperon-cli:0.2.10",
    )


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/examples")
def examples():
    root = Path(__file__).resolve().parents[1] / "examples" / "evaluation"
    return jsonify({path.stem: path.read_text(encoding="utf-8") for path in sorted(root.glob("*.plain"))})


@app.post("/api/evaluate")
def evaluate():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {"text"}:
        return jsonify(error="body must be exactly {text: string}"), 400
    text = body["text"]
    if not isinstance(text, str):
        return jsonify(error="text must be a string"), 400
    if len(text.encode("utf-8")) > MAX_SPEC_BYTES:
        return jsonify(error="text exceeds the 128 KiB evaluation limit"), 413
    try:
        vertical = build_stage_1_through_8(text)
        payload = evaluate_plain(text)
        payload.update(vertical)
        return jsonify(payload)
    except (TypeError, ValueError) as error:
        return jsonify(error=str(error)), 422


@app.route("/api/validation-plan/<project_id>", methods=["GET", "POST"])
@app.post("/api/validation-plan-review/<project_id>")
@app.post("/api/semantic-test/<project_id>")
@app.get("/api/semantic-results/<project_id>")
@app.get("/api/semantic-trace/<project_id>")
def semantic_validation_api(project_id):
    return _semantic_api_response()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=False)

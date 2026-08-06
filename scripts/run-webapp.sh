#!/usr/bin/env bash
# Launch the Plain2MeTTa web app.
# Usage: bash scripts/run-webapp.sh [--port PORT]
set -euo pipefail
cd "$(dirname "$0")/.."

# Install flask if missing
python3 -c "import flask" 2>/dev/null || pip install flask

echo "Starting Plain2MeTTa Web..."
cd webapp
PYTHONPATH="../src:${PYTHONPATH:-}" python3 app.py "$@"

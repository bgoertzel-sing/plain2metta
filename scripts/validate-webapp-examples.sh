#!/usr/bin/env bash
# Validate the numbered web-playground examples and the provider-free suite.
set -euo pipefail
cd "$(dirname "$0")/.."

python_bin="${PYTHON_BIN:-.venv/bin/python}"
"$python_bin" -m unittest tests.test_webapp_examples -v
"$python_bin" -m unittest discover -s tests -v
git diff --check

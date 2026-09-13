#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.conda/bin/python -u -m finance_graph --config "${1:-config.json}" all
.conda/bin/python scripts/post_evaluation_audit.py "${1:-config.json}"

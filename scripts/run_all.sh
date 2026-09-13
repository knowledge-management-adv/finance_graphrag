#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec .conda/bin/python -u -m finance_graph --config "${1:-config.json}" all

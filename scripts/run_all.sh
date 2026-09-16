#!/usr/bin/env bash
set -euo pipefail
# Use Python from the activated API or local environment.
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
config_path="${1:-$repo_dir/config.json}"
python -u -m finance_graph --config "$config_path" all
python "$repo_dir/scripts/post_evaluation_audit.py" "$config_path"

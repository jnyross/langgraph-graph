#!/usr/bin/env bash
# Canonical mini-bench harness for meta_legal speed experiments.
# Quality gate: every cell must produce >=1 draft (enforced by mini_bench.py).
set -euo pipefail
cd "$(dirname "$0")"

export LANGSMITH_TRACING="${LANGSMITH_TRACING:-false}"
export LANGCHAIN_TRACING_V2="${LANGCHAIN_TRACING_V2:-false}"
export META_LEGAL_LLM_TIMEOUT_S="${META_LEGAL_LLM_TIMEOUT_S:-45}"

# Deterministic-ish: fixed pairs inside mini_bench.py; no live clock deps in metric.
exec uv run python scripts/mini_bench.py

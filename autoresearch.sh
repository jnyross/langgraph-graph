#!/usr/bin/env bash
# Full catalog×domain pipeline bench (1110 cells) with quality gates.
# Primary metric: wall_s (lower is better). Exit 2 on quality loss.
set -euo pipefail
cd "$(dirname "$0")"

export LANGSMITH_TRACING="${LANGSMITH_TRACING:-false}"
export LANGCHAIN_TRACING_V2="${LANGCHAIN_TRACING_V2:-false}"
export META_LEGAL_LLM_TIMEOUT_S="${META_LEGAL_LLM_TIMEOUT_S:-30}"
export META_LEGAL_MAX_CONCURRENCY="${META_LEGAL_MAX_CONCURRENCY:-100}"

exec uv run python scripts/full_pipeline_bench.py

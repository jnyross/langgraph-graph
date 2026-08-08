#!/usr/bin/env bash
# Start the minimal HITL UI (static page + /lg proxy to langgraph dev).
#
# Prerequisites:
#   uv run langgraph dev --no-browser   # API on http://127.0.0.1:2024
#
# Usage:
#   ./scripts/run_hitl_ui.sh
#   HITL_UI_PORT=3100 ./scripts/run_hitl_ui.sh
#   ./scripts/run_hitl_ui.sh --port 3100 --upstream http://127.0.0.1:2024

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"

cd "$ROOT"
echo "HITL UI → http://127.0.0.1:${HITL_UI_PORT:-3100}/?assistantId=hitl_demo"
echo "Expecting LangGraph API at ${HITL_UI_UPSTREAM:-http://127.0.0.1:2024}"
exec uv run python -m langgraph_graph.hitl_ui.server "$@"

#!/usr/bin/env bash
# Start the Agent Chat UI against the local LangGraph Agent Server.
#
# Prerequisites:
#   1. uv run langgraph dev --no-browser   # API on http://127.0.0.1:2024
#   2. Node 20+ and pnpm
#
# Usage:
#   ./scripts/run_agent_chat_ui.sh
#   ./scripts/run_agent_chat_ui.sh --install   # pnpm install first

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UI_DIR="$ROOT/apps/agent-chat-ui"

if [[ ! -d "$UI_DIR" ]]; then
  echo "Missing $UI_DIR — Agent Chat UI should live under apps/agent-chat-ui." >&2
  exit 1
fi

if [[ "${1:-}" == "--install" ]]; then
  (cd "$UI_DIR" && pnpm install)
fi

if [[ ! -f "$UI_DIR/.env" ]]; then
  cp "$UI_DIR/.env.example" "$UI_DIR/.env"
  echo "Created $UI_DIR/.env from .env.example"
fi

echo "Agent Chat UI → http://localhost:3000"
echo "Expecting LangGraph API at http://localhost:2024 (graph id: agent)"
cd "$UI_DIR"
exec pnpm dev

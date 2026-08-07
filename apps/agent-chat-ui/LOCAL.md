# Agent Chat UI (this repo)

Vendored from [langchain-ai/agent-chat-ui](https://github.com/langchain-ai/agent-chat-ui).
Use it as the human-in-the-loop surface for the **`agent`** graph.

## Run locally

Terminal 1 — LangGraph Agent Server:

```bash
uv sync --extra dev
uv run langgraph dev --no-browser
# API: http://127.0.0.1:2024
```

Terminal 2 — Agent Chat UI:

```bash
./scripts/run_agent_chat_ui.sh --install   # first time
./scripts/run_agent_chat_ui.sh
# UI: http://localhost:3000
```

Defaults (see `.env.example`):

| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:2024` |
| `NEXT_PUBLIC_ASSISTANT_ID` | `agent` |

No LangSmith API key is required for a local Agent Server.

## HITL contract

The `agent` graph interrupts with an Agent Inbox–compatible payload
(`action_requests` + `review_configs`). Agent Chat UI shows approve / edit /
reject controls and resumes with:

```json
{ "decisions": [{ "type": "approve" }] }
```

See `docs/hitl.md` and `src/langgraph_graph/hitl.py`.

## Hosted alternative

You can skip the local Next app and open
[agentchat.vercel.app](https://agentchat.vercel.app) with:

- Deployment URL: `http://localhost:2024`
- Graph / Assistant ID: `agent`

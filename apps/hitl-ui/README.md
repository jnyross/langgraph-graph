# HITL Control (minimal UI)

A zero-build frontend for LangGraph human-in-the-loop interrupts. Open it in a
Codex / local browser, start (or attach) a thread, and answer prompts:

- **confirm** — yes / no
- **choice** — pick one (or many) options
- **text** — free-text input
- **approve** — approve / edit / reject a proposed action  
  (also understands Agent Inbox `{action_requests, review_configs}` for graph id `agent`)

## Quick start

```bash
# Terminal 1 — Agent Server
uv run langgraph dev --no-browser --port 2024

# Terminal 2 — HITL UI (proxies /lg → :2024)
./scripts/run_hitl_ui.sh
```

Open:

```text
http://127.0.0.1:3100/?assistantId=hitl_demo
```

Click **Start run** and walk through the demo graph.

## Codex browser flow

1. Start `langgraph dev` and `./scripts/run_hitl_ui.sh` as above.
2. Open the UI URL in the Codex browser.
3. Either click **Start run**, or create a thread/run from chat and open:

```text
http://127.0.0.1:3100/?assistantId=hitl_demo&threadId=<THREAD_ID>
```

Attach uses `GET /threads/{id}/state` to surface a pending interrupt.

## Query params

| Param | Default | Meaning |
|-------|---------|---------|
| `assistantId` | `hitl_demo` | Graph / assistant id |
| `threadId` | _(empty)_ | Attach to an existing thread |
| `apiUrl` | `/lg` | API base (same-origin proxy by default) |

## CLI smoke (no UI)

```bash
uv run python examples/hitl_demo_smoke.py
```

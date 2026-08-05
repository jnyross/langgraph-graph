# Langgraph Graph — agent notes

## Context

This project implements the LangGraph-based recommendation from the
`Graph research` folder (`../Graph research/agentic-graphs-research.md`).
LangGraph is the **primary graph runtime** for personal task automation
with human-in-the-loop approvals, running on a MacBook Pro + Mac mini stack.

## Stack decisions (from research)

- **Runtime:** LangGraph (Python), official `interrupt()` HITL + checkpointer.
- **Models:** Ollama (or MLX) behind OpenAI-compatible endpoints; optional LiteLLM.
- **Typed tools:** Pydantic AI where validation > big graph.
- **No/low-code lane (separate):** self-hosted n8n for webhook glue automations.

## Conventions

- Python 3.12+. Manage deps with **uv** (`uv add`, `uv sync`). Do not commit `uv.lock`.
- Package import path is `langgraph_graph` (lives in `src/`).
- Keep graph definitions declarative; put side effects in tool functions, not nodes.
- Every node that performs an external action must be preceded by an `interrupt()`.
- Config via environment variables, never hardcoded secrets.

## HITL compliance minimum

A human approval interrupt is required before any of:
1. External send (message, email, webhook)
2. Spend (paid API call, purchase)
3. Production write
4. HR / PII export

## Running things

```bash
uv sync
uv run python examples/hitl_basic.py
uv run pytest            # once tests exist
```

## Layout quick ref

- `src/langgraph_graph/` — package: state schemas, graph builder, tools, HITL helpers
- `examples/` — runnable demos
- `scripts/` — ops helpers
- `docs/` — design notes, roadmap, decisions

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

## Preferred dev loop

Primary local path is **LangSmith Studio** via the LangGraph CLI:

```bash
uv sync --extra dev
cp .env.example .env   # optional LANGSMITH_API_KEY for traces; never commit .env
uv run langgraph dev
# API: http://127.0.0.1:2024
# Studio: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

- Graph ids in Studio / `langgraph.json`: **`agent`** (HITL) and **`meta_legal`** (no-HITL research)
- Safari / CORS issues: `uv run langgraph dev --tunnel`
- Script paths: `uv run python examples/hitl_basic.py` (HITL) · `uv run python examples/meta_legal_smoke.py` (no-HITL)

## Studio export contract

| Export | Where | Checkpointer |
|--------|--------|--------------|
| Module-level **`graph`** | `src/langgraph_graph/graph.py` (`agent`) | **None** — Agent Server injects one for Studio |
| Module-level **`graph`** | `src/langgraph_graph/meta_legal/graph.py` (`meta_legal`) | **None** — same Studio contract |
| **`build_graph()`** | same modules | **MemorySaver** (or optional checkpointer arg) for scripts/examples |

Do not attach a custom checkpointer to either Studio `graph` export.

`langgraph.json` points at:

```text
"agent": "./src/langgraph_graph/graph.py:graph"
"meta_legal": "./src/langgraph_graph/meta_legal/graph.py:graph"
```

### `meta_legal` (no HITL)

- **Do not** add `interrupt()` in `meta_legal` — research-only, fully automated.
- Starter domains only: `privacy`, `competition`, `youth_safety`, `ip`, `accessibility`.
- Input: `jurisdictions: list[str]`, `domains: list[str]`, `subject: str = "Meta"`.
- Cell id: `{jurisdiction_id}::{domain_id}`; dossiers under `data/dossiers/<run_id>/`.
- Models via **OpenRouter** (`langchain-openai`): set `OPENROUTER_API_KEY` in `.env`; default `OPENROUTER_MODEL=~deepseek/deepseek-v4-flash-latest` (rolling; currently → `deepseek/deepseek-v4-flash-0731`). Base URL default `https://openrouter.ai/api/v1`.

## Conventions

- Python 3.12+. Manage deps with **uv** (`uv add`, `uv sync`). Do not commit `uv.lock`.
- Package import path is `langgraph_graph` (lives in `src/`).
- Keep graph definitions declarative; put side effects in tool functions, not nodes.
- Every node that performs an external action in the **`agent`** graph must be preceded by an `interrupt()`.
- Config via environment variables, never hardcoded secrets. **Do not commit `.env`.**
- Keep the existing plan / act / reply nodes and HITL `interrupt()` design on **`agent`**. **`meta_legal` is the exception: no HITL.**

## Skills

After install, LangChain / LangGraph agent skills live under **`.agents/skills/`**
(or a similar project skills path). Prefer those skills for LangGraph CLI,
HITL, persistence, and LangSmith workflows.

## HITL compliance minimum

A human approval interrupt is required before any of:
1. External send (message, email, webhook)
2. Spend (paid API call, purchase)
3. Production write
4. HR / PII export

## Running things

```bash
uv sync --extra dev
uv run langgraph dev                          # preferred — Studio (select agent or meta_legal)
uv run python examples/hitl_basic.py          # CLI HITL demo
uv run python examples/meta_legal_smoke.py    # CLI meta_legal smoke (OpenRouter)
uv run pytest                                 # once tests exist
```

## Layout quick ref

- `langgraph.json` — Studio / `langgraph dev` entries (`graphs.agent`, `graphs.meta_legal`)
- `src/langgraph_graph/` — package: state schemas, graph builder, tools, HITL helpers
- `examples/` — runnable demos
- `scripts/` — ops helpers
- `docs/` — design notes, roadmap, decisions
- `.agents/skills/` — installed agent skills

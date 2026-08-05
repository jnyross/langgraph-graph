# Langgraph Graph

A personal-automation runtime for **AI agentic graphs** built on [LangGraph](https://github.com/langchain-ai/langgraph) (Python), with first-class **human-in-the-loop (HITL)** interrupts and **local-model** support. Designed to run on a MacBook Pro / Mac mini stack.

> This project follows the recommendation in `../Graph research/agentic-graphs-research.md`:
> LangGraph as the primary graph runtime, using official `interrupt()` HITL, with Ollama/MLX behind OpenAI-compatible endpoints.

## Goals

- Stateful, multi-step agent workflows as explicit graphs (nodes, edges, branching, resume).
- HITL checkpoints before any external side effect (send / spend / prod write / PII export).
- Local-first: Ollama / MLX models via OpenAI-compatible endpoints; optional LiteLLM for multi-provider.
- Reproducible runs via LangGraph checkpointer (SQLite now, Postgres later).
- Local development and debugging primarily through **LangSmith Studio** (`langgraph dev`).

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)**
- A free **[LangSmith](https://smith.langchain.com/)** account (optional; needed for traces and the hosted Studio UI)

## Quick start (LangSmith Studio)

```bash
uv sync --extra dev
cp .env.example .env   # add LANGSMITH_API_KEY if you want traces
uv run langgraph dev
```

Then open:

- **API:** http://127.0.0.1:2024
- **Studio:** https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024

The Studio graph id is **`agent`** (see `langgraph.json` → `graphs.agent`).

### Safari / cross-origin note

If the hosted Studio page cannot reach the local API (common in Safari), run with a tunnel:

```bash
uv run langgraph dev --tunnel
```

### Model env (defaults shown)

```bash
export MODEL="ollama/chatgpt-oss:latest"   # any OpenAI-compatible endpoint
export BASE_URL="http://localhost:11434/v1"
export API_KEY="ollama"                     # ignored by Ollama
```

Or set the same keys in `.env`.

## CLI / script example (HITL)

Without Studio, run the starter HITL example:

```bash
uv run python examples/hitl_basic.py
```

Scripts and examples use `build_graph()` (with an in-memory checkpointer). Studio uses the module-level `graph` export (no custom checkpointer — the Agent Server injects one).

## Meta legal research graph

Second Studio graph for multi-jurisdiction Meta legal research. Graph id: **`meta_legal`** (`langgraph.json` → `graphs.meta_legal`).

This graph is **no-HITL** — it does not call `interrupt()`. Runs write dossiers under `data/dossiers/<run_id>/`.

Models go through **OpenRouter** (`langchain-openai` / `ChatOpenAI`). Set `OPENROUTER_API_KEY` in `.env`. Default model is the rolling alias `~deepseek/deepseek-v4-flash-latest` (currently routes to `deepseek/deepseek-v4-flash-0731`); override with `OPENROUTER_MODEL`. Optional `TAVILY_API_KEY` if you switch search off DuckDuckGo. `DOSSIER_ROOT` defaults to `data/dossiers`.

Starter domains only: `privacy`, `competition`, `youth_safety`, `ip`, `accessibility`. Cell id format: `{jurisdiction_id}::{domain_id}`.

### Run in Studio

```bash
uv run langgraph dev
# select graph id: meta_legal
```

Sample Studio / API input:

```json
{
  "jurisdictions": ["EU", "US-CA", "UK"],
  "domains": ["privacy", "competition", "youth_safety", "ip", "accessibility"],
  "subject": "Meta"
}
```

### CLI smoke

```bash
uv run python examples/meta_legal_smoke.py
# optional overrides:
# uv run python examples/meta_legal_smoke.py --jurisdictions "European Union" "United States" --domains privacy
```

Live research workers need `OPENROUTER_API_KEY`; the planner + dossier path still run without it.

### Full grid (catalog)

Runs the operating jurisdiction catalog (`data/jurisdictions/meta_operating_catalog.json`) × starter domains:

```bash
# cell count only (no API calls)
uv run python examples/meta_legal_full_grid.py --dry-run

# subset for debugging
uv run python examples/meta_legal_full_grid.py --levels country,supranational --limit-jurisdictions 5

# full live run (expensive) — concurrency via META_LEGAL_MAX_CONCURRENCY (default 100)
uv run python examples/meta_legal_full_grid.py
```

Writes `data/dossiers/<run_id>/` plus `run_metrics.json` (elapsed_sec, cell_count, accepted/rejected counts).

### Eval (gold set recall)

```bash
# offline recall vs committed gold (not derived from data/dossiers/**)
uv run python -m evals.meta_legal.score_recall \
  --gold evals/meta_legal/gold_set.json \
  --dossier data/dossiers/<run_id>
# alias: uv run python -m evals.meta_legal --dossier data/dossiers/<run_id>
```

## Layout

```
langgraph.json         # LangGraph CLI / Studio config (graph id: agent)
.env.example           # copy to .env (never commit .env)
src/langgraph_graph/   # importable package: graph definition, state, tools, HITL
examples/              # runnable demos (start with hitl_basic.py)
scripts/               # ops helpers (seed checkpoints, list threads, etc.)
docs/                  # design notes and decisions
.agents/skills/        # LangChain / LangGraph agent skills (after install)
```

## HITL policy

No external side effect fires without a hard interrupt on first deploy. Approvals are granted per-thread, per-action, then can be relaxed after observation. See [docs/hitl.md](docs/hitl.md).

## Status

Scaffold. See [docs/roadmap.md](docs/roadmap.md).

# Langgraph Graph

A personal-automation runtime for **AI agentic graphs** built on [LangGraph](https://github.com/langchain-ai/langgraph) (Python), with first-class **human-in-the-loop (HITL)** interrupts and **local-model** support. Designed to run on a MacBook Pro / Mac mini stack.

> This project follows the recommendation in `../Graph research/agentic-graphs-research.md`:
> LangGraph as the primary graph runtime, using official `interrupt()` HITL, with Ollama/MLX behind OpenAI-compatible endpoints.

## Goals

- Stateful, multi-step agent workflows as explicit graphs (nodes, edges, branching, resume).
- HITL checkpoints before any external side effect (send / spend / prod write / PII export).
- Local-first: Ollama / MLX models via OpenAI-compatible endpoints; optional LiteLLM for multi-provider.
- Reproducible runs via LangGraph checkpointer (SQLite now, Postgres later).

## Quick start

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                      # create venv + install deps
uv run python examples/hitl_basic.py   # run the starter HITL graph
```

Set model config via env (defaults shown):

```bash
export MODEL="ollama/chatgpt-oss:latest"   # any OpenAI-compatible endpoint
export BASE_URL="http://localhost:11434/v1"
export API_KEY="ollama"                     # ignored by Ollama
```

## Layout

```
src/langgraph_graph/   # importable package: graph definition, state, tools, HITL
examples/              # runnable demos (start with hitl_basic.py)
scripts/               # ops helpers (seed checkpoints, list threads, etc.)
docs/                  # design notes and decisions
```

## HITL policy

No external side effect fires without a hard interrupt on first deploy. Approvals are granted per-thread, per-action, then can be relaxed after observation. See [docs/hitl.md](docs/hitl.md).

## Status

Scaffold. See [docs/roadmap.md](docs/roadmap.md).

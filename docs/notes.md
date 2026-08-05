# Design notes

## Why LangGraph

Follows the recommendation in `../../Graph research/agentic-graphs-research.md`.
LangGraph scored highest on graph/workflow model + native HITL interrupts in the
research rubric, and has the strongest production consensus for controllable
graphs on Reddit/Langfuse comparisons.

## Why interrupt(), not prompts

An interrupt is a durable, resumable pause persisted by the checkpointer. A
prompt-based "ask the model to wait" is not — it can hallucinate continuation.
For anything that touches money, external sends, or PII, only an interrupt counts.

## Local-first

Default endpoint is Ollama on `localhost:11434/v1`. MLX can drop in via its
OpenAI-compatible server. LiteLLM is optional for routing many providers.

## What this project is NOT

- Not a no-code flow builder — that lane is n8n, kept separate.
- Not a coding copilot IDE agent (Cline/OpenCode/Goose etc.) — different category.
- Not a knowledge-graph memory store (Graphiti) — noted in research, out of scope.

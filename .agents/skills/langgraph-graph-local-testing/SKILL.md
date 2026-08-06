---
name: langgraph-graph-local-testing
description: End-to-end smoke testing for the langgraph-graph repo, covering the LangGraph dev server, meta_legal graph, and static law-matrix web server.
---

# Local smoke testing for `langgraph-graph`

This repo uses `uv` for dependency management. The package lives in `src/langgraph_graph`.

## Devin Secrets Needed

- `OPENROUTER_API_KEY` — required for live `meta_legal` LLM research workers. Pass it as an environment variable; do not write the key into `.env`.

## One-time setup

```bash
cd /home/ubuntu/repos/langgraph-graph
uv python install 3.12
uv sync --extra dev
```

Create a non-secret `.env` (the real key is injected at runtime):

```bash
cat > .env <<'EOF'
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=~deepseek/deepseek-v4-flash-latest
BASE_URL=https://openrouter.ai/api/v1
MODEL=~deepseek/deepseek-v4-flash-latest
DOSSIER_ROOT=data/dossiers
EOF
```

Do not commit `.env` (it is gitignored).

## Smoke tests

### 1. `meta_legal` graph via the CLI example

```bash
OPENROUTER_API_KEY="${OPENROUTER_API_KEY}" \
OPENROUTER_MODEL=~deepseek/deepseek-v4-flash-latest \
  uv run python examples/meta_legal_smoke.py --jurisdictions "European Union" --domains privacy
```

Pass criteria:
- exit code 0
- `accepted >= 1`
- a dossier is written under `data/dossiers/<run_id>/`

If OpenRouter rejects the alias, fall back to `OPENROUTER_MODEL=deepseek/deepseek-v4-flash-0731`.

To verify the alias itself without a full graph run:

```bash
OPENROUTER_API_KEY="${OPENROUTER_API_KEY}" \
OPENROUTER_MODEL=~deepseek/deepseek-v4-flash-latest \
  uv run python - <<'PY'
from langgraph_graph.meta_legal.llm import get_llm
print(get_llm().invoke("Say ok").content)
PY
```

### 2. LangGraph dev server

```bash
uv run langgraph dev --no-browser --no-reload --port 2024
```

Check:

```bash
curl -s http://127.0.0.1:2024/ok        # expect 200 {"ok":true}
curl -s http://127.0.0.1:2024/docs      # API docs
```

Graphs are listed through `/assistants` (POST `/assistants/search`) and executed through `/runs`, not `/graphs`.

### 3. Static law-matrix web server

```bash
uv run python -m langgraph_graph.web.server --port 8765
```

Check:

```bash
curl -s http://127.0.0.1:8765/api/matrix
curl -s 'http://127.0.0.1:8765/api/laws?q=privacy'
```

Both should return `200` and valid JSON with `count`, `total`, `laws`, and `stats`.

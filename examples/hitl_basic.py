"""Run the starter HITL graph end-to-end in a single process.

Demonstrates the core loop:
  1. Start a thread.
  2. Hit the `interrupt()` in the `act` node.
  3. Resume with an approval decision.
  4. Print the final output.

This needs an OpenAI-compatible endpoint running (Ollama by default).
Set MODEL / BASE_URL / API_KEY in the environment or .env.
"""

from __future__ import annotations

import uuid

from langchain_core.messages import HumanMessage

from langgraph_graph import build_graph

# Load .env if present (optional; env vars also work without it).
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


def main() -> None:
    graph = build_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    request = "Remind me to review the agentic graphs research tomorrow."

    print("→ Starting run…")
    state = graph.invoke({"input": request, "messages": [HumanMessage(content=request)]}, config=config)

    # The graph paused at the interrupt. Inspect it.
    while state.get("pending_action") is None and "__interrupt__" in _next_interrupt(graph, config):
        print("\n⏸  Interrupted for approval. Inspecting action…")
        print("   ", graph.get_state(config))
        decision = _ask_human()
        print(f"→ Resuming with decision={decision}")
        state = graph.invoke(None, config=config)

    print("\n✅ Done. Final output:")
    print(state.get("output", "(empty)"))


def _next_interrupt(graph, config) -> tuple:
    try:
        return graph.get_state(config).next
    except Exception:
        return ()


def _ask_human() -> bool:
    answer = input("Approve action? [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


if __name__ == "__main__":
    main()

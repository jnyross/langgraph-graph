"""Run the starter HITL graph end-to-end in a single process.

Demonstrates the core loop:
  1. Start a thread.
  2. Hit the `interrupt()` in the `act` node.
  3. Resume with an Agent Chat UI–compatible decision payload.
  4. Print the final output.

This needs an OpenAI-compatible endpoint running (Ollama by default).
Set MODEL / BASE_URL / API_KEY in the environment or .env.
"""

from __future__ import annotations

import uuid

from langgraph.types import Command

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
    # Agent Chat UI / Agent Server expect OpenAI-style message dicts.
    state = graph.invoke(
        {"input": request, "messages": [{"role": "user", "content": request}]},
        config=config,
    )

    interrupts = state.get("__interrupt__") if isinstance(state, dict) else None
    if interrupts:
        print("\n⏸  Interrupted for approval.")
        print("   payload:", getattr(interrupts[0], "value", interrupts[0]))
        decision = _ask_human()
        print(f"→ Resuming with decision={decision}")
        state = graph.invoke(
            Command(resume={"decisions": [decision]}),
            config=config,
        )

    print("\n✅ Done. Final output:")
    if isinstance(state, dict):
        print(state.get("output", "(empty)"))
    else:
        print(state)


def _ask_human() -> dict:
    answer = input("Approve action? [y/N]: ").strip().lower()
    if answer in {"y", "yes"}:
        return {"type": "approve"}
    return {"type": "reject", "message": "Rejected from CLI demo."}


if __name__ == "__main__":
    main()

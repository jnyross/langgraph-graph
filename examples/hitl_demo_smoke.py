"""Drive hitl_demo through all four HITL prompts without a UI.

Usage::

    uv run python examples/hitl_demo_smoke.py
"""

from __future__ import annotations

import uuid

from langgraph.types import Command

from langgraph_graph.hitl_demo import build_graph


def main() -> None:
    graph = build_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    print("→ Starting hitl_demo…")
    state = graph.invoke({"input": "smoke"}, config=config)

    resumes = [
        {"kind": "confirm", "value": True},
        {"kind": "choice", "value": "eu"},
        {"kind": "text", "value": "youth safety"},
        {
            "kind": "approve",
            "decision": {"type": "approve"},
        },
    ]

    for resume in resumes:
        interrupts = state.get("__interrupt__") if isinstance(state, dict) else None
        if not interrupts:
            break
        value = getattr(interrupts[0], "value", interrupts[0])
        kind = value.get("kind") if isinstance(value, dict) else "?"
        print(f"⏸  interrupt kind={kind} → resume {resume}")
        state = graph.invoke(Command(resume=resume), config=config)

    print("\n✅ Done.")
    if isinstance(state, dict):
        print(state.get("output", "(empty)"))
        print("answers:", state.get("answers"))
    else:
        print(state)


if __name__ == "__main__":
    main()

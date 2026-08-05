#!/usr/bin/env python3
"""CLI runner for the Langgraph Graph HITL loop.

Usage:
    uv run python scripts/run.py "your request here"
    uv run python scripts/run.py --thread-id <id> "..."   # resume an existing thread
"""

from __future__ import annotations

import argparse
import uuid

from langchain_core.messages import HumanMessage

from langgraph_graph import build_graph


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Langgraph Graph HITL loop.")
    parser.add_argument("request", help="The user request.")
    parser.add_argument("--thread-id", default=None, help="Resume an existing thread.")
    parser.add_argument("--auto-approve", action="store_true", help="Auto-approve the interrupt (dev only).")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    graph = build_graph()
    thread_id = args.thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    print(f"thread_id = {thread_id}")

    state = graph.invoke(
        {"input": args.request, "messages": [HumanMessage(content=args.request)]},
        config=config,
    )

    # Resume past the interrupt with the chosen decision.
    decision = True if args.auto_approve else _ask_human()
    print(f"→ resuming with decision={decision}")
    state = graph.invoke(None, config=config)

    print("\n✅ Final output:")
    print(state.get("output", "(empty)"))


def _ask_human() -> bool:
    return input("Approve action? [y/N]: ").strip().lower() in {"y", "yes"}


if __name__ == "__main__":
    main()

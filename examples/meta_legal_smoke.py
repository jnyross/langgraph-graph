"""Smoke-run the meta_legal research graph (no HITL).

Tiny default grid: EU + US × privacy. Requires OPENROUTER_API_KEY for live
LLM research workers; planner + dossier writer still run without it (workers
may error or produce empty accepted/rejected).

Usage:
  uv run python examples/meta_legal_smoke.py
  uv run python examples/meta_legal_smoke.py \\
      --jurisdictions "European Union" "United States" --domains privacy
"""

from __future__ import annotations

import argparse
import os
import uuid

from langgraph_graph.meta_legal import build_graph

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


DEFAULT_JURISDICTIONS = ["European Union", "United States"]
DEFAULT_DOMAINS = ["privacy"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-run meta_legal (no HITL). OpenRouter key needed for live LLM."
    )
    parser.add_argument(
        "--jurisdictions",
        nargs="+",
        default=DEFAULT_JURISDICTIONS,
        help=f"Jurisdiction labels (default: {DEFAULT_JURISDICTIONS})",
    )
    parser.add_argument(
        "--domains",
        nargs="+",
        default=DEFAULT_DOMAINS,
        help=f"Starter domains (default: {DEFAULT_DOMAINS})",
    )
    parser.add_argument(
        "--subject",
        default="Meta",
        help='Research subject (default: "Meta")',
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if not os.getenv("OPENROUTER_API_KEY"):
        print(
            "Note: OPENROUTER_API_KEY is unset. Planner + dossier writer still run; "
            "research workers need OpenRouter (default ~deepseek/deepseek-v4-flash-latest)."
        )

    graph = build_graph()
    thread_id = str(uuid.uuid4())
    config = {
        "configurable": {"thread_id": thread_id},
        "max_concurrency": 4,
    }

    payload = {
        "jurisdictions": list(args.jurisdictions),
        "domains": list(args.domains),
        "subject": args.subject,
    }

    print("→ Starting meta_legal smoke run…")
    print(f"   jurisdictions={payload['jurisdictions']}")
    print(f"   domains={payload['domains']}")
    print(f"   subject={payload['subject']!r}")
    print(f"   thread_id={thread_id}")

    state = graph.invoke(payload, config=config)

    run_id = state.get("run_id") or "(none)"
    dossier_path = state.get("dossier_path") or "(none)"
    accepted = state.get("accepted") or []
    rejected = state.get("rejected") or []
    cell_errors = state.get("cell_errors") or []
    error = state.get("error")

    print("\nDone.")
    print(f"  run_id        = {run_id}")
    print(f"  dossier_path  = {dossier_path}")
    print(f"  accepted      = {len(accepted)}")
    print(f"  rejected      = {len(rejected)}")
    print(f"  cell_errors   = {len(cell_errors)}")
    if error:
        print(f"  error         = {error}")


if __name__ == "__main__":
    main()

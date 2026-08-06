"""Smoke-run the news_radar graph (no HITL).

Tiny default grid: EU × privacy, 14-day lookback. Requires network search and
an OpenRouter key for signal extraction.

Usage:
  uv run python examples/news_radar_smoke.py
  uv run python examples/news_radar_smoke.py \
      --jurisdictions "European Union" --domains privacy --lookback-days 14
"""

from __future__ import annotations

import argparse
import os
import uuid

from langgraph_graph.news_radar import build_graph

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


DEFAULT_JURISDICTIONS = ["European Union"]
DEFAULT_DOMAINS = ["privacy"]
DEFAULT_LOOKBACK_DAYS = 14


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-run news_radar (no HITL). OpenRouter + search keys needed for live scan."
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
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help=f"Recency window in days (default: {DEFAULT_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--include-rumors",
        action="store_true",
        help="Include unconfirmed rumors in signal extraction",
    )
    parser.add_argument(
        "--max-cells",
        type=int,
        default=None,
        help="Cap total number of jurisdiction×domain cells",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if not os.getenv("OPENROUTER_API_KEY"):
        print(
            "Note: OPENROUTER_API_KEY is unset. Graph skeleton will run, but "
            "signal extraction requires an LLM."
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
        "lookback_days": args.lookback_days,
        "include_rumors": args.include_rumors,
        "max_cells": args.max_cells,
    }

    print("→ Starting news_radar smoke run…")
    print(f"   jurisdictions={payload['jurisdictions']}")
    print(f"   domains={payload['domains']}")
    print(f"   subject={payload['subject']!r}")
    print(f"   lookback_days={payload['lookback_days']}")
    print(f"   thread_id={thread_id}")

    state = graph.invoke(payload, config=config)

    run_id = state.get("run_id") or "(none)"
    radar_path = state.get("radar_path") or "(none)"
    signals = state.get("signals") or []
    clusters = state.get("clusters") or []
    rejected = state.get("rejected") or []
    cell_errors = state.get("cell_errors") or []
    error = state.get("error")

    print("\nDone.")
    print(f"  run_id        = {run_id}")
    print(f"  radar_path    = {radar_path}")
    print(f"  signals       = {len(signals)}")
    print(f"  clusters      = {len(clusters)}")
    print(f"  rejected      = {len(rejected)}")
    print(f"  cell_errors   = {len(cell_errors)}")
    if error:
        print(f"  error         = {error}")


if __name__ == "__main__":
    main()

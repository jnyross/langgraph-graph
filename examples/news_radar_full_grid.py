"""Full-grid run of news_radar across all catalog jurisdictions × starter domains.

This starts a broad forward-signal sweep. It is intentionally expensive;
use ``--max-cells`` to cap the grid for a cheaper test.

Usage:
  uv run python examples/news_radar_full_grid.py
  uv run python examples/news_radar_full_grid.py --max-cells 50 --lookback-days 7
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path

from langgraph_graph.meta_legal.models import STARTER_DOMAINS
from langgraph_graph.news_radar import build_graph

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


CATALOG_PATH = Path("data/jurisdictions/meta_operating_catalog.json")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Full-grid news_radar run over the live jurisdiction catalog."
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=7,
        help="Recency window in days (default: 7)",
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
        help="Cap total number of cells (default: full grid)",
    )
    parser.add_argument(
        "--levels",
        nargs="+",
        default=["country", "supranational"],
        help='Catalog levels to include (default: "country supranational")',
    )
    return parser.parse_args()


def _load_jurisdiction_names(levels: list[str]) -> list[str]:
    if not CATALOG_PATH.exists():
        raise FileNotFoundError(f"Catalog not found: {CATALOG_PATH}")

    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    allowed = {str(level).lower().strip() for level in levels}
    names: list[str] = []
    for entry in catalog.get("jurisdictions", []):
        level = str(entry.get("level") or "").lower()
        if level in allowed:
            name = str(entry.get("name") or "").strip()
            if name:
                names.append(name)
    return sorted(names)


def main() -> None:
    args = _parse_args()

    if not os.getenv("OPENROUTER_API_KEY"):
        print(
            "Note: OPENROUTER_API_KEY is unset. Signal extraction will be skipped."
        )

    jurisdictions = _load_jurisdiction_names(args.levels)
    domains = list(STARTER_DOMAINS)

    print(f"→ Full-grid preparation: {len(jurisdictions)} jurisdictions × {len(domains)} domains")
    if args.max_cells:
        print(f"  capped to {args.max_cells} cells")

    graph = build_graph()
    thread_id = str(uuid.uuid4())
    config = {
        "configurable": {"thread_id": thread_id},
        "max_concurrency": 8,
    }

    payload = {
        "jurisdictions": jurisdictions,
        "domains": domains,
        "subject": "Meta",
        "lookback_days": args.lookback_days,
        "include_rumors": args.include_rumors,
        "max_cells": args.max_cells,
        "levels": args.levels,
    }

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

#!/usr/bin/env python3
"""Fixed mini bench for meta_legal cell throughput.

Prints:
  METRIC wall_s=<seconds>
  METRIC min_drafts=<n>
  METRIC total_drafts=<n>
  METRIC max_cell_s=<seconds>
  METRIC cells=<n>

Quality gate (exit 2 if failed): every cell produces >= 1 draft.
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("META_LEGAL_LLM_TIMEOUT_S", "45")

from langgraph_graph.meta_legal.nodes.plan_cells import expand_explicit_cells
from langgraph_graph.meta_legal.nodes.research_cell import run_research_cell
from langgraph_graph.meta_legal.tools.fetch import clear_fetch_cache
from langgraph_graph.meta_legal.tools.search import clear_search_cache, reset_search_breaker

PAIRS = [
    {"jurisdiction": "European Union", "domain": "privacy"},
    {"jurisdiction": "California", "domain": "privacy"},
    {"jurisdiction": "United Kingdom", "domain": "youth_safety"},
    {"jurisdiction": "Nigeria", "domain": "privacy"},
    {"jurisdiction": "Brazil", "domain": "competition"},
    {"jurisdiction": "Japan", "domain": "ip"},
    {"jurisdiction": "Mexico", "domain": "accessibility"},
    {"jurisdiction": "Austria", "domain": "privacy"},
]


def main() -> int:
    cells = expand_explicit_cells(PAIRS, subject="Meta")
    clear_fetch_cache()
    clear_search_cache()
    reset_search_breaker()

    def one(cell):
        t0 = time.perf_counter()
        out = run_research_cell(cell)
        return time.perf_counter() - t0, len(out.get("drafts") or [])

    t0 = time.perf_counter()
    times: list[float] = []
    drafts: list[int] = []
    with ThreadPoolExecutor(max_workers=len(cells)) as pool:
        futs = [pool.submit(one, c) for c in cells]
        for fut in as_completed(futs):
            dt, n = fut.result()
            times.append(dt)
            drafts.append(n)
    wall = time.perf_counter() - t0
    min_d = min(drafts) if drafts else 0
    total_d = sum(drafts)
    max_c = max(times) if times else 0.0

    print(f"METRIC wall_s={wall:.4f}")
    print(f"METRIC min_drafts={min_d}")
    print(f"METRIC total_drafts={total_d}")
    print(f"METRIC max_cell_s={max_c:.4f}")
    print(f"METRIC cells={len(cells)}")

    if min_d < 1:
        print("QUALITY_FAIL min_drafts < 1", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

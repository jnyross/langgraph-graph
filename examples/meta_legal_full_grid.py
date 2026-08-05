"""Full-grid meta_legal run from the jurisdiction operating catalog.

Loads all catalog jurisdictions (filterable by level) × starter domains,
optionally dry-runs the cell count, then invokes ``build_graph()``.

Usage:
  uv run python examples/meta_legal_full_grid.py --dry-run
  uv run python examples/meta_legal_full_grid.py --levels country,supranational
  uv run python examples/meta_legal_full_grid.py --limit-jurisdictions 3 --domains privacy

Env:
  META_LEGAL_MAX_CONCURRENCY  default 12
  OPENROUTER_API_KEY          required for live research workers
  DOSSIER_ROOT                default data/dossiers
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path

from langgraph_graph.meta_legal import STARTER_DOMAINS, build_graph
from langgraph_graph.meta_legal.jurisdictions import (
    VALID_LEVELS,
    catalog_product_size,
    list_jurisdiction_names,
    load_catalog,
)
from langgraph_graph.meta_legal.nodes.plan_cells import expand_cells
from langgraph_graph.meta_legal.run_config import (
    DEFAULT_STARTER_DOMAINS,
    max_concurrency,
    write_run_metrics,
)

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


def _parse_levels(raw: str | None) -> list[str] | None:
    """Parse comma-separated levels; None means all catalog levels."""
    if raw is None or not str(raw).strip():
        return None
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    if not parts:
        return None
    unknown = [p for p in parts if p not in VALID_LEVELS]
    if unknown:
        allowed = ", ".join(sorted(VALID_LEVELS))
        raise SystemExit(
            f"Unknown jurisdiction level(s): {', '.join(unknown)}. Allowed: {allowed}"
        )
    # preserve order, dedupe
    return list(dict.fromkeys(parts))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Full-grid meta_legal run from data/jurisdictions catalog "
            "(no HITL). OpenRouter key needed for live LLM research."
        )
    )
    parser.add_argument(
        "--levels",
        default=None,
        help=(
            "Comma-separated catalog levels to include "
            f"(default: all). Allowed: {','.join(sorted(VALID_LEVELS))}"
        ),
    )
    parser.add_argument(
        "--domains",
        nargs="+",
        default=list(DEFAULT_STARTER_DOMAINS),
        help=f"Domains (default: {' '.join(DEFAULT_STARTER_DOMAINS)})",
    )
    parser.add_argument(
        "--subject",
        default="Meta",
        help='Research subject (default: "Meta")',
    )
    parser.add_argument(
        "--limit-jurisdictions",
        type=int,
        default=None,
        metavar="N",
        help="Only use the first N catalog jurisdictions (debug)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned cell count and exit 0 without invoking the graph",
    )
    parser.add_argument(
        "--catalog",
        default=None,
        help="Optional path to jurisdiction catalog JSON (default: bundled)",
    )
    return parser.parse_args(argv)


def _select_jurisdictions(args: argparse.Namespace) -> list[str]:
    levels = _parse_levels(args.levels)
    catalog = load_catalog(args.catalog) if args.catalog else load_catalog()
    names = list_jurisdiction_names(catalog, levels=levels)
    if not names:
        raise SystemExit("No jurisdictions matched the catalog/level filter.")
    limit = args.limit_jurisdictions
    if limit is not None:
        if limit < 1:
            raise SystemExit("--limit-jurisdictions must be >= 1")
        names = names[:limit]
    return names


def _select_domains(raw: list[str]) -> list[str]:
    domains = [d.strip() for d in raw if d and str(d).strip()]
    if not domains:
        raise SystemExit("At least one domain is required.")
    # warn on non-starters but allow (graph accepts free-string extras)
    unknown = [d for d in domains if d not in STARTER_DOMAINS]
    if unknown:
        print(
            f"Note: non-starter domain(s) will still be sent: {', '.join(unknown)}",
            file=sys.stderr,
        )
    return list(dict.fromkeys(domains))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    jurisdictions = _select_jurisdictions(args)
    domains = _select_domains(list(args.domains))
    subject = (args.subject or "Meta").strip() or "Meta"

    cells = expand_cells(jurisdictions, domains, subject=subject)
    cell_count = len(cells)
    expected = catalog_product_size(
        domains,
        catalog=load_catalog(args.catalog) if args.catalog else load_catalog(),
        levels=_parse_levels(args.levels),
    )
    # When no jurisdiction limit, planned cells must match full product size.
    if args.limit_jurisdictions is None and cell_count != expected:
        raise SystemExit(
            f"catalog product mismatch: expand_cells={cell_count} expected={expected}"
        )

    print("meta_legal full grid")
    print(f"  jurisdictions = {len(jurisdictions)}")
    print(f"  domains       = {domains}")
    print(f"  subject       = {subject!r}")
    print(f"  cell_count    = {cell_count}")
    print(f"  catalog_product = {expected}")
    if args.limit_jurisdictions is not None:
        print(f"  limit_jurisdictions = {args.limit_jurisdictions}")
    if args.levels:
        print(f"  levels        = {args.levels}")

    if args.dry_run:
        print("dry-run: exiting without invoke")
        return 0

    if not os.getenv("OPENROUTER_API_KEY"):
        print(
            "Note: OPENROUTER_API_KEY is unset. Planner + dossier writer still run; "
            "research workers need OpenRouter.",
            file=sys.stderr,
        )

    concurrency = max_concurrency()
    graph = build_graph()
    thread_id = str(uuid.uuid4())
    config = {
        "configurable": {"thread_id": thread_id},
        "max_concurrency": concurrency,
    }
    payload = {
        "jurisdictions": jurisdictions,
        "domains": domains,
        "subject": subject,
    }

    print(f"  max_concurrency = {concurrency}")
    print(f"  thread_id       = {thread_id}")
    print("→ invoking build_graph()…")

    t0 = time.perf_counter()
    state = graph.invoke(payload, config=config)
    elapsed_sec = round(time.perf_counter() - t0, 3)

    run_id = state.get("run_id") or ""
    dossier_path = state.get("dossier_path") or ""
    accepted = state.get("accepted") or []
    rejected = state.get("rejected") or []
    cell_errors = state.get("cell_errors") or []
    error = state.get("error")
    # Prefer planner cells from result when present
    result_cells = state.get("cells") or cells
    result_cell_count = len(result_cells) if result_cells is not None else cell_count

    print("\nDone.")
    print(f"  run_id        = {run_id or '(none)'}")
    print(f"  dossier_path  = {dossier_path or '(none)'}")
    print(f"  accepted      = {len(accepted)}")
    print(f"  rejected      = {len(rejected)}")
    print(f"  cell_errors   = {len(cell_errors)}")
    print(f"  cell_count    = {result_cell_count}")
    print(f"  elapsed_sec   = {elapsed_sec}")
    if error:
        print(f"  error         = {error}")

    metrics = {
        "run_id": run_id or None,
        "dossier_path": dossier_path or None,
        "subject": subject,
        "jurisdictions_count": len(jurisdictions),
        "domains": domains,
        "cell_count": result_cell_count,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "cell_errors_count": len(cell_errors),
        "elapsed_sec": elapsed_sec,
        "max_concurrency": concurrency,
        "thread_id": thread_id,
        "error": error,
        "levels": args.levels,
        "limit_jurisdictions": args.limit_jurisdictions,
    }

    metrics_path: Path | None = None
    if dossier_path:
        metrics_path = write_run_metrics(dossier_path, metrics)
    elif run_id:
        root = os.getenv("DOSSIER_ROOT", "data/dossiers")
        metrics_path = write_run_metrics(Path(root) / run_id, metrics)
    else:
        # Last resort: write beside default dossier root under orphan/
        root = Path(os.getenv("DOSSIER_ROOT", "data/dossiers"))
        metrics_path = write_run_metrics(root / f"orphan-{thread_id}", metrics)

    print(f"  run_metrics   = {metrics_path}")
    return 0


if __name__ == "__main__":
    code = main()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)

"""Run meta_legal eval grid and score gold recall.

Cell sources:
  - gold (default): unique jurisdiction×domain pairs from gold_set.json
  - catalog: full cartesian product from meta_operating_catalog.json × domains

Never passes gold titles into the graph. Invokes once with ``explicit_cells``.

Usage:
  uv run python examples/meta_legal_eval_grid.py --dry-run
  uv run python examples/meta_legal_eval_grid.py --source catalog --dry-run
  uv run python examples/meta_legal_eval_grid.py --source catalog --limit-cells 20
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from langgraph_graph.meta_legal import build_graph
from langgraph_graph.meta_legal.jurisdictions import catalog_product_pairs, catalog_product_size
from langgraph_graph.meta_legal.run_config import DEFAULT_STARTER_DOMAINS, max_concurrency

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD = REPO_ROOT / "evals" / "meta_legal" / "gold_set.json"
DEFAULT_LOG = REPO_ROOT / "evals" / "meta_legal" / "experiments" / "log.jsonl"
EXP_ID = "exp_001"
EXP_NAME = "seed_expansion"


def _humanize_jurisdiction_id(jurisdiction_id: str) -> str:
    """Best-effort label when gold only has a slug id."""
    text = (jurisdiction_id or "").strip().replace("-", " ").replace("_", " ")
    return " ".join(part.capitalize() for part in text.split()) if text else ""


def load_explicit_cells_from_gold(gold_path: Path) -> list[dict[str, str]]:
    """Unique jurisdiction×domain pairs from gold (no titles).

    Prefers ``jurisdiction_name`` for graph input; falls back to humanized id.
    """
    raw = json.loads(gold_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"gold set must be a JSON list: {gold_path}")

    cells: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain_id") or item.get("domain") or "").strip()
        if not domain:
            continue
        name = str(item.get("jurisdiction_name") or "").strip()
        jid = str(item.get("jurisdiction_id") or "").strip()
        jurisdiction = name or _humanize_jurisdiction_id(jid) or jid
        if not jurisdiction:
            continue
        key = (jurisdiction.casefold(), domain.casefold())
        if key in seen:
            continue
        seen.add(key)
        cells.append({"jurisdiction": jurisdiction, "domain": domain})
    return cells


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Eval-grid meta_legal run (gold pairs or full catalog product) + recall score."
    )
    parser.add_argument(
        "--source",
        choices=("gold", "catalog"),
        default="gold",
        help="Cell source: gold_set pairs (default) or full catalog×domains product",
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=DEFAULT_GOLD,
        help=f"Path to gold_set.json for scoring and --source gold (default: {DEFAULT_GOLD})",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Optional catalog JSON path when --source catalog (default: bundled)",
    )
    parser.add_argument(
        "--domains",
        nargs="+",
        default=None,
        help=(
            "Domains for --source catalog "
            f"(default: {' '.join(DEFAULT_STARTER_DOMAINS)})"
        ),
    )
    parser.add_argument(
        "--levels",
        default=None,
        help="Comma-separated catalog levels for --source catalog (default: all)",
    )
    parser.add_argument(
        "--subject",
        default="Meta",
        help="Research subject label (default: Meta)",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG,
        help=f"JSONL experiment log path (default: {DEFAULT_LOG})",
    )
    parser.add_argument(
        "--exp-id",
        default=EXP_ID,
        help=f"Experiment id for log line (default: {EXP_ID})",
    )
    parser.add_argument(
        "--exp-name",
        default=EXP_NAME,
        help=f"Experiment name for log line (default: {EXP_NAME})",
    )
    parser.add_argument(
        "--notes",
        default="explicit_cells from gold pairs; seed expansion baseline path",
        help="Notes field written to log.jsonl",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print cell count / sample and exit without invoke",
    )
    parser.add_argument(
        "--skip-score",
        action="store_true",
        help="Invoke graph but skip score_recall",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=None,
        help="Override max_concurrency (default: run_config / env, usually 100)",
    )
    parser.add_argument(
        "--limit-cells",
        type=int,
        default=None,
        help="Only run the first N explicit cells (mini eval / smoke). Default: all.",
    )
    return parser.parse_args(argv)


def _parse_levels(raw: str | None) -> list[str] | None:
    if raw is None or not str(raw).strip():
        return None
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    return list(dict.fromkeys(parts)) or None


def load_explicit_cells(args: argparse.Namespace) -> list[dict[str, str]]:
    """Resolve explicit cells from --source gold|catalog."""
    if args.source == "catalog":
        domains = list(args.domains) if args.domains else list(DEFAULT_STARTER_DOMAINS)
        levels = _parse_levels(args.levels)
        path = args.catalog
        return catalog_product_pairs(domains, levels=levels, path=path)
    return load_explicit_cells_from_gold(args.gold)


def _append_log(log_path: Path, row: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def _score_dossier(gold_path: Path, dossier_path: str) -> dict[str, Any]:
    # Ensure repo root is importable when invoked as a script path.
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from evals.meta_legal.score_recall import score_recall, summarize

    result = score_recall(gold_path, Path(dossier_path))
    return summarize(result)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    gold_path: Path = args.gold
    if args.source == "gold" and not gold_path.is_file():
        print(f"error: gold set not found: {gold_path}", file=sys.stderr)
        return 2
    if args.source == "catalog" or not args.skip_score:
        # Scoring always needs gold when not skipped.
        if not args.skip_score and not gold_path.is_file():
            print(f"error: gold set not found for scoring: {gold_path}", file=sys.stderr)
            return 2

    expected_product: int | None = None
    if args.source == "catalog":
        domains = list(args.domains) if args.domains else list(DEFAULT_STARTER_DOMAINS)
        levels = _parse_levels(args.levels)
        expected_product = catalog_product_size(
            domains, levels=levels, path=args.catalog
        )

    explicit_cells = load_explicit_cells(args)
    if args.source == "catalog" and expected_product is not None:
        if len(explicit_cells) != expected_product:
            print(
                f"error: catalog product size mismatch: got {len(explicit_cells)} "
                f"expected {expected_product}",
                file=sys.stderr,
            )
            return 2

    if args.limit_cells is not None:
        limit = max(0, int(args.limit_cells))
        explicit_cells = explicit_cells[:limit]
    jurisdictions = list(dict.fromkeys(c["jurisdiction"] for c in explicit_cells))
    domains = list(dict.fromkeys(c["domain"] for c in explicit_cells))
    subject = (args.subject or "Meta").strip() or "Meta"
    concurrency = (
        max(1, int(args.max_concurrency))
        if args.max_concurrency is not None
        else max_concurrency()
    )

    print("meta_legal eval grid")
    print(f"  source          = {args.source}")
    print(f"  gold            = {gold_path}")
    if args.source == "catalog":
        print(f"  catalog_product = {expected_product}")
        if args.levels:
            print(f"  levels          = {args.levels}")
    print(f"  explicit_cells  = {len(explicit_cells)}")
    if args.limit_cells is not None:
        print(f"  limit_cells     = {int(args.limit_cells)}")
    print(f"  jurisdictions   = {len(jurisdictions)}")
    print(f"  domains         = {domains}")
    print(f"  subject         = {subject!r}")
    print(f"  max_concurrency = {concurrency}")
    if explicit_cells:
        print(f"  sample_cell     = {explicit_cells[0]}")
    if args.dry_run:
        print("dry-run: exiting without invoke")
        return 0

    if not os.getenv("OPENROUTER_API_KEY"):
        print(
            "Note: OPENROUTER_API_KEY is unset. Planner + dossier writer still run; "
            "research workers need OpenRouter.",
            file=sys.stderr,
        )

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
        "explicit_cells": explicit_cells,
    }

    print(f"  thread_id       = {thread_id}")
    print("→ invoking build_graph() with explicit_cells…")

    t0 = time.perf_counter()
    state = graph.invoke(payload, config=config)
    elapsed_sec = round(time.perf_counter() - t0, 3)

    run_id = state.get("run_id") or ""
    dossier_path = state.get("dossier_path") or ""
    accepted = state.get("accepted") or []
    rejected = state.get("rejected") or []
    cell_errors = state.get("cell_errors") or []
    error = state.get("error")
    result_cells = state.get("cells") or []
    result_cell_count = len(result_cells)

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

    recall = None
    found = None
    total = None
    score_error = None
    if args.skip_score:
        print("  score         = skipped")
    elif not dossier_path:
        score_error = "no dossier_path; cannot score"
        print(f"  score         = {score_error}", file=sys.stderr)
    else:
        try:
            summary = _score_dossier(gold_path, dossier_path)
            recall = float(summary["recall"])
            found = int(summary["found"])
            total = int(summary["total"])
            print(f"  recall        = {recall:.4f} ({found}/{total})")
        except Exception as exc:  # noqa: BLE001 — log and continue
            score_error = str(exc)
            print(f"  score_error   = {score_error}", file=sys.stderr)

    notes = args.notes
    if score_error:
        notes = f"{notes}; score_error={score_error}"
    if error:
        notes = f"{notes}; graph_error={error}"

    log_row = {
        "exp_id": args.exp_id,
        "name": args.exp_name,
        "recall": recall,
        "found": found,
        "total": total,
        "dossier": dossier_path or None,
        "elapsed_sec": elapsed_sec,
        "notes": notes,
    }
    _append_log(args.log, log_row)
    print(f"  log           = {args.log}")
    print(f"  log_row       = {json.dumps(log_row, sort_keys=True)}")

    return 0 if not error else 1


if __name__ == "__main__":
    code = main()
    # Daemon LLM/httpx threads can keep the interpreter alive after Done
    # (CLOSE_WAIT TLS reads). Force-exit so supervised evals actually finish.
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)

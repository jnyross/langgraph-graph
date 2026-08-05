"""CLI: score meta_legal dossier / prediction recall against the gold set."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from evals.meta_legal.match import load_gold_set, load_predictions, match_gold_to_predictions

DEFAULT_GOLD = Path(__file__).resolve().parent / "gold_set.json"
DEFAULT_THRESHOLD = 0.95


def summarize(result: Mapping[str, Any]) -> dict[str, Any]:
    """Compact JSON summary for stdout."""
    return {
        "total": int(result["total"]),
        "found": int(result["found"]),
        "missing": int(result["missing"]),
        "recall": float(result["recall"]),
        "missing_ids": list(result.get("missing_ids") or []),
    }


def score_recall(
    gold: Sequence[Mapping[str, Any]] | str | Path,
    predictions: Sequence[Mapping[str, Any]] | str | Path,
) -> dict[str, Any]:
    """Score gold vs predictions (paths or in-memory lists)."""
    gold_set = load_gold_set(gold) if isinstance(gold, (str, Path)) else [dict(g) for g in gold]
    preds = (
        load_predictions(predictions)
        if isinstance(predictions, (str, Path))
        else [dict(p) for p in predictions]
    )
    return match_gold_to_predictions(gold_set, preds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.meta_legal.score_recall",
        description="Score dossier/prediction recall against the independent meta_legal gold set.",
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=DEFAULT_GOLD,
        help=f"Path to gold_set.json (default: {DEFAULT_GOLD})",
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--dossier",
        type=Path,
        help="Path to a dossier directory (data/dossiers/<run_id>) with laws/ or index.json",
    )
    src.add_argument(
        "--predictions",
        type=Path,
        help="Path to a JSON list (or object with laws/predictions) of law records",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Minimum recall to exit 0 (default: {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include found/missing entry detail in JSON output",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    gold_path: Path = args.gold
    if not gold_path.is_file():
        print(json.dumps({"error": f"gold set not found: {gold_path}"}), file=sys.stderr)
        return 2

    pred_path: Path = args.dossier if args.dossier is not None else args.predictions
    if pred_path is None:
        parser.error("one of --dossier or --predictions is required")

    try:
        result = score_recall(gold_path, pred_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2

    payload = summarize(result)
    payload["threshold"] = float(args.threshold)
    payload["pass"] = payload["recall"] >= float(args.threshold)
    if args.verbose:
        payload["found_ids"] = list(result.get("found_ids") or [])
        payload["missing_entries"] = list(result.get("missing_entries") or [])

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

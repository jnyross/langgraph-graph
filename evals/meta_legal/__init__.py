"""Independent gold-set recall evaluation for meta_legal dossiers."""

from evals.meta_legal.match import (
    gold_found,
    load_gold_set,
    load_predictions,
    match_gold_to_predictions,
    normalize_citation,
    normalize_title_slug,
    significant_url_key,
)

__all__ = [
    "gold_found",
    "load_gold_set",
    "load_predictions",
    "match_gold_to_predictions",
    "normalize_citation",
    "normalize_title_slug",
    "score_recall",
    "significant_url_key",
    "summarize",
]


def __getattr__(name: str):
    if name in {"score_recall", "summarize"}:
        from evals.meta_legal import score_recall as _score_mod

        return getattr(_score_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

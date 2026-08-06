"""Compare signals against the meta_legal dossier to tag them new/update/duplicate."""

from __future__ import annotations

import re
from typing import Any, Literal, cast

from langgraph_graph.news_radar.models import SignalRecord
from langgraph_graph.news_radar.state import RadarState

_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "and",
        "for",
        "are",
        "with",
        "new",
        "law",
        "bill",
        "act",
        "regulation",
        "regulatory",
        "proposed",
        "amendment",
    }
)


def _title_tokens(title: str) -> set[str]:
    words = re.findall(r"\b[a-z]{3,}\b", str(title).lower())
    return {w for w in words if w not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _match_signal_to_law(
    signal: SignalRecord, known_laws: list[dict[str, Any]]
) -> tuple[Literal["new", "update_to_known_law", "duplicate_of_known_law"], str | None]:
    """Return (status, matched_law_id) for a signal."""
    sig_url = (signal.source_url or "").strip()
    sig_tokens = _title_tokens(signal.title)

    best_id: str | None = None
    best_score = 0.0

    for law in known_laws:
        if not law.get("title"):
            continue
        if law.get("jurisdiction_id") and law["jurisdiction_id"] != signal.jurisdiction_id:
            continue
        if law.get("domain_id") and law["domain_id"] != signal.domain_id:
            continue

        law_url = str(law.get("source_url") or "").strip()
        if sig_url and law_url and sig_url == law_url:
            return "duplicate_of_known_law", cast(str | None, law.get("law_id"))

        law_tokens = _title_tokens(law["title"])
        score = _jaccard(sig_tokens, law_tokens)
        if score > best_score:
            best_score = score
            best_id = cast(str | None, law.get("law_id"))

    if best_score >= 0.75:
        return "duplicate_of_known_law", best_id
    if best_score >= 0.45:
        return "update_to_known_law", best_id
    return "new", None


def link_known_laws(state: RadarState) -> dict:
    """Annotate each signal with its relationship to the known-law dossier."""
    signals: list[SignalRecord] = list(state.get("signals", []))
    known_laws = state.get("known_laws", [])

    for sig in signals:
        status, law_id = _match_signal_to_law(sig, known_laws)
        sig.known_law_status = status
        sig.known_law_match_id = law_id

    return {"signals": signals}

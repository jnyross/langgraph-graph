"""Cluster accepted signals that describe the same proposal or event."""

from __future__ import annotations

import re
from datetime import datetime

from langgraph_graph.news_radar.models import SignalCluster, SignalRecord
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
        "proposed",
        "regulation",
        "regulatory",
        "announces",
        "said",
    }
)


def _title_tokens(title: str) -> set[str]:
    words = re.findall(r"\b[a-z]{3,}\b", str(title).lower())
    return {w for w in words if w not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _date_or_none(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()[:10]
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return text
    except Exception:
        return None


def cluster_signals(state: RadarState) -> dict:
    """Group accepted signals by title/event similarity across publishers."""
    signals: list[SignalRecord] = list(state.get("accepted", []))
    include_rumors = state.get("include_rumors", False)
    threshold = 0.30 if include_rumors else 0.45

    clusters: list[SignalCluster] = []

    for sig in signals:
        tokens = _title_tokens(sig.title)
        best_match: SignalCluster | None = None
        best_score = 0.0
        for cluster in clusters:
            if sig.domain_id and sig.domain_id != cluster.domain_id:
                continue
            cluster_tokens = _title_tokens(cluster.title)
            score = _jaccard(tokens, cluster_tokens)
            if score >= threshold and score > best_score:
                best_match = cluster
                best_score = score

        if best_match is not None:
            best_match.signal_ids.append(sig.signal_id)
            best_match.signals.append(sig)
            # Update title to the longest representative.
            if len(sig.title) > len(best_match.title):
                best_match.title = sig.title
            best_match.publisher_names = list(
                {name for name in best_match.publisher_names if name} | {sig.source_name or ""}
            )
        else:
            clusters.append(
                SignalCluster(
                    title=sig.title,
                    event_type=sig.event_type,
                    domain_id=sig.domain_id,
                    signal_ids=[sig.signal_id],
                    signals=[sig],
                    publisher_names=[sig.source_name or ""],
                )
            )

    # Finalize each cluster.
    for cluster in clusters:
        cluster.publisher_names = sorted({n for n in cluster.publisher_names if n})
        cluster.distinct_publisher_count = len(cluster.publisher_names)

        dates = sorted({d for d in (_date_or_none(s.published_date) for s in cluster.signals) if d})
        cluster.earliest_date = dates[0] if dates else None
        cluster.latest_date = dates[-1] if dates else None

        any_rumor = any(s.is_rumor for s in cluster.signals)
        cluster.is_rumor_cluster = any_rumor or cluster.distinct_publisher_count <= 1

        if cluster.distinct_publisher_count == 0:
            cluster.status = "duplicate"
        elif cluster.is_rumor_cluster and not include_rumors:
            cluster.status = "rumor"
        elif cluster.distinct_publisher_count >= 3 and not any_rumor:
            cluster.status = "confirmed"
        else:
            cluster.status = "corroborated"

    return {"clusters": clusters, "signals": signals}

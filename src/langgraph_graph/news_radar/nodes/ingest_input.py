"""Validate news_radar invocation input and materialize the run ID."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from langgraph_graph.meta_legal.models import normalize_domain, normalize_jurisdiction
from langgraph_graph.news_radar.models import RadarInput
from langgraph_graph.news_radar.state import RadarState


def _default_run_id() -> str:
    """Radar run ID uses a timestamp tag plus a short UUID."""
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"radar_{ts}_{uuid4().hex[:8]}"


def ingest_input(state: RadarState) -> dict:
    """Normalize and validate incoming radar parameters."""
    try:
        sub: dict[str, Any] = {
            k: state[k]
            for k in (
                "jurisdictions",
                "domains",
                "subject",
                "lookback_days",
                "levels",
                "dossier_run_id",
                "max_cells",
                "include_rumors",
                "previous_run_id",
            )
            if k in state
        }
        raw = RadarInput(**sub)
    except Exception as exc:
        return {"error": f"Invalid radar input: {exc}"}

    run_id = state.get("run_id") or _default_run_id()
    return {
        "jurisdictions": [
            normalize_jurisdiction(j) for j in raw.jurisdictions if j.strip()
        ],
        "domains": [normalize_domain(d) for d in raw.domains if d.strip()],
        "subject": raw.subject.strip() or "Meta",
        "lookback_days": raw.lookback_days,
        "levels": raw.levels,
        "dossier_run_id": raw.dossier_run_id,
        "previous_run_id": raw.previous_run_id,
        "max_cells": raw.max_cells,
        "include_rumors": raw.include_rumors,
        "run_id": run_id,
        "error": None,
    }

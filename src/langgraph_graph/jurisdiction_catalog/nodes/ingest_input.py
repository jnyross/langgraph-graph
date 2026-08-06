"""Normalize jurisdiction catalog graph input."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ..state import CatalogState


def ingest_input(state: CatalogState) -> dict[str, Any]:
    """Normalize user input; invalid input is represented in state."""
    raw_levels = state.get("levels")
    levels = [str(x).strip() for x in (raw_levels or []) if str(x).strip()]
    raw_regions = state.get("regions")
    regions = [str(x).strip() for x in (raw_regions or []) if str(x).strip()]
    try:
        if raw_levels is not None and not isinstance(raw_levels, (list, tuple)):
            raise ValueError("levels must be a list")
        if any(not isinstance(x, str) for x in (raw_levels or [])):
            raise ValueError("levels must contain strings")
    except Exception as exc:
        return {
            "error": f"invalid input: {exc}",
            "levels": [],
            "regions": [],
            "run_id": state.get("run_id") or str(uuid4()),
        }
    return {
        "subject": str(state.get("subject") or "Meta").strip() or "Meta",
        "levels": levels,
        "regions": regions,
        "seed_path": str(state.get("seed_path") or ""),
        "discover_extra": bool(state.get("discover_extra", False)),
        "write_target": str(state.get("write_target") or "data/jurisdictions/runs"),
        "promote": bool(state.get("promote", False)),
        "run_id": str(state.get("run_id") or uuid4()),
        "error": None,
    }

"""Expand jurisdiction × domain inputs into a list of WatchCell units."""

from __future__ import annotations

from typing import Any

from langgraph_graph.meta_legal.models import (
    normalize_domain,
    normalize_jurisdiction,
    slugify,
)
from langgraph_graph.news_radar.models import WatchCell
from langgraph_graph.news_radar.state import RadarState


def _jurisdiction_level(jurisdiction_id: str, catalog: list[dict[str, Any]]) -> str:
    for j in catalog:
        if j.get("id") == jurisdiction_id:
            return str(j.get("level") or "").lower()
    return ""


def _filter_by_level(
    cells: list[WatchCell], levels: list[str], catalog: list[dict[str, Any]]
) -> list[WatchCell]:
    if not levels:
        return cells
    allowed = {str(level).lower().strip() for level in levels}
    out: list[WatchCell] = []
    for cell in cells:
        level = _jurisdiction_level(cell.jurisdiction_id, catalog)
        if level in allowed:
            out.append(cell)
    return out


def plan_cells(state: RadarState) -> dict:
    """Build the radar cell grid from inputs and optional catalog level filter."""
    raw_jurisdictions = state.get("jurisdictions", [])
    raw_domains = state.get("domains", [])
    subject = state.get("subject", "Meta")
    catalog = state.get("catalog_jurisdictions", [])
    max_cells = state.get("max_cells")

    # Normalize domains against the starter set and aliases; fall back to raw value.
    domains: list[tuple[str, str]] = []
    for d in raw_domains:
        label = d.strip()
        did = normalize_domain(label)
        if not did:
            did = slugify(label)
        # Use canonical alias text (lower-cased label without underscores) for display.
        display = " ".join(did.split("_"))
        domains.append((did, display))

    # Build cells by normalizing each jurisdiction.
    cells: list[WatchCell] = []
    for jurisdiction in raw_jurisdictions:
        jurisdiction = jurisdiction.strip()
        if not jurisdiction:
            continue
        normalized = normalize_jurisdiction(jurisdiction) or jurisdiction
        jurisdiction_id = slugify(normalized) or slugify(jurisdiction)
        level = _jurisdiction_level(jurisdiction_id, catalog)
        for domain_id, domain in domains:
            cell_id = f"{jurisdiction_id}::{domain_id}"
            cells.append(
                WatchCell(
                    cell_id=cell_id,
                    jurisdiction=normalized,
                    jurisdiction_id=jurisdiction_id,
                    domain=domain,
                    domain_id=domain_id,
                    subject=subject,
                    status="pending",
                    level=level or None,
                )
            )

    if catalog:
        cells = _filter_by_level(cells, state.get("levels", []), catalog)

    # Hard cap if requested (deterministic head of grid).
    if max_cells and max_cells > 0 and len(cells) > max_cells:
        cells = cells[:max_cells]

    # Deduplicate.
    seen: set[str] = set()
    unique: list[WatchCell] = []
    for c in cells:
        if c.cell_id in seen:
            continue
        seen.add(c.cell_id)
        unique.append(c)

    return {"cells": unique}

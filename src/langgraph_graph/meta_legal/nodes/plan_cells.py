"""Plan research cells: cartesian or explicit jurisdiction×domain pairs."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from langgraph_graph.meta_legal.models import (
    ResearchCell,
    make_cell_id,
    normalize_domain,
    normalize_jurisdiction,
    slugify,
)
from langgraph_graph.meta_legal.state import ResearchState


def expand_cells(
    jurisdictions: list[str],
    domains: list[str],
    subject: str = "Meta",
) -> list[ResearchCell]:
    """Pure cartesian expansion into stable ``ResearchCell`` objects.

    - Normalizes each jurisdiction label (aliases only; no member expansion).
    - Normalizes each domain (starter aliases: IP → ip, Youth Safety → youth_safety, …).
    - ``jurisdiction_id`` is ``slugify(normalized jurisdiction)``.
    - Duplicate jurisdiction×domain pairs collapse (first wins, order preserved).
    """
    subject_clean = (subject or "Meta").strip() or "Meta"
    cells: list[ResearchCell] = []
    seen: set[str] = set()

    for raw_jurisdiction in jurisdictions or []:
        if raw_jurisdiction is None or not str(raw_jurisdiction).strip():
            continue
        jurisdiction = normalize_jurisdiction(str(raw_jurisdiction))
        if not jurisdiction:
            continue
        j_id = slugify(jurisdiction)

        for raw_domain in domains or []:
            if raw_domain is None or not str(raw_domain).strip():
                continue
            d_id = normalize_domain(str(raw_domain))
            if not d_id:
                continue
            cell_id = make_cell_id(j_id, d_id)
            if cell_id in seen:
                continue
            seen.add(cell_id)
            cells.append(
                ResearchCell(
                    cell_id=cell_id,
                    jurisdiction=jurisdiction,
                    jurisdiction_id=j_id,
                    domain=d_id,
                    domain_id=d_id,
                    status="pending",
                    subject=subject_clean,
                )
            )

    return cells


def expand_explicit_cells(
    explicit_cells: Sequence[Mapping[str, Any]],
    subject: str = "Meta",
) -> list[ResearchCell]:
    """Expand only the given jurisdiction×domain pairs (no full cartesian).

    Each mapping should provide ``jurisdiction`` (or ``jurisdiction_name`` /
    ``jurisdiction_id``) and ``domain`` (or ``domain_id``). Labels are
    normalized the same way as :func:`expand_cells`. Duplicate pairs collapse.
    """
    subject_clean = (subject or "Meta").strip() or "Meta"
    cells: list[ResearchCell] = []
    seen: set[str] = set()

    for raw in explicit_cells or []:
        if not isinstance(raw, Mapping):
            continue
        raw_jurisdiction = (
            raw.get("jurisdiction")
            or raw.get("jurisdiction_name")
            or raw.get("jurisdiction_id")
            or ""
        )
        raw_domain = raw.get("domain") or raw.get("domain_id") or ""
        if raw_jurisdiction is None or not str(raw_jurisdiction).strip():
            continue
        if raw_domain is None or not str(raw_domain).strip():
            continue

        jurisdiction = normalize_jurisdiction(str(raw_jurisdiction))
        if not jurisdiction:
            continue
        # Prefer human labels; if caller only passed a slug id, title-case it.
        if jurisdiction == str(raw_jurisdiction).strip() and "_" in jurisdiction and jurisdiction == jurisdiction.lower():
            jurisdiction = jurisdiction.replace("_", " ").replace("-", " ").title()
            jurisdiction = normalize_jurisdiction(jurisdiction) or jurisdiction

        d_id = normalize_domain(str(raw_domain))
        if not d_id:
            continue
        j_id = slugify(jurisdiction)
        cell_id = make_cell_id(j_id, d_id)
        if cell_id in seen:
            continue
        seen.add(cell_id)
        cells.append(
            ResearchCell(
                cell_id=cell_id,
                jurisdiction=jurisdiction,
                jurisdiction_id=j_id,
                domain=d_id,
                domain_id=d_id,
                status="pending",
                subject=subject_clean,
            )
        )

    return cells


def plan_cells(state: ResearchState) -> dict[str, Any]:
    """Expand jurisdictions × domains, or only ``explicit_cells`` when set."""
    if state.get("error"):
        return {"cells": []}

    subject = state.get("subject") or "Meta"
    explicit = list(state.get("explicit_cells") or [])
    if explicit:
        cells = expand_explicit_cells(explicit, subject=subject)
    else:
        cells = expand_cells(
            jurisdictions=list(state.get("jurisdictions") or []),
            domains=list(state.get("domains") or []),
            subject=subject,
        )
    return {"cells": cells}


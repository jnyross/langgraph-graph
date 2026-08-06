"""Persist structurally valid discovered candidates into the research seed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langgraph_graph.jurisdiction_catalog.models import SUPPORTED_LEVELS, Candidate
from langgraph_graph.jurisdiction_catalog.state import CatalogState
from langgraph_graph.meta_legal.jurisdictions import default_catalog_path


def _default_seed_path() -> Path:
    """Return the repository's deterministic jurisdiction seed path."""
    return default_catalog_path().parent / "jurisdiction_catalog_seed.json"


def _structurally_valid(
    candidate: Candidate, known_ids: set[str], rejected: list[dict[str, Any]]
) -> bool:
    """Check static fields and parent resolution, not research verdicts."""
    if candidate.level not in SUPPORTED_LEVELS:
        return False
    if not candidate.id or not candidate.name:
        return False
    if candidate.parent_id and candidate.parent_id not in known_ids:
        return False
    reasons = {
        reason
        for item in rejected
        if item.get("candidate", {}).get("id") == candidate.id
        for reason in str(item.get("reason", "")).split(",")
    }
    return not reasons.intersection(
        {"unsupported_level", "missing_required_field", "unresolved_parent"}
    )


def widen_seed(state: CatalogState) -> dict[str, Any]:
    """Append discovered candidates without changing the live catalog."""
    discovered = state.get("discovered_candidates") or []
    if not state.get("auto_widen_seed", True) or not state.get("discovery_ran"):
        return {}
    if not discovered:
        return {}
    seed_path = Path(state.get("seed_path") or _default_seed_path())
    try:
        document = json.loads(seed_path.read_text(encoding="utf-8"))
        candidates = list(document.get("candidates", []))
        persisted = list(document.get("discovered_candidates", []))
        existing_ids = {item.get("id") for item in [*candidates, *persisted] if item.get("id")}
        known_ids = existing_ids | {candidate.id for candidate in state.get("candidates", [])}
        rejected = list(state.get("rejected") or [])
        additions = [
            candidate
            for candidate in discovered
            if candidate.id not in existing_ids
            and _structurally_valid(candidate, known_ids, rejected)
        ]
        additions.sort(key=lambda candidate: candidate.id)
        if not additions:
            return {}
        persisted.extend(candidate.model_dump() for candidate in additions)
        document["discovered_candidates"] = persisted
        seed_path.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        return {"errors": [f"seed widening failed: {exc}"]}
    return {}

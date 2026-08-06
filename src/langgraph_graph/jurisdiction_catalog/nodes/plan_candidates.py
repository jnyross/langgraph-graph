"""Plan deterministic jurisdiction candidates from seed and current catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langgraph_graph.meta_legal.jurisdictions import load_catalog
from langgraph_graph.meta_legal.models import slugify

from ..models import Candidate, candidate_id
from ..state import CatalogState

DEFAULT_SEED = (
    Path(__file__).resolve().parents[4] / "data/jurisdictions/jurisdiction_catalog_seed.json"
)


def _read(path: Path) -> list[dict[str, Any]]:
    """Read candidate entries from a seed document."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("candidates") or data.get("jurisdictions") or [])


def plan_candidates(state: CatalogState) -> dict[str, Any]:
    """Build a deterministic, deduplicated candidate universe."""
    if state.get("error"):
        return {"candidates": [], "error": state["error"]}
    path = Path(state.get("seed_path") or DEFAULT_SEED)
    try:
        entries = _read(path)
        current = load_catalog()
    except Exception as exc:
        return {
            "candidates": [],
            "error": f"candidate planning failed: {exc}",
            "errors": [str(exc)],
        }
    by_id: dict[str, Candidate] = {}
    wanted = set(state.get("levels") or [])
    regions = {slugify(x) for x in (state.get("regions") or [])}
    errors: list[str] = []
    for index, (raw, source) in enumerate(
        [(x, "seed") for x in entries]
        + [(x, "current_catalog") for x in current.get("jurisdictions", [])]
    ):
        try:
            name = str(raw["name"])
            level = str(raw["level"])
            parent = raw.get("parent_id")
            cid = str(raw.get("id") or candidate_id(name, level, parent))
            item = Candidate(
                id=cid,
                name=name,
                level=level,
                parent_id=parent,
                domains_priority=list(raw.get("domains_priority") or ["all"]),
                rationale=str(raw.get("rationale") or ""),
                source=source,
            )
        except Exception as exc:
            errors.append(f"skipped {source}[{index}]: {exc}")
            continue
        if wanted and level not in wanted:
            continue
        if regions and not ({slugify(item.name), slugify(item.parent_id or "")} & regions):
            continue
        prior = by_id.get(item.id)
        if prior is None or (prior.source == "current_catalog" and source == "seed"):
            by_id[item.id] = item
    return {"candidates": [by_id[k] for k in sorted(by_id)], "error": None, "errors": errors}

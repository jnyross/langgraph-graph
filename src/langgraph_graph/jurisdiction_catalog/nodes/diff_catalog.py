from __future__ import annotations

# ruff: noqa: E501
from typing import Any

from langgraph_graph.meta_legal.jurisdictions import load_catalog

from ..models import CatalogDiff


def compute_diff(accepted: list[dict[str, Any]], current: list[dict[str, Any]], excluded: list[dict[str, Any]] | None = None) -> CatalogDiff:
    old, new = {x["id"]: x for x in current}, {x["id"]: x for x in accepted}
    changed: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []
    keys = ("level", "parent_id", "name", "domains_priority")
    for cid in sorted(set(old) & set(new)):
        (unchanged if all(old[cid].get(k) == new[cid].get(k) for k in keys) else changed).append({"id": cid, "before": old[cid], "after": new[cid]})
    return CatalogDiff(
        added=[new[k] for k in sorted(set(new) - set(old))],
        removed=[old[k] for k in sorted(set(old) - set(new))],
        changed=changed, unchanged=unchanged, excluded=excluded or [],
    )


def diff_catalog(state: dict[str, Any]) -> dict[str, Any]:
    try:
        current = load_catalog().get("jurisdictions", [])
    except Exception:
        current = []
    accepted = [x.model_dump() if hasattr(x, "model_dump") else dict(x) for x in state.get("validated") or []]
    excluded = [x for x in state.get("rejected") or [] if x.get("reason") == "exclude"]
    return {"diff": compute_diff(accepted, current, excluded).model_dump()}

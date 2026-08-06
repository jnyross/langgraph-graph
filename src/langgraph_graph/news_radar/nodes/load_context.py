"""Load the jurisdiction catalog and the latest meta_legal dossier as context."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langgraph_graph.news_radar.state import RadarState

_CATALOG_PATH = Path("data/jurisdictions/meta_operating_catalog.json")
_DOSSIER_ROOT = Path("data/dossiers")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_dossier_index(dossier_run_id: str | None) -> dict[str, Any] | None:
    if dossier_run_id:
        path = _DOSSIER_ROOT / dossier_run_id / "index.json"
        data = _read_json(path)
        if data:
            return data

    # Find the most recently created index in the dossier root.
    candidates: list[tuple[float, Path, dict[str, Any]]] = []
    if _DOSSIER_ROOT.exists():
        for run_dir in _DOSSIER_ROOT.iterdir():
            if run_dir.is_dir():
                index = _read_json(run_dir / "index.json")
                if index:
                    try:
                        ts = index.get("created_at", "")
                        # Naive string sort is sufficient for ISO-8601.
                        order = 0.0 if not isinstance(ts, str) else sum(ord(c) for c in ts)
                        candidates.append((order, run_dir, index))
                    except Exception:
                        pass
    if candidates:
        # Sort descending by created_at string.
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][2]
    return None


def _catalog_jurisdictions(catalog: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not catalog:
        return []
    return [
        {
            "id": j.get("id", ""),
            "name": j.get("name", ""),
            "level": j.get("level", ""),
            "parent_id": j.get("parent_id"),
            "domains_priority": j.get("domains_priority", []),
        }
        for j in catalog.get("jurisdictions", [])
    ]


def _known_laws_from_index(index: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not index:
        return []
    known: list[dict[str, Any]] = []
    laws = index.get("laws", [])
    for law in laws:
        known.append(
            {
                "law_id": law.get("law_id") or law.get("id"),
                "title": law.get("title", ""),
                "jurisdiction_id": law.get("jurisdiction_id", ""),
                "domain_id": law.get("domain_id", ""),
                "cell_id": law.get("cell_id", ""),
                "status": law.get("status"),
                "source_url": law.get("source_url"),
            }
        )
    return known


def load_context(state: RadarState) -> dict:
    """Read the catalog and dossier; hydrate known_laws and catalog metadata."""
    catalog = _read_json(_CATALOG_PATH)
    catalog_version = (catalog or {}).get("version", "")
    catalog_jurisdictions = _catalog_jurisdictions(catalog)

    index = _load_dossier_index(state.get("dossier_run_id"))
    known_laws = _known_laws_from_index(index)

    return {
        "catalog_version": catalog_version,
        "catalog_jurisdictions": catalog_jurisdictions,
        "known_laws": known_laws,
    }

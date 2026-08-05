"""Jurisdiction operating catalog loader for Meta full-grid research runs.

Catalog file (repo data, not package data)::

    data/jurisdictions/meta_operating_catalog.json

Public API::

    default_catalog_path() -> Path
    load_catalog(path=None) -> dict
    list_jurisdiction_names(catalog=None, levels=None) -> list[str]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# repo root: src/langgraph_graph/meta_legal/jurisdictions.py → parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_RELATIVE = Path("data/jurisdictions/meta_operating_catalog.json")

VALID_LEVELS = frozenset({"supranational", "country", "us_state", "us_city"})


def default_catalog_path() -> Path:
    """Absolute path to the bundled Meta operating jurisdiction catalog."""
    return _REPO_ROOT / _DEFAULT_RELATIVE


def load_catalog(path: str | Path | None = None) -> dict[str, Any]:
    """Load and lightly validate the jurisdiction catalog JSON.

    Parameters
    ----------
    path:
        Optional override. When omitted, uses :func:`default_catalog_path`.

    Returns
    -------
    dict
        Catalog document with at least ``version``, ``subject``, and
        ``jurisdictions`` (list of entry dicts).

    Raises
    ------
    FileNotFoundError
        If the catalog file is missing.
    ValueError
        If the JSON shape is invalid (missing keys, bad entries, duplicate ids).
    """
    catalog_path = Path(path) if path is not None else default_catalog_path()
    raw = catalog_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"catalog root must be an object: {catalog_path}")

    jurisdictions = data.get("jurisdictions")
    if not isinstance(jurisdictions, list):
        raise ValueError(f"catalog.jurisdictions must be a list: {catalog_path}")

    seen: set[str] = set()
    for i, item in enumerate(jurisdictions):
        if not isinstance(item, Mapping):
            raise ValueError(f"jurisdictions[{i}] must be an object")
        jid = item.get("id")
        name = item.get("name")
        level = item.get("level")
        if not isinstance(jid, str) or not jid.strip():
            raise ValueError(f"jurisdictions[{i}].id must be a non-empty string")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"jurisdictions[{i}].name must be a non-empty string")
        if not isinstance(level, str) or not level.strip():
            raise ValueError(f"jurisdictions[{i}].level must be a non-empty string")
        if jid in seen:
            raise ValueError(f"duplicate jurisdiction id: {jid!r}")
        seen.add(jid)

    if "version" not in data:
        raise ValueError("catalog.version is required")
    if "subject" not in data:
        raise ValueError("catalog.subject is required")

    return data


def list_jurisdiction_names(
    catalog: Mapping[str, Any] | None = None,
    levels: Sequence[str] | Iterable[str] | None = None,
) -> list[str]:
    """Return display names from the catalog, optionally filtered by level.

    Parameters
    ----------
    catalog:
        Pre-loaded catalog dict. When ``None``, loads via :func:`load_catalog`.
    levels:
        Optional iterable of level strings (e.g. ``\"country\"``,
        ``\"supranational\"``). ``None`` returns all entries in catalog order.

    Returns
    -------
    list[str]
        Jurisdiction ``name`` values in catalog order.
    """
    doc = catalog if catalog is not None else load_catalog()
    items = doc.get("jurisdictions") or []
    if not isinstance(items, list):
        return []

    allowed: set[str] | None = None
    if levels is not None:
        allowed = {str(level).strip() for level in levels if str(level).strip()}
        if not allowed:
            return []

    names: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if allowed is not None and str(item.get("level") or "") not in allowed:
            continue
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names

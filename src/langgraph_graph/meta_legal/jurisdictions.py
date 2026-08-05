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
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

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


def catalog_jurisdiction_count(
    catalog: Mapping[str, Any] | None = None,
    levels: Sequence[str] | Iterable[str] | None = None,
) -> int:
    """Number of catalog jurisdictions (optionally filtered by level)."""
    return len(list_jurisdiction_names(catalog=catalog, levels=levels))


def catalog_product_pairs(
    domains: Sequence[str] | None = None,
    *,
    catalog: Mapping[str, Any] | None = None,
    levels: Sequence[str] | Iterable[str] | None = None,
    path: str | Path | None = None,
) -> list[dict[str, str]]:
    """Full cartesian product: catalog jurisdictions × domains.

    Returns ``[{"jurisdiction": name, "domain": domain_id}, ...]`` in catalog
    order × domain order. Domain strings are passed through as given (callers
    typically use starter domain slugs). Empty jurisdiction names are skipped.
    """
    doc = catalog if catalog is not None else load_catalog(path)
    names = list_jurisdiction_names(doc, levels=levels)
    if domains is None:
        from langgraph_graph.meta_legal.run_config import DEFAULT_STARTER_DOMAINS

        domain_list = list(DEFAULT_STARTER_DOMAINS)
    else:
        domain_list = [str(d).strip() for d in domains if str(d).strip()]

    pairs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for name in names:
        for domain in domain_list:
            key = (name.casefold(), domain.casefold())
            if key in seen:
                continue
            seen.add(key)
            pairs.append({"jurisdiction": name, "domain": domain})
    return pairs


def catalog_product_size(
    domains: Sequence[str] | None = None,
    *,
    catalog: Mapping[str, Any] | None = None,
    levels: Sequence[str] | Iterable[str] | None = None,
    path: str | Path | None = None,
) -> int:
    """``|J| × |D|`` for the catalog product (after empty-name filtering)."""
    return len(
        catalog_product_pairs(
            domains,
            catalog=catalog,
            levels=levels,
            path=path,
        )
    )

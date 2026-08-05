"""Data aggregation layer for the law-matrix website.

Reads filesystem dossiers under ``data/dossiers/<run_id>/`` and produces a
matrix-friendly aggregate for the static frontend.

Dossier layout (from :mod:`langgraph_graph.meta_legal.nodes.write_dossier`)::

    data/dossiers/<run_id>/
        manifest.json                 # DossierManifest
        index.json                    # summary + law_ids + per-law paths
        laws/<safe_law_id>.json       # one LawRecord per file
        cells/<safe_cell_id>/findings.json  # {cell_id, count, findings: [LawRecord]}
        rejected/<bucket>.json        # validation rejections (ignored here)

The aggregator tolerates missing / partial dossiers and deduplicates by
``law_id`` so the same run written twice does not double-count.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_DOSSIER_ROOT = "data/dossiers"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _dossier_root(explicit: str | Path | None = None) -> Path:
    """Resolve the dossier root.

    Priority: explicit arg > ``DOSSIER_ROOT`` env > ``data/dossiers``.
    Always returns a :class:`Path` (may not exist).
    """
    if explicit is not None:
        return Path(explicit)
    return Path(os.environ.get("DOSSIER_ROOT", DEFAULT_DOSSIER_ROOT))


def _safe_load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _humanize_slug(slug: str) -> str:
    """Best-effort display label from a slug: ``european_union`` -> ``European Union``."""
    if not slug:
        return slug
    return slug.replace("_", " ").replace("-", " ").title()


# ---------------------------------------------------------------------------
# public: discover_runs / load_manifest
# ---------------------------------------------------------------------------


def discover_runs(dossier_root: str | Path | None = None) -> list[str]:
    """List run_ids that contain a ``manifest.json`` under *dossier_root*.

    Returns a sorted list. If the root does not exist or contains no
    manifests, returns ``[]`` (graceful empty handling).
    """
    root = _dossier_root(dossier_root)
    if not root.is_dir():
        return []
    runs: list[str] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        manifest = entry / "manifest.json"
        if manifest.is_file():
            runs.append(entry.name)
    runs.sort()
    return runs


def load_manifest(
    run_id: str,
    dossier_root: str | Path | None = None,
) -> dict[str, Any] | None:
    """Load ``manifest.json`` for *run_id*.

    Returns the parsed dict on success, ``None`` if the file is missing or
    unreadable.
    """
    if not run_id or not str(run_id).strip():
        return None
    root = _dossier_root(dossier_root)
    path = root / str(run_id).strip() / "manifest.json"
    data = _safe_load_json(path)
    if not isinstance(data, dict):
        return None
    return data


# ---------------------------------------------------------------------------
# internal: per-run law collection
# ---------------------------------------------------------------------------


def _laws_from_laws_dir(run_dir: Path) -> list[dict[str, Any]]:
    """Read ``laws/*.json`` inside *run_dir*."""
    laws_dir = run_dir / "laws"
    if not laws_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for p in laws_dir.glob("*.json"):
        data = _safe_load_json(p)
        if isinstance(data, dict) and data.get("law_id"):
            records.append(data)
        elif isinstance(data, dict) and data.get("title"):
            # Some writers may omit law_id but still valid
            records.append(data)
    return records


def _laws_from_cells(run_dir: Path) -> list[dict[str, Any]]:
    """Read ``cells/*/findings.json`` inside *run_dir*."""
    cells_dir = run_dir / "cells"
    if not cells_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for findings_path in cells_dir.glob("*/findings.json"):
        data = _safe_load_json(findings_path)
        if not isinstance(data, dict):
            continue
        findings = data.get("findings")
        if isinstance(findings, list):
            for item in findings:
                if isinstance(item, dict):
                    records.append(item)
    # Also handle flat glob in case of unexpected layout
    for findings_path in cells_dir.glob("findings.json"):
        data = _safe_load_json(findings_path)
        if isinstance(data, dict) and isinstance(data.get("findings"), list):
            for item in data["findings"]:
                if isinstance(item, dict):
                    records.append(item)
    return records


def _laws_from_index(run_dir: Path) -> list[dict[str, Any]]:
    """Fallback: try to resolve laws via ``index.json`` entries."""
    index_path = run_dir / "index.json"
    data = _safe_load_json(index_path)
    if not isinstance(data, dict):
        return []
    records: list[dict[str, Any]] = []
    # index may embed full law objects in some future shape
    for key in ("findings", "laws"):
        val = data.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and item.get("law_id"):
                    # If item only has path, try to load that file
                    if len(item) <= 3 and item.get("path"):
                        law_path = run_dir / item["path"]
                        loaded = _safe_load_json(law_path)
                        if isinstance(loaded, dict):
                            records.append(loaded)
                            continue
                    # Otherwise treat as inline record if it has title/jurisdiction
                    if item.get("title") or item.get("jurisdiction_id"):
                        # inline already complete enough
                        if item.get("title"):
                            records.append(item)
                        continue
                    # path-only entry fallback already attempted above
                    continue
    return records


def _collect_laws_for_run(run_dir: Path) -> list[dict[str, Any]]:
    """Collect laws for a single run, deduplicated by ``law_id``.

    Tries ``laws/*.json`` first, then ``cells/*/findings.json``, then
    ``index.json`` as fallback. Within a run, records are deduplicated by
    ``law_id`` (first occurrence wins).
    """
    seen: dict[str, dict[str, Any]] = {}

    def _add_batch(batch: list[dict[str, Any]]) -> None:
        for rec in batch:
            lid = str(rec.get("law_id") or "").strip()
            if not lid:
                # synthesize a key so we still count it
                lid = f"__nolawid__{rec.get('title','')[:40]}"
                # Use title as fallback dedup; skip if truly empty
                if lid == "__nolawid__":
                    continue
            if lid not in seen:
                seen[lid] = rec

    # Primary source
    _add_batch(_laws_from_laws_dir(run_dir))
    # Findings as secondary (may overlap)
    _add_batch(_laws_from_cells(run_dir))
    # Fallback only if still empty
    if not seen:
        _add_batch(_laws_from_index(run_dir))

    return list(seen.values())


# ---------------------------------------------------------------------------
# public: matrix building
# ---------------------------------------------------------------------------


def _enrich_law(record: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Return a shallow copy with guaranteed keys for downstream use."""
    out = dict(record)
    # Ensure core identifiers exist
    jid = str(out.get("jurisdiction_id") or out.get("jurisdiction") or "").strip()
    did = str(out.get("domain_id") or out.get("domain") or "").strip()
    cid = str(out.get("cell_id") or "").strip()
    if not cid and jid and did:
        cid = f"{jid}::{did}"
        out["cell_id"] = cid
    # Attach provenance if not present
    if "run_id" not in out:
        out["run_id"] = run_id
    # Ensure strings for template safety
    out.setdefault("title", "")
    out.setdefault("jurisdiction_id", jid)
    out.setdefault("domain_id", did)
    out.setdefault("cell_id", cid)
    return out


def build_matrix(
    laws: list[dict[str, Any]],
    runs: list[str],
    *,
    extra_jurisdictions: list[str] | None = None,
    extra_domains: list[str] | None = None,
) -> dict[str, Any]:
    """Build the canonical matrix structure from a flat law list.

    Parameters
    ----------
    laws:
        Enriched law dicts (each with ``jurisdiction_id``, ``domain_id``,
        ``cell_id``).
    runs:
        Sorted run_ids contributing to *laws*.
    extra_jurisdictions / extra_domains:
        Optional jurisdiction/domain ids from manifests to include even when
        no laws exist for that pair (improves coverage calculation for empty
        grids).

    Returns
    -------
    dict with keys ``domains``, ``jurisdictions``, ``cells``, ``laws``,
    ``runs``, ``stats``.  ``cells`` is keyed by ``cell_id``
    (``{jurisdiction_id}::{domain_id}``) and each value is::

        {jurisdiction, jurisdiction_id, domain, domain_id, count, laws}

    ``stats`` is ``{total_laws, total_cells, populated_cells, coverage}``
    where ``coverage`` is ``populated / total_possible`` (0 when empty).
    """
    jurisdictions_set: set[str] = set(extra_jurisdictions or [])
    domains_set: set[str] = set(extra_domains or [])
    for law in laws:
        jid = str(law.get("jurisdiction_id") or "").strip()
        did = str(law.get("domain_id") or "").strip()
        if jid:
            jurisdictions_set.add(jid)
        if did:
            domains_set.add(did)

    # Group by cell
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for law in laws:
        cid = str(law.get("cell_id") or "").strip()
        if not cid:
            jid = str(law.get("jurisdiction_id") or "").strip()
            did = str(law.get("domain_id") or "").strip()
            if jid and did:
                cid = f"{jid}::{did}"
            else:
                cid = "unknown::unknown"
        grouped[cid].append(law)

    jurisdictions = sorted(jurisdictions_set)
    domains = sorted(domains_set)

    cells: dict[str, dict[str, Any]] = {}
    for cid, cell_laws in grouped.items():
        # Derive ids from cell_id when possible
        if "::" in cid:
            jid_part, did_part = cid.split("::", 1)
        else:
            # fallback: use first law's ids
            jid_part = str(cell_laws[0].get("jurisdiction_id") or "").strip()
            did_part = str(cell_laws[0].get("domain_id") or "").strip()
        cells[cid] = {
            "jurisdiction": _humanize_slug(jid_part),
            "jurisdiction_id": jid_part,
            "domain": did_part,
            "domain_id": did_part,
            "count": len(cell_laws),
            "laws": sorted(cell_laws, key=lambda r: str(r.get("title") or r.get("law_id") or "")),
        }

    # Ensure every declared jurisdiction × domain has a cell entry (even if count 0)
    # so the frontend can render empty cells. Only when both lists are non-empty.
    if jurisdictions and domains:
        for jid in jurisdictions:
            for did in domains:
                cid = f"{jid}::{did}"
                if cid not in cells:
                    cells[cid] = {
                        "jurisdiction": _humanize_slug(jid),
                        "jurisdiction_id": jid,
                        "domain": did,
                        "domain_id": did,
                        "count": 0,
                        "laws": [],
                    }

    total_laws = len(laws)
    populated_cells = sum(1 for v in cells.values() if v["count"] > 0)
    total_cells = len(cells)
    # Coverage: fraction of possible j × d pairs that have at least one law.
    # When the grid was expanded to all combos, total_cells == possible.
    # Otherwise compute from declared sets.
    if jurisdictions and domains:
        possible = len(jurisdictions) * len(domains)
        coverage = populated_cells / possible if possible else 0.0
    else:
        coverage = 0.0
        possible = total_cells

    stats = {
        "total_laws": total_laws,
        "total_cells": total_cells,
        "populated_cells": populated_cells,
        "total_possible_cells": possible,
        "coverage": round(coverage, 4),
    }

    # Laws sorted for deterministic output
    sorted_laws = sorted(laws, key=lambda r: (
        str(r.get("jurisdiction_id") or ""),
        str(r.get("domain_id") or ""),
        str(r.get("title") or r.get("law_id") or ""),
    ))

    return {
        "domains": domains,
        "jurisdictions": jurisdictions,
        "cells": cells,
        "laws": sorted_laws,
        "runs": sorted(runs),
        "stats": stats,
    }


def collect_all_laws(
    dossier_root: str | Path | None = None,
) -> dict[str, Any]:
    """Aggregate laws across all runs under *dossier_root*.

    Returns a matrix dict (see :func:`build_matrix`) with keys
    ``runs``, ``jurisdictions``, ``domains``, ``cells``, ``laws``, ``stats``.
    Handles an empty or missing ``data/dossiers`` directory gracefully
    (all lists empty, zero stats).

    The function reads, in priority order per run:

    1. ``laws/*.json``
    2. ``cells/*/findings.json``
    3. ``index.json`` (fallback)

    and deduplicates by ``law_id`` across sources within a run, then again
    globally across runs.
    """
    root = _dossier_root(dossier_root)
    run_ids = discover_runs(root)

    if not run_ids:
        return build_matrix([], [], extra_jurisdictions=[], extra_domains=[])

    all_laws: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    extra_jurisdictions: set[str] = set()
    extra_domains: set[str] = set()

    for run_id in run_ids:
        run_dir = root / run_id
        manifest = load_manifest(run_id, root)
        if manifest:
            for j in manifest.get("jurisdictions") or []:
                # Manifest stores display names; slugify to align with law ids
                from langgraph_graph.meta_legal.models import slugify

                extra_jurisdictions.add(slugify(str(j)))
            for d in manifest.get("domains") or []:
                from langgraph_graph.meta_legal.models import normalize_domain

                extra_domains.add(normalize_domain(str(d)))

        batch = _collect_laws_for_run(run_dir)
        for rec in batch:
            enriched = _enrich_law(rec, run_id)
            lid = str(enriched.get("law_id") or "").strip()
            # Global dedup: keep first occurrence across runs
            if lid and lid in seen_ids:
                continue
            if lid:
                seen_ids.add(lid)
            all_laws.append(enriched)

    # If laws already cover jurisdictions/domains, extra_* just fills gaps
    return build_matrix(
        all_laws,
        run_ids,
        extra_jurisdictions=sorted(extra_jurisdictions),
        extra_domains=sorted(extra_domains),
    )


def generate_matrix_json(
    output_path: str | Path,
    dossier_root: str | Path | None = None,
) -> Path:
    """Write the aggregated matrix JSON to *output_path*.

    Creates parent directories as needed. Returns the absolute :class:`Path`
    written. The JSON shape matches :func:`collect_all_laws` / :func:`build_matrix`
    and is suitable for a static frontend fetch.

    Example::

        python -m langgraph_graph.web.aggregator --build web/data/matrix.json
    """
    matrix = collect_all_laws(dossier_root)
    # Add generation timestamp for cache-busting / debugging
    from datetime import UTC, datetime

    matrix["_generated_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    matrix["_dossier_root"] = str(_dossier_root(dossier_root).resolve()) if _dossier_root(dossier_root).exists() else str(_dossier_root(dossier_root))

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out.resolve()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Build law-matrix JSON for the static frontend.")
    parser.add_argument(
        "--build",
        dest="output",
        metavar="OUTPUT_PATH",
        help="Write aggregated matrix JSON to OUTPUT_PATH (e.g. web/data/matrix.json)",
    )
    parser.add_argument(
        "--dossier-root",
        dest="dossier_root",
        default=None,
        help="Override dossier root (default: $DOSSIER_ROOT or data/dossiers)",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print aggregated JSON to stdout instead of writing a file",
    )
    args = parser.parse_args()

    if args.output:
        out = generate_matrix_json(args.output, dossier_root=args.dossier_root)
        print(f"Wrote {out} ({out.stat().st_size} bytes)")
        # Also print a short summary
        data = json.loads(out.read_text(encoding="utf-8"))
        stats = data.get("stats", {})
        print(f"  runs={len(data.get('runs', []))} laws={stats.get('total_laws', 0)} cells={stats.get('total_cells', 0)} coverage={stats.get('coverage', 0)}")
    elif args.print:
        matrix = collect_all_laws(dossier_root=args.dossier_root)
        print(json.dumps(matrix, indent=2, ensure_ascii=False))
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()

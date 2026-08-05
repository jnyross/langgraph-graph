#!/usr/bin/env python3
"""Build web/data/matrix.json from filesystem dossiers.

Primary path imports the canonical aggregator
(:mod:`langgraph_graph.web.aggregator`) when available; a minimal
fallback scans ``data/dossiers/*/manifest.json`` and ``laws/*.json``
so the website remains buildable before the backend subagent lands.

Idempotent: re-running overwrites ``web/data/matrix.json`` with fresh
aggregation. Handles an empty or missing ``data/dossiers`` gracefully
(empty matrix with zero stats) so CI / preview deploys never fail.

Usage:
    uv run python scripts/build_matrix.py
    uv run python scripts/build_matrix.py --output web/data/matrix.json
    uv run python scripts/build_matrix.py --dossier-root data/dossiers --print
    DOSSIER_ROOT=/tmp/dossiers uv run python scripts/build_matrix.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_OUTPUT = "web/data/matrix.json"
DEFAULT_DOSSIER_ROOT = "data/dossiers"


def _fallback_build_matrix(output_path: Path, dossier_root: Path) -> Path:
    """Minimal fallback when the canonical aggregator is not importable.

    Scans ``dossier_root/*/manifest.json`` and ``laws/*.json``,
    deduplicates by ``law_id`` and builds a matrix dict compatible
    with the frontend shape.
    """
    from collections import defaultdict

    root = dossier_root
    run_ids: list[str] = []
    laws: list[dict] = []
    seen: set[str] = set()
    extra_jids: set[str] = set()
    extra_dids: set[str] = set()

    if root.is_dir():
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            manifest_path = entry / "manifest.json"
            if not manifest_path.is_file():
                continue
            run_ids.append(entry.name)
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = {}
            # Collect declared jurisdictions/domains for empty-cell expansion
            if isinstance(manifest, dict):
                try:
                    from langgraph_graph.meta_legal.models import normalize_domain, slugify

                    for j in manifest.get("jurisdictions") or []:
                        extra_jids.add(slugify(str(j)))
                    for d in manifest.get("domains") or []:
                        extra_dids.add(normalize_domain(str(d)))
                except Exception:
                    for j in manifest.get("jurisdictions") or []:
                        extra_jids.add(str(j).strip().lower().replace(" ", "_"))
                    for d in manifest.get("domains") or []:
                        extra_dids.add(str(d).strip().lower().replace(" ", "_"))

            laws_dir = entry / "laws"
            if laws_dir.is_dir():
                for p in sorted(laws_dir.glob("*.json")):
                    try:
                        data = json.loads(p.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    if not isinstance(data, dict):
                        continue
                    lid = str(data.get("law_id") or "").strip()
                    if lid and lid in seen:
                        continue
                    if lid:
                        seen.add(lid)
                    # Enrich minimal fields
                    if "run_id" not in data:
                        data = dict(data)
                        data["run_id"] = entry.name
                    jid = str(data.get("jurisdiction_id") or "").strip()
                    did = str(data.get("domain_id") or "").strip()
                    if not data.get("cell_id") and jid and did:
                        data = dict(data)
                        data["cell_id"] = f"{jid}::{did}"
                    laws.append(data)

    # Build cells structure matching aggregator.build_matrix output
    def _humanize(slug: str) -> str:
        return slug.replace("_", " ").replace("-", " ").title() if slug else slug

    jurisdictions = sorted(extra_jids | {str(l.get("jurisdiction_id") or "").strip() for l in laws if l.get("jurisdiction_id")})
    jurisdictions = [j for j in jurisdictions if j]
    domains = sorted(extra_dids | {str(l.get("domain_id") or "").strip() for l in laws if l.get("domain_id")})
    domains = [d for d in domains if d]

    grouped: dict[str, list[dict]] = defaultdict(list)
    for law in laws:
        cid = str(law.get("cell_id") or "").strip()
        if not cid:
            jid = str(law.get("jurisdiction_id") or "").strip()
            did = str(law.get("domain_id") or "").strip()
            cid = f"{jid}::{did}" if jid and did else "unknown::unknown"
        grouped[cid].append(law)

    cells: dict[str, dict] = {}
    for cid, cell_laws in grouped.items():
        if "::" in cid:
            jid_part, did_part = cid.split("::", 1)
        else:
            jid_part = str(cell_laws[0].get("jurisdiction_id") or "").strip()
            did_part = str(cell_laws[0].get("domain_id") or "").strip()
        cells[cid] = {
            "jurisdiction": _humanize(jid_part),
            "jurisdiction_id": jid_part,
            "domain": did_part,
            "domain_id": did_part,
            "count": len(cell_laws),
            "laws": sorted(cell_laws, key=lambda r: str(r.get("title") or r.get("law_id") or "")),
        }

    if jurisdictions and domains:
        for jid in jurisdictions:
            for did in domains:
                cid = f"{jid}::{did}"
                if cid not in cells:
                    cells[cid] = {
                        "jurisdiction": _humanize(jid),
                        "jurisdiction_id": jid,
                        "domain": did,
                        "domain_id": did,
                        "count": 0,
                        "laws": [],
                    }

    total_laws = len(laws)
    populated = sum(1 for v in cells.values() if v["count"] > 0)
    total_cells = len(cells)
    if jurisdictions and domains:
        possible = len(jurisdictions) * len(domains)
        coverage = round(populated / possible, 4) if possible else 0.0
    else:
        possible = total_cells
        coverage = 0.0

    sorted_laws = sorted(laws, key=lambda r: (str(r.get("jurisdiction_id") or ""), str(r.get("domain_id") or ""), str(r.get("title") or "")))

    from datetime import UTC, datetime

    matrix: dict = {
        "domains": domains,
        "jurisdictions": jurisdictions,
        "cells": cells,
        "laws": sorted_laws,
        "runs": sorted(run_ids),
        "stats": {
            "total_laws": total_laws,
            "total_cells": total_cells,
            "populated_cells": populated,
            "total_possible_cells": possible,
            "coverage": coverage,
        },
        "_generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "_dossier_root": str(root.resolve()) if root.exists() else str(root),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output_path.resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build law-matrix JSON for the static frontend.")
    parser.add_argument(
        "--output",
        dest="output",
        default=None,
        help=f"Output path (default: {DEFAULT_OUTPUT})",
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
        dest="print_stdout",
        help="Print aggregated JSON to stdout instead of writing a file",
    )
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]

        load_dotenv()
    except Exception:
        pass

    dossier_root = Path(args.dossier_root or os.environ.get("DOSSIER_ROOT", DEFAULT_DOSSIER_ROOT))
    output_path = Path(args.output or os.environ.get("MATRIX_OUTPUT", DEFAULT_OUTPUT))

    # --print mode: prefer aggregator.collect_all_laws if available
    if args.print_stdout:
        try:
            from langgraph_graph.web.aggregator import collect_all_laws

            matrix = collect_all_laws(dossier_root)
            print(json.dumps(matrix, indent=2, ensure_ascii=False))
            return
        except ImportError:
            # Fallback: build then print
            tmp = output_path
            _fallback_build_matrix(tmp, dossier_root)
            print(tmp.read_text(encoding="utf-8"))
            return
        except Exception as exc:
            print(f"Error collecting laws: {exc}", file=sys.stderr)
            sys.exit(1)

    # Normal file-build path: try canonical aggregator first, fallback on ImportError
    try:
        from langgraph_graph.web.aggregator import generate_matrix_json

        # File existence check as requested — coordinate via import availability
        out = generate_matrix_json(str(output_path), dossier_root=str(dossier_root))
        data = json.loads(out.read_text(encoding="utf-8"))
        stats = data.get("stats", {})
        print(f"Wrote {out} ({out.stat().st_size} bytes)")
        print(f"  runs={len(data.get('runs', []))} laws={stats.get('total_laws', 0)} cells={stats.get('total_cells', 0)} coverage={stats.get('coverage', 0)}")
        return
    except ImportError as exc:
        print(f"Aggregator not available ({exc}); using fallback scanner.", file=sys.stderr)
    except Exception as exc:
        # Real aggregator error (not missing module) should surface
        print(f"Aggregator failed: {exc}", file=sys.stderr)
        print("Falling back to minimal scanner.", file=sys.stderr)

    out = _fallback_build_matrix(output_path, dossier_root)
    data = json.loads(out.read_text(encoding="utf-8"))
    stats = data.get("stats", {})
    print(f"Wrote {out} ({out.stat().st_size} bytes) via fallback")
    print(f"  runs={len(data.get('runs', []))} laws={stats.get('total_laws', 0)} cells={stats.get('total_cells', 0)} coverage={stats.get('coverage', 0)}")


if __name__ == "__main__":
    main()

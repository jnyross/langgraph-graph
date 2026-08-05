#!/usr/bin/env python3
"""Generate a full-catalog demo dossier: 222 jurisdictions × 5 domains.

Populates every jurisdiction with 1-2 synthetic laws per domain on average
(sparse mode) to keep the matrix realistic without exploding file count.
Uses the canonical filesystem writer so the aggregator/frontend consume it
identically to a real research run.

Usage:
    uv run python scripts/seed_full_catalog.py                 # demo_full_<ts>
    uv run python scripts/seed_full_catalog.py --run-id custom
    uv run python scripts/seed_full_catalog.py --sparse 0.6   # 60% of cells
    DOSSIER_ROOT=/tmp/dossiers uv run python scripts/seed_full_catalog.py
"""
from __future__ import annotations

import argparse
import json
import os
import random
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from langgraph_graph.meta_legal.models import LawRecord, ResearchCell, make_cell_id, slugify
from langgraph_graph.meta_legal.nodes.write_dossier import write_dossier_to_root

DEFAULT_DOSSIER_ROOT = "data/dossiers"
DOMAINS = ["privacy", "competition", "youth_safety", "ip", "accessibility"]
CATALOG_PATH = Path("data/jurisdictions/meta_operating_catalog.json")

# Domain-specific law title templates for synthetic generation
TEMPLATES: dict[str, list[str]] = {
    "privacy": [
        "Data Protection Act — {jurisdiction} comprehensive privacy framework",
        "Personal Information Protection Law — {jurisdiction}",
        "Privacy Regulation — {jurisdiction} platform data handling obligations",
        "Consumer Privacy Act — {jurisdiction}",
    ],
    "competition": [
        "Competition Act — {jurisdiction} antitrust provisions for digital platforms",
        "Digital Markets Regulation — {jurisdiction}",
        "Antitrust Guidelines — {jurisdiction} platform dominance rules",
        "Fair Competition Ordinance — {jurisdiction}",
    ],
    "youth_safety": [
        "Child Online Safety Act — {jurisdiction}",
        "Youth Protection Regulation — {jurisdiction} age assurance duties",
        "Minor Safety Code — {jurisdiction}",
        "Children's Digital Privacy Rule — {jurisdiction}",
    ],
    "ip": [
        "Copyright Act — {jurisdiction} platform liability for user content",
        "Intellectual Property Code — {jurisdiction} takedown obligations",
        "Trademark & Platform Liability Regulation — {jurisdiction}",
        "Digital Copyright Directive — {jurisdiction}",
    ],
    "accessibility": [
        "Digital Accessibility Act — {jurisdiction}",
        "Accessibility Standards Regulation — {jurisdiction} platform conformance",
        "Inclusive Design Mandate — {jurisdiction}",
        "Web Accessibility Directive — {jurisdiction}",
    ],
}

EXCERPTS: dict[str, str] = {
    "privacy": "Imposes data controller duties on Meta for user personal data, including lawful basis, retention limits and cross-border transfer constraints.",
    "competition": "Prohibits self-preferencing and mandates interoperability for designated gatekeeper platforms including Meta services.",
    "youth_safety": "Requires age assurance and heightened privacy defaults for users under 18 on Meta platforms.",
    "ip": "Establishes notice-and-action and stay-down duties for copyrighted material hosted on Meta platforms.",
    "accessibility": "Requires WCAG 2.1 AA conformance for Meta consumer-facing interfaces and content tools.",
}

def load_jurisdictions(catalog_path: Path) -> list[dict]:
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    return data.get("jurisdictions", [])

def gen_laws_for_cell(j_name: str, j_id: str, domain: str, n: int) -> list[LawRecord]:
    out: list[LawRecord] = []
    for i in range(n):
        title_tpl = random.choice(TEMPLATES[domain])
        title = title_tpl.format(jurisdiction=j_name)
        slug = slugify(title)[:40] + f"-{i+1}"
        cell_id = make_cell_id(j_id, domain)
        out.append(
            LawRecord(
                law_id=f"{j_id}--{slug}",
                title=title,
                jurisdiction_id=j_id,
                domain_id=domain,
                cell_id=cell_id,
                citation=f"{j_name} {domain} instrument {i+1}, {2020+i}",
                source_url=f"https://example.com/laws/{j_id}/{slug}",
                source_type="primary" if random.random() > 0.4 else "secondary",
                excerpt=EXCERPTS[domain],
                meta_nexus=random.choice(["platform_obligation", "sector_rule", "named_party"]),
                meta_nexus_rationale=f"Synthetic full-catalog entry for {j_name} × {domain} demonstrating matrix scale.",
                confidence=round(random.uniform(0.68, 0.92), 2),
                language="en",
                effective_date=f"{2020+i}-06-01",
                status="in_force",
                worker_model="demo-full-catalog",
            )
        )
    return out

def main() -> None:
    ap = argparse.ArgumentParser(description="Seed full catalog dossier")
    ap.add_argument("--run-id", default=None, help="Override run_id (default demo_full_<ts>)")
    ap.add_argument("--dossier-root", default=os.environ.get("DOSSIER_ROOT", DEFAULT_DOSSIER_ROOT))
    ap.add_argument("--sparse", type=float, default=0.55, help="Fraction of cells to populate (0.0-1.0, default 0.55)")
    ap.add_argument("--catalog", default=str(CATALOG_PATH))
    args = ap.parse_args()

    random.seed(42)

    catalog = load_jurisdictions(Path(args.catalog))
    if not catalog:
        raise SystemExit(f"No jurisdictions in {args.catalog}")

    run_id = args.run_id or f"demo_full_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}_{uuid4().hex[:6]}"
    jurisdictions_display = [j["name"] for j in catalog]
    jurisdictions_ids = [j["id"] for j in catalog]

    # Build cells (one per jurisdiction × domain)
    cells: list[ResearchCell] = []
    for j in catalog:
        j_name = j["name"]
        j_id = j["id"]
        for d in DOMAINS:
            cells.append(
                ResearchCell(
                    cell_id=make_cell_id(j_id, d),
                    jurisdiction=j_name,
                    jurisdiction_id=j_id,
                    domain=d,
                    domain_id=d,
                    status="done",
                    subject="Meta",
                )
            )

    # Generate laws sparsely
    all_laws: list[LawRecord] = []
    for j in catalog:
        for d in DOMAINS:
            if random.random() > args.sparse:
                continue
            # 1 law 60%, 2 laws 30%, 3 laws 10%
            r = random.random()
            n = 1 if r < 0.6 else 2 if r < 0.9 else 3
            all_laws.extend(gen_laws_for_cell(j["name"], j["id"], d, n))

    root = Path(args.dossier_root)
    out = write_dossier_to_root(
        root,
        run_id=run_id,
        jurisdictions=jurisdictions_display,
        domains=DOMAINS,
        subject="Meta",
        accepted=all_laws,
        rejected=[],
        cells=cells,
        cell_errors=[],
    )
    print(f"Wrote {len(all_laws)} laws across {len(cells)} cells ({len(jurisdictions_display)} jurisdictions × {len(DOMAINS)} domains)")
    print(f"Dossier: {out}")
    print(f"Run ID: {run_id}")
    print(f"Next: uv run python -m langgraph_graph.web.aggregator --build web/data/matrix.json")

if __name__ == "__main__":
    main()

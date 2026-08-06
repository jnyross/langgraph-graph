"""Write research artifacts and optionally promote a safe catalog."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langgraph_graph.jurisdiction_catalog.state import CatalogState
from langgraph_graph.meta_legal.jurisdictions import default_catalog_path, load_catalog
from langgraph_graph.meta_legal.run_config import write_run_metrics


def _repo_root() -> Path:
    """Return the repository root from the live catalog path."""
    return default_catalog_path().parents[2]


def _catalog_entry(item: Any) -> dict[str, Any]:
    """Strip run-only fields before serializing a live-catalog entry."""
    raw = item.model_dump() if hasattr(item, "model_dump") else dict(item)
    return {
        key: raw.get(key)
        for key in ("id", "name", "level", "parent_id", "domains_priority", "rationale")
    }


def write_catalog(state: CatalogState) -> dict[str, Any]:
    """Write a research run and promote only after explicit safety gates."""
    run_id = str(state.get("run_id") or "run")
    configured_root = Path(state.get("write_target") or "data/jurisdictions/runs")
    root = configured_root if configured_root.is_absolute() else _repo_root() / configured_root
    out = root / run_id
    out.mkdir(parents=True, exist_ok=True)
    entries = [_catalog_entry(item) for item in state.get("validated") or []]
    catalog = {
        "version": "2",
        "subject": state.get("subject") or "Meta",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "notes": "Evidence-backed jurisdiction catalog research run; not legal advice.",
        "provenance": {
            "method": "deterministic seed planning plus evidence verification",
            "run_id": run_id,
        },
        "jurisdictions": entries,
    }
    (out / "catalog.json").write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "diff.json").write_text(
        json.dumps(state.get("diff") or {}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    rejected = list(state.get("rejected") or [])
    validation_failures = [
        item for item in rejected if item.get("reason") not in {"uncertain", "exclude"}
    ]
    promotion_reasons: list[str] = []
    if not state.get("promote"):
        promotion_reasons.append("promotion not requested")
    if validation_failures:
        promotion_reasons.append("validation-rule failures are present")
    try:
        current_count = len(load_catalog().get("jurisdictions", []))
    except Exception as exc:
        current_count = 0
        promotion_reasons.append(f"current catalog unavailable: {exc}")
    floor = int(current_count * 0.8)
    if current_count and len(entries) < floor:
        promotion_reasons.append(f"accepted count {len(entries)} is below sanity floor {floor}")
    serialized = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
    if not promotion_reasons:
        check_path = out / ".promotion_catalog.json"
        try:
            check_path.write_text(serialized, encoding="utf-8")
            load_catalog(check_path)
            default_catalog_path().write_text(serialized, encoding="utf-8")
        except Exception as exc:
            promotion_reasons.append(f"promotion validation/write failed: {exc}")
        finally:
            check_path.unlink(missing_ok=True)
    report = "# Jurisdiction catalog research run\n\n"
    report += f"- Run: `{run_id}`\n"
    report += f"- Candidates accepted: {len(entries)}\n"
    report += f"- Uncertain/rejected: {len(rejected)}\n"
    report += f"- Promotion: {'allowed' if not promotion_reasons else 'refused'}\n\n"
    if promotion_reasons:
        report += "Promotion refusal reasons:\n"
        report += "".join(f"- {reason}\n" for reason in promotion_reasons)
    else:
        report += "Promotion passed validation and sanity gates.\n"
    errors = list(state.get("errors") or [])
    if errors:
        report += "\nErrors:\n"
        report += "".join(f"- {error}\n" for error in errors)
    (out / "report.md").write_text(report, encoding="utf-8")
    write_run_metrics(
        out,
        {
            "run_id": run_id,
            "candidate_count": len(state.get("candidates") or []),
            "accepted_count": len(entries),
            "uncertain_count": len(rejected),
            "promotion_refused": bool(promotion_reasons),
        },
    )
    return {"output_path": str(out)}

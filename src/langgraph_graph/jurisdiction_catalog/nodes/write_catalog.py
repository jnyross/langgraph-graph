from __future__ import annotations

# ruff: noqa: E501
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langgraph_graph.meta_legal.jurisdictions import default_catalog_path
from langgraph_graph.meta_legal.run_config import write_run_metrics


def write_catalog(state: dict[str, Any]) -> dict[str, Any]:
    run_id = str(state.get("run_id") or "run")
    root = Path(state.get("write_target") or "data/jurisdictions/runs")
    out = root / run_id
    out.mkdir(parents=True, exist_ok=True)
    entries = [x.model_dump() if hasattr(x, "model_dump") else dict(x) for x in state.get("validated") or []]
    catalog = {
        "version": "2", "subject": state.get("subject") or "Meta",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "notes": "Evidence-backed jurisdiction catalog research run; not legal advice.",
        "provenance": {"method": "deterministic seed planning plus evidence verification", "run_id": run_id},
        "jurisdictions": entries,
    }
    (out / "catalog.json").write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    diff = state.get("diff") or {}
    (out / "diff.json").write_text(json.dumps(diff, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = "# Jurisdiction catalog research run\n\n"
    report += f"- Run: `{run_id}`\n- Candidates accepted: {len(entries)}\n- Uncertain/rejected: {len(state.get('rejected') or [])}\n\n"
    report += "The live catalog is not overwritten by default. Promotion requires an explicit flag and no uncertainty blockers.\n"
    (out / "report.md").write_text(report, encoding="utf-8")
    write_run_metrics(out, {"run_id": run_id, "candidate_count": len(state.get("candidates") or []), "accepted_count": len(entries), "uncertain_count": len(state.get("rejected") or [])})
    if state.get("promote") and not state.get("rejected"):
        default_catalog_path().write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"output_path": str(out)}

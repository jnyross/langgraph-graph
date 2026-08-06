"""Write radar artifacts to disk."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langgraph_graph.news_radar.models import (
    RadarManifest,
    RejectedSignal,
    SignalCluster,
    SignalRecord,
    WatchCell,
)
from langgraph_graph.news_radar.state import RadarState

_RADAR_ROOT = Path("data/radar")


def _safe_fs_id(text: str) -> str:
    """Filesystem-safe ID: keep alnum, hyphen, underscore; replace others."""
    safe = re.sub(r"[^\w\-]", "_", str(text).strip())
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe or "unknown"


def _dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _radar_root() -> Path:
    return _RADAR_ROOT


def _group_by_cell_id(items: list[Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}
    for item in items:
        cid = getattr(item, "cell_id", "unknown") or "unknown"
        grouped.setdefault(cid, []).append(item)
    return grouped


def _write_cells(path: Path, cells: list[WatchCell]) -> None:
    cells_dir = path / "cells"
    for cell in cells:
        cid = _safe_fs_id(cell.cell_id)
        _dump_json(cells_dir / f"{cid}.json", cell.model_dump())


def _write_rejected(path: Path, rejected: list[RejectedSignal]) -> None:
    rejected_dir = path / "rejected"
    for cid, records in _group_by_cell_id(rejected).items():
        safe = _safe_fs_id(cid)
        _dump_json(
            rejected_dir / f"{safe}.json",
            [r.model_dump() for r in records],
        )


def _write_signals(path: Path, signals: list[SignalRecord]) -> dict[str, Any]:
    signals_dir = path / "signals"
    timeline: list[dict[str, Any]] = []
    for sig in signals:
        sid = _safe_fs_id(sig.signal_id)
        payload = sig.model_dump()
        _dump_json(signals_dir / f"{sid}.json", payload)
        timeline.append(
            {
                "signal_id": sig.signal_id,
                "title": sig.title,
                "published_date": sig.published_date,
                "event_type": sig.event_type,
                "source_name": sig.source_name,
                "cell_id": sig.cell_id,
            }
        )
    timeline.sort(key=lambda x: (x["published_date"] or "9999", x["title"]))
    _dump_json(path / "timeline.json", timeline)
    return {"timeline": timeline}


def _write_clusters(path: Path, clusters: list[SignalCluster]) -> None:
    _dump_json(path / "clusters.json", [c.model_dump() for c in clusters])


def _delta_json(
    previous_run_id: str | None,
    current_signals: list[SignalRecord],
) -> dict[str, Any]:
    current_ids = {s.signal_id for s in current_signals}
    delta: dict[str, Any] = {
        "previous_run_id": previous_run_id,
        "current_signal_count": len(current_ids),
        "new_signal_count": len(current_ids),
        "removed_signal_count": 0,
    }
    if previous_run_id and current_ids:
        prev_path = _radar_root() / previous_run_id / "index.json"
        if prev_path.exists():
            try:
                prev = json.loads(prev_path.read_text(encoding="utf-8"))
                prev_ids = {s.get("signal_id") for s in prev.get("signals", [])}
                delta["new_signal_count"] = len(current_ids - prev_ids)
                delta["removed_signal_count"] = len(prev_ids - current_ids)
            except Exception:
                pass
    return delta


def write_radar(state: RadarState) -> dict:
    """Persist all radar outputs to ``data/radar/<run_id>/``."""
    run_id = state.get("run_id", "unknown")
    root = _radar_root() / run_id
    root.mkdir(parents=True, exist_ok=True)

    cells: list[WatchCell] = list(state.get("cells", []))
    signals: list[SignalRecord] = list(state.get("signals", []))
    clusters: list[SignalCluster] = list(state.get("clusters", []))
    rejected: list[RejectedSignal] = list(state.get("rejected", []))
    errors: list[Any] = list(state.get("cell_errors", []))
    known_laws: list[Any] = list(state.get("known_laws", []))

    try:
        _write_cells(root, cells)
        _write_signals(root, signals)
        _write_clusters(root, clusters)
        _write_rejected(root, rejected)
        _dump_json(root / "known_laws.json", [dict(law) for law in known_laws])

        manifest = RadarManifest(
            run_id=run_id,
            subject=state.get("subject", "Meta"),
            previous_run_id=state.get("previous_run_id"),
            jurisdictions=state.get("jurisdictions", []),
            domains=state.get("domains", []),
            lookback_days=state.get("lookback_days", 14),
            levels=state.get("levels", []),
            include_rumors=state.get("include_rumors", False),
            signal_count=len(signals),
            cluster_count=len(clusters),
            known_law_count=len(known_laws),
            rejected_count=len(rejected),
            error_count=len(errors),
            catalog_version=state.get("catalog_version", ""),
            radar_path=str(root.resolve()),
        )
        _dump_json(root / "manifest.json", manifest.model_dump())

        index = {
            "run_id": run_id,
            "radar_path": str(root.resolve()),
            "manifest": manifest.model_dump(),
            "signals": [s.model_dump() for s in signals],
            "clusters": [c.model_dump() for c in clusters],
            "cells": [c.model_dump() for c in cells],
            "cell_errors": [dict(e) for e in errors],
        }
        _dump_json(root / "index.json", index)

        delta = _delta_json(state.get("previous_run_id"), signals)
        _dump_json(root / "delta.json", delta)

        metrics = {
            "run_id": run_id,
            "signal_count": len(signals),
            "cluster_count": len(clusters),
            "rejected_count": len(rejected),
            "error_count": len(errors),
            "cells_count": len(cells),
        }
        _dump_json(root / "run_metrics.json", metrics)

        return {"radar_path": str(root.resolve()), "error": None}
    except Exception as exc:
        return {"radar_path": str(root.resolve()), "error": f"write_radar failed: {exc}"}

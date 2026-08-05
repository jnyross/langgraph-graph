"""Filesystem dossier writer for meta_legal research runs.

Writes a website-friendly tree under ``{DOSSIER_ROOT}/{run_id}/``:
manifest, index, per-law JSON/MD, per-cell findings, and rejected bucket.
No HITL; pure filesystem I/O.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from langgraph_graph.meta_legal.models import (
    CellError,
    DossierManifest,
    LawRecord,
    RejectedRecord,
    ResearchCell,
    slugify,
)
from langgraph_graph.meta_legal.state import ResearchState

DEFAULT_DOSSIER_ROOT = "data/dossiers"


def safe_fs_id(value: str) -> str:
    """Filesystem-safe path segment: ``::`` → ``__``, each side slugified."""
    parts = (value or "").split("::")
    slugged = [slugify(part) for part in parts]
    text = "__".join(slugged).strip("_")
    # Collapse accidental triple+ underscores from empty middle segments
    while "___" in text:
        text = text.replace("___", "__")
    return text or "unknown"


def _default_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}_{uuid4().hex[:8]}"


def _dossier_root() -> Path:
    return Path(os.environ.get("DOSSIER_ROOT", DEFAULT_DOSSIER_ROOT))


def _as_law(item: LawRecord | Mapping[str, Any]) -> LawRecord:
    if isinstance(item, LawRecord):
        return item
    return LawRecord.model_validate(item)


def _as_rejected(item: RejectedRecord | Mapping[str, Any]) -> RejectedRecord:
    if isinstance(item, RejectedRecord):
        return item
    return RejectedRecord.model_validate(item)


def _as_cell(item: ResearchCell | Mapping[str, Any]) -> ResearchCell:
    if isinstance(item, ResearchCell):
        return item
    return ResearchCell.model_validate(item)


def _as_cell_error(item: CellError | Mapping[str, Any]) -> CellError:
    if isinstance(item, CellError):
        return item
    return CellError.model_validate(item)


def _dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _law_markdown(record: LawRecord) -> str:
    """Human-readable companion for a single accepted law record."""
    lines = [
        f"# {record.title}",
        "",
        f"- **law_id**: `{record.law_id}`",
        f"- **jurisdiction_id**: `{record.jurisdiction_id}`",
        f"- **domain_id**: `{record.domain_id}`",
        f"- **cell_id**: `{record.cell_id}`",
        f"- **meta_nexus**: `{record.meta_nexus}`",
        f"- **citation**: {record.citation or '—'}",
        f"- **source_url**: {record.source_url or '—'}",
        f"- **source_type**: `{record.source_type}`",
        f"- **language**: `{record.language}`",
        f"- **effective_date**: {record.effective_date or '—'}",
        f"- **status**: {record.status or '—'}",
        f"- **confidence**: {record.confidence}",
        f"- **validated**: {record.validated}",
        "",
        "## Meta nexus rationale",
        "",
        record.meta_nexus_rationale or "—",
        "",
        "## Excerpt",
        "",
        record.excerpt or "—",
        "",
    ]
    return "\n".join(lines)


def write_dossier_to_root(
    root: str | Path,
    *,
    run_id: str,
    jurisdictions: Sequence[str],
    domains: Sequence[str],
    subject: str = "Meta",
    accepted: Sequence[LawRecord | Mapping[str, Any]] | None = None,
    rejected: Sequence[RejectedRecord | Mapping[str, Any]] | None = None,
    cells: Sequence[ResearchCell | Mapping[str, Any]] | None = None,
    model: str | None = None,
    cell_errors: Sequence[CellError | Mapping[str, Any]] | None = None,
) -> Path:
    """Write a complete dossier tree under ``root / run_id`` and return that path.

    Pure helper (no graph state) so unit tests can pass ``tmp_path`` directly.
    Zero accepted still writes ``manifest.json`` and ``index.json``.
    """
    if not run_id or not str(run_id).strip():
        raise ValueError("run_id must be a non-empty string")

    root_path = Path(root)
    dossier_dir = root_path / str(run_id).strip()
    dossier_dir.mkdir(parents=True, exist_ok=True)

    accepted_records = [_as_law(item) for item in (accepted or [])]
    rejected_records = [_as_rejected(item) for item in (rejected or [])]
    cell_models = [_as_cell(item) for item in (cells or [])]
    errors = [_as_cell_error(item) for item in (cell_errors or [])]

    cell_ids: list[str] = []
    seen_cell_ids: set[str] = set()
    for cell in cell_models:
        if cell.cell_id and cell.cell_id not in seen_cell_ids:
            cell_ids.append(cell.cell_id)
            seen_cell_ids.add(cell.cell_id)
    for record in accepted_records:
        if record.cell_id and record.cell_id not in seen_cell_ids:
            cell_ids.append(record.cell_id)
            seen_cell_ids.add(record.cell_id)
    for item in rejected_records:
        cid = item.cell_id or getattr(item.record, "cell_id", "") or ""
        if cid and cid not in seen_cell_ids:
            cell_ids.append(cid)
            seen_cell_ids.add(cid)

    laws_dir = dossier_dir / "laws"
    cells_dir = dossier_dir / "cells"
    rejected_dir = dossier_dir / "rejected"
    laws_dir.mkdir(parents=True, exist_ok=True)
    cells_dir.mkdir(parents=True, exist_ok=True)
    rejected_dir.mkdir(parents=True, exist_ok=True)

    law_ids: list[str] = []
    accepted_by_cell: dict[str, list[LawRecord]] = defaultdict(list)

    for record in accepted_records:
        safe_law = safe_fs_id(record.law_id)
        if not safe_law or safe_law == "unknown":
            safe_law = safe_fs_id(record.title) or uuid4().hex[:12]
        # Keep law_ids as original ids for index; path uses safe segment.
        law_ids.append(record.law_id)
        payload = record.model_dump(mode="json")
        _dump_json(laws_dir / f"{safe_law}.json", payload)
        (laws_dir / f"{safe_law}.md").write_text(_law_markdown(record), encoding="utf-8")
        cell_key = record.cell_id or "unknown"
        accepted_by_cell[cell_key].append(record)

    for cell_id, records in accepted_by_cell.items():
        safe_cell = safe_fs_id(cell_id)
        cell_path = cells_dir / safe_cell
        cell_path.mkdir(parents=True, exist_ok=True)
        _dump_json(
            cell_path / "findings.json",
            {
                "cell_id": cell_id,
                "count": len(records),
                "law_ids": [r.law_id for r in records],
                "findings": [r.model_dump(mode="json") for r in records],
            },
        )

    rejected_by_cell: dict[str, list[RejectedRecord]] = defaultdict(list)
    for item in rejected_records:
        cid = (item.cell_id or getattr(item.record, "cell_id", "") or "").strip()
        bucket = cid if cid else "all"
        rejected_by_cell[bucket].append(item)

    if rejected_records and not rejected_by_cell:
        rejected_by_cell["all"] = list(rejected_records)

    for bucket, items in rejected_by_cell.items():
        safe_bucket = safe_fs_id(bucket) if bucket != "all" else "all"
        _dump_json(
            rejected_dir / f"{safe_bucket}.json",
            {
                "cell_id": None if bucket == "all" else bucket,
                "count": len(items),
                "rejected": [item.model_dump(mode="json") for item in items],
            },
        )

    dossier_path_str = str(dossier_dir)
    manifest = DossierManifest(
        run_id=str(run_id).strip(),
        subject=subject or "Meta",
        jurisdictions=list(jurisdictions or []),
        domains=list(domains or []),
        cell_ids=cell_ids,
        accepted_count=len(accepted_records),
        rejected_count=len(rejected_records),
        error_count=len(errors),
        dossier_path=dossier_path_str,
    )
    _dump_json(dossier_dir / "manifest.json", manifest.model_dump(mode="json"))

    index_payload: dict[str, Any] = {
        "run_id": manifest.run_id,
        "subject": manifest.subject,
        "jurisdictions": list(manifest.jurisdictions),
        "domains": list(manifest.domains),
        "accepted_count": manifest.accepted_count,
        "rejected_count": manifest.rejected_count,
        "error_count": manifest.error_count,
        "cell_ids": list(manifest.cell_ids),
        "law_ids": law_ids,
        "laws": [
            {
                "law_id": r.law_id,
                "title": r.title,
                "jurisdiction_id": r.jurisdiction_id,
                "domain_id": r.domain_id,
                "cell_id": r.cell_id,
                "path": f"laws/{safe_fs_id(r.law_id)}.json",
            }
            for r in accepted_records
        ],
        "rejected_buckets": sorted(
            (safe_fs_id(b) if b != "all" else "all") for b in rejected_by_cell
        ),
        "created_at": manifest.created_at,
    }
    if model:
        index_payload["model"] = model
    if errors:
        index_payload["errors"] = [e.model_dump(mode="json") for e in errors]
    _dump_json(dossier_dir / "index.json", index_payload)

    return dossier_dir


def write_dossier(state: ResearchState | Mapping[str, Any]) -> dict[str, Any]:
    """Graph node: persist accepted/rejected findings and return dossier_path."""
    run_id = (state.get("run_id") or "").strip() or _default_run_id()
    subject = (state.get("subject") or "Meta").strip() or "Meta"
    jurisdictions = list(state.get("jurisdictions") or [])
    domains = list(state.get("domains") or [])
    accepted = list(state.get("accepted") or [])
    rejected = list(state.get("rejected") or [])
    cells = list(state.get("cells") or [])
    cell_errors = list(state.get("cell_errors") or [])

    try:
        dossier_dir = write_dossier_to_root(
            _dossier_root(),
            run_id=run_id,
            jurisdictions=jurisdictions,
            domains=domains,
            subject=subject,
            accepted=accepted,
            rejected=rejected,
            cells=cells,
            cell_errors=cell_errors,
        )
    except OSError as exc:
        return {
            "run_id": run_id,
            "error": f"Failed to write dossier under {_dossier_root()}: {exc}",
        }

    return {
        "dossier_path": str(dossier_dir),
        "run_id": run_id,
    }

"""Validate signal drafts produced by scan_cell."""

from __future__ import annotations

from typing import Any

from langgraph_graph.news_radar.models import (
    RejectedSignal,
    SignalDraft,
    SignalRecord,
    WatchCell,
    _coerce_watch_cell,
)
from langgraph_graph.news_radar.state import RadarState

_MIN_TITLE_LENGTH = 10
_MIN_CONFIDENCE = 0.2


def _rejection_reasons(
    draft: SignalDraft, cell: WatchCell | None, include_rumors: bool
) -> list[str]:
    reasons: list[str] = []
    title = (draft.title or "").strip()
    if len(title) < _MIN_TITLE_LENGTH:
        reasons.append("title too short or missing")
    if not (draft.source_url or "").strip().startswith(("http://", "https://")):
        reasons.append("missing or invalid source_url")
    if cell is not None and (
        draft.jurisdiction_id != cell.jurisdiction_id or draft.domain_id != cell.domain_id
    ):
        reasons.append("jurisdiction/domain mismatch with cell")
    if not include_rumors and draft.is_rumor:
        reasons.append("rumor rejected because include_rumors is false")
    if draft.confidence < _MIN_CONFIDENCE:
        reasons.append(f"confidence {draft.confidence:.2f} below threshold")
    return reasons


def _watch_cells_by_id(state: RadarState) -> dict[str, WatchCell]:
    """Map planned cells by cell_id so each draft can be validated against its own cell."""
    cells: dict[str, WatchCell] = {}
    items: list[Any] = list(state.get("cells", []))
    single_cell = state.get("cell")
    if isinstance(single_cell, (WatchCell, dict)):
        items = [single_cell, *items]
    for item in items:
        if isinstance(item, WatchCell):
            cells[item.cell_id] = item
        elif isinstance(item, dict):
            try:
                cell = WatchCell(**item)
                cells[cell.cell_id] = cell
            except Exception:
                continue
    return cells


def validate_signal(state: RadarState) -> dict[str, Any]:
    """Turn drafts into accepted/rejected signal records, one per planned cell."""
    cell_map = _watch_cells_by_id(state)
    drafts = state.get("drafts", [])
    include_rumors = state.get("include_rumors", False)
    accepted: list[SignalRecord] = []
    rejected: list[RejectedSignal] = []

    for draft_obj in drafts:
        draft: SignalDraft
        if isinstance(draft_obj, SignalDraft):
            draft = draft_obj
        else:
            try:
                draft = SignalDraft(**dict(draft_obj))
            except Exception:
                fallback = _coerce_watch_cell(draft_obj)
                fallback_cell_id = fallback.cell_id if fallback else str(
                    getattr(draft_obj, "cell_id", "") or ""
                )
                fallback_jurisdiction_id = fallback.jurisdiction_id if fallback else str(
                    getattr(draft_obj, "jurisdiction_id", "") or ""
                )
                fallback_domain_id = fallback.domain_id if fallback else str(
                    getattr(draft_obj, "domain_id", "") or ""
                )
                rejected.append(
                    RejectedSignal(
                        record=SignalDraft(
                            title=str(getattr(draft_obj, "title", "")),
                            jurisdiction_id=fallback_jurisdiction_id,
                            domain_id=fallback_domain_id,
                            cell_id=fallback_cell_id,
                        ),
                        reason="unparseable draft object",
                        cell_id=fallback_cell_id,
                    )
                )
                continue

        cell = cell_map.get(draft.cell_id) if draft.cell_id else None
        reasons = _rejection_reasons(draft, cell, include_rumors)
        if reasons:
            rejected.append(
                RejectedSignal(
                    record=draft,
                    reason="; ".join(reasons),
                    cell_id=cell.cell_id if cell else draft.cell_id,
                )
            )
        else:
            data = draft.model_dump()
            data["validated"] = True
            accepted.append(SignalRecord(**data))

    return {"accepted": accepted, "rejected": rejected}

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


def validate_signal(state: RadarState) -> dict[str, Any]:
    """Turn drafts into accepted/rejected signal records for one cell."""
    cell = _coerce_watch_cell(state)
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
                fallback_cell_id = cell.cell_id if cell else str(
                    getattr(draft_obj, "cell_id", "") or ""
                )
                fallback_jurisdiction_id = cell.jurisdiction_id if cell else str(
                    getattr(draft_obj, "jurisdiction_id", "") or ""
                )
                fallback_domain_id = cell.domain_id if cell else str(
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

        cell_id = cell.cell_id if cell else draft.cell_id
        reasons = _rejection_reasons(draft, cell, include_rumors)
        if reasons:
            rejected.append(
                RejectedSignal(
                    record=draft,
                    reason="; ".join(reasons),
                    cell_id=cell_id,
                )
            )
        else:
            data = draft.model_dump()
            data["validated"] = True
            accepted.append(SignalRecord(**data))

    return {"accepted": accepted, "rejected": rejected}

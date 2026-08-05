"""Per-cell draft validation (rule-based; optional LLM stub).

``research_cell`` → ``validate_cell`` (Send fan-out) → reduce.

Deterministic checks first. An optional LLM adjudicator may be wired later
via ``prompts/validate.md``; v1 keeps validation pure and offline-testable.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langgraph_graph.meta_legal.models import (
    LawRecord,
    LawRecordDraft,
    RejectedRecord,
    ResearchCell,
    normalize_domain,
    normalize_jurisdiction,
    slugify,
)

# Allowed meta_nexus tags (plan: named_party | platform_obligation | sector_rule | other)
_META_NEXUS_VALUES = frozenset(
    {
        "named_party",
        "platform_obligation",
        "sector_rule",
        "other",
    }
)


def _as_draft(item: Any) -> LawRecordDraft | None:
    """Coerce a draft-like value to LawRecordDraft; return None if unusable."""
    if item is None:
        return None
    if isinstance(item, LawRecordDraft) and not isinstance(item, LawRecord):
        return item
    if isinstance(item, LawRecord):
        # Already validated record re-entering — treat as draft for re-check.
        return LawRecordDraft(**item.model_dump(exclude={"validated"}, exclude_none=False))
    if isinstance(item, Mapping):
        try:
            data = dict(item)
            data.pop("validated", None)
            return LawRecordDraft.model_validate(data)
        except Exception:
            return None
    return None


def _norm_id(value: str, *, kind: str) -> str:
    """Normalize jurisdiction/domain ids for comparison (slug forms)."""
    text = (value or "").strip()
    if not text:
        return ""
    if kind == "jurisdiction":
        # jurisdiction_id is already a slug in ResearchCell; still slugify aliases.
        return slugify(normalize_jurisdiction(text))
    if kind == "domain":
        return normalize_domain(text)
    return slugify(text)


def _canonical_cell_jurisdiction_id(cell: ResearchCell | None) -> str:
    """Stable gold-compatible jurisdiction slug for the active cell."""
    if cell is None:
        return ""
    raw = (cell.jurisdiction_id or "").strip()
    if raw:
        return _norm_id(raw, kind="jurisdiction")
    label = (cell.jurisdiction or "").strip()
    if label:
        return _norm_id(label, kind="jurisdiction")
    return ""


def _cell_from_state(state: Mapping[str, Any]) -> ResearchCell | None:
    """Build a ResearchCell from state when present (Send payload or full state)."""
    cell = state.get("cell")
    if isinstance(cell, ResearchCell):
        return cell
    if isinstance(cell, Mapping):
        try:
            return ResearchCell.model_validate(cell)
        except Exception:
            pass

    cell_id = (state.get("cell_id") or "").strip()
    jurisdiction_id = (state.get("jurisdiction_id") or "").strip()
    domain_id = (state.get("domain_id") or "").strip()
    jurisdiction = (state.get("jurisdiction") or jurisdiction_id).strip()
    domain = (state.get("domain") or domain_id).strip()
    subject = (state.get("subject") or "Meta").strip() or "Meta"

    if not cell_id and jurisdiction_id and domain_id:
        from langgraph_graph.meta_legal.models import make_cell_id

        cell_id = make_cell_id(jurisdiction_id, domain_id)

    if not cell_id and not (jurisdiction_id and domain_id):
        return None

    if not jurisdiction_id and cell_id and "::" in cell_id:
        jurisdiction_id, _, domain_id = cell_id.partition("::")
        jurisdiction = jurisdiction or jurisdiction_id
        domain = domain or domain_id

    if not jurisdiction_id or not domain_id:
        return None

    try:
        return ResearchCell(
            cell_id=cell_id or f"{jurisdiction_id}::{domain_id}",
            jurisdiction=jurisdiction or jurisdiction_id,
            jurisdiction_id=jurisdiction_id,
            domain=domain or domain_id,
            domain_id=domain_id,
            subject=subject,
            status="validating",
        )
    except Exception:
        return None


def _rejection_reasons(
    draft: LawRecordDraft,
    cell: ResearchCell | None,
) -> list[str]:
    """Return ordered reason codes for a draft (empty ⇒ accept)."""
    reasons: list[str] = []

    title = (draft.title or "").strip()
    if not title:
        reasons.append("missing_title")

    source_url = (draft.source_url or "").strip()
    if not source_url:
        reasons.append("missing_citation")

    nexus = (draft.meta_nexus or "").strip()
    if not nexus:
        reasons.append("missing_meta_nexus")
    elif slugify(nexus) not in _META_NEXUS_VALUES and nexus not in _META_NEXUS_VALUES:  # noqa: SIM102
        # Allow exact tags; also accept already-slug forms.
        # Unknown free-text nexus is treated as missing/unclear.
        if slugify(nexus) not in {slugify(v) for v in _META_NEXUS_VALUES}:
            reasons.append("missing_meta_nexus")

    if cell is not None:
        draft_j = _norm_id(draft.jurisdiction_id, kind="jurisdiction")
        cell_j = _norm_id(cell.jurisdiction_id, kind="jurisdiction")
        if draft_j and cell_j and draft_j != cell_j or not draft_j and cell_j:
            reasons.append("jurisdiction_mismatch")

        draft_d = _norm_id(draft.domain_id, kind="domain")
        cell_d = _norm_id(cell.domain_id, kind="domain")
        if draft_d and cell_d and draft_d != cell_d or not draft_d and cell_d:
            reasons.append("domain_mismatch")

    return reasons


def validate_drafts(
    drafts: list[LawRecordDraft] | list[Any] | None,
    cell: ResearchCell | None = None,
) -> tuple[list[LawRecord], list[RejectedRecord]]:
    """Rule-based validation of drafts for one cell (or unbound).

    Returns ``(accepted, rejected)``. Malformed items become rejected with
    ``malformed_draft`` rather than raising.
    """
    accepted: list[LawRecord] = []
    rejected: list[RejectedRecord] = []

    if not drafts:
        return accepted, rejected

    cell_id = cell.cell_id if cell is not None else ""

    for item in drafts:
        draft = _as_draft(item)
        if draft is None:
            # Preserve something inspectable when possible.
            fallback = LawRecordDraft(
                title="",
                jurisdiction_id=cell.jurisdiction_id if cell else "",
                domain_id=cell.domain_id if cell else "",
                meta_nexus="",
                source_url="",
                cell_id=cell_id,
            )
            if isinstance(item, Mapping):
                # Best-effort partial fill for debugging.
                for key in (
                    "title",
                    "jurisdiction_id",
                    "domain_id",
                    "source_url",
                    "cell_id",
                    "meta_nexus",
                ):
                    val = item.get(key)
                    if isinstance(val, str) and val:
                        setattr(fallback, key, val)
            rejected.append(
                RejectedRecord(
                    record=fallback,
                    reason="malformed_draft",
                    cell_id=cell_id or getattr(fallback, "cell_id", "") or "",
                )
            )
            continue

        # Stamp cell_id when missing and cell is known.
        if cell is not None and not (draft.cell_id or "").strip():
            draft = draft.model_copy(update={"cell_id": cell.cell_id})

        reasons = _rejection_reasons(draft, cell)
        if reasons:
            rejected.append(
                RejectedRecord(
                    record=draft,
                    reason=",".join(reasons),
                    cell_id=cell_id or draft.cell_id or "",
                )
            )
            continue

        payload = draft.model_dump()
        # Producer-side alignment: accepted records always carry the cell's
        # canonical jurisdiction/domain slugs (gold-compatible), even if the
        # LLM emitted a label/alias that normalized equivalently.
        if cell is not None:
            canon_j = _canonical_cell_jurisdiction_id(cell)
            canon_d = _norm_id(cell.domain_id or cell.domain, kind="domain")
            if canon_j:
                payload["jurisdiction_id"] = canon_j
            if canon_d:
                payload["domain_id"] = canon_d
            if not (payload.get("cell_id") or "").strip():
                payload["cell_id"] = cell.cell_id
        accepted.append(LawRecord(**payload, validated=True))

    return accepted, rejected


def validate_cell(state: dict[str, Any] | Mapping[str, Any]) -> dict[str, Any]:
    """LangGraph node: validate drafts for the current cell payload.

    Expected Send-style keys (subset OK)::

        drafts: list[LawRecordDraft]
        cell_id / jurisdiction_id / domain_id  (or nested ``cell``)

    When ``drafts`` spans multiple cells, filters to the active ``cell_id``
    if one can be resolved.

    Returns::

        {"accepted": list[LawRecord], "rejected": list[RejectedRecord]}
    """
    state_map: Mapping[str, Any] = state if isinstance(state, Mapping) else {}
    cell = _cell_from_state(state_map)

    raw_drafts = state_map.get("drafts") or []
    if not isinstance(raw_drafts, list):
        raw_drafts = [raw_drafts]

    drafts: list[Any] = list(raw_drafts)

    # If we know the cell, only validate drafts for that cell when mixed.
    if cell is not None and drafts:
        cell_id = cell.cell_id
        filtered = [d for d in drafts if _draft_cell_id(d) in ("", cell_id)]
        # Prefer filtered set when any draft carries a cell_id match or empty;
        # if every draft belongs to other cells, validate none for this cell.
        if any(_draft_cell_id(d) == cell_id for d in drafts) or any(
            _draft_cell_id(d) == "" for d in drafts
        ):
            drafts = filtered
        else:
            drafts = []

    accepted, rejected = validate_drafts(drafts, cell=cell)
    return {"accepted": accepted, "rejected": rejected}


def _draft_cell_id(item: Any) -> str:
    if isinstance(item, LawRecordDraft):
        return (item.cell_id or "").strip()
    if isinstance(item, Mapping):
        return str(item.get("cell_id") or "").strip()
    return ""


__all__ = [
    "validate_cell",
    "validate_drafts",
]

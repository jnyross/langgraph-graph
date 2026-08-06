from __future__ import annotations

# ruff: noqa: E501
from typing import Any

from ..models import SUPPORTED_LEVELS, Candidate, Verification


def validate_candidate(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get("verification")
    if raw is None:
        items = state.get("verifications") or []
        if items:
            raw = items[0]
    raw = raw or {}
    verification = raw if isinstance(raw, Verification) else Verification.model_validate(raw)
    candidate = Candidate.model_validate(
        state.get("candidate") or verification.candidate or state
    )
    reasons: list[str] = []
    if candidate.level not in SUPPORTED_LEVELS:
        reasons.append("unsupported_level")
    if not candidate.id or not candidate.name:
        reasons.append("missing_required_field")
    known_ids = {str(x.get("id") if isinstance(x, dict) else getattr(x, "id", "")) for x in state.get("candidates") or []}
    if candidate.parent_id and known_ids and candidate.parent_id not in known_ids:
        reasons.append("unresolved_parent")
    if verification.verdict == "include" and len(verification.evidence) < 1:
        reasons.append("insufficient_evidence")
    if verification.verdict == "include" and verification.confidence < 0.5:
        reasons.append("low_confidence")
    if reasons or verification.verdict != "include":
        return {"rejected": [{"candidate": candidate.model_dump(), "verification": verification.model_dump(), "reason": ",".join(reasons) or verification.verdict}]}
    return {"validated": [candidate]}

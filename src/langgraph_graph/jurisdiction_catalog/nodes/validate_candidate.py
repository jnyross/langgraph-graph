"""Deterministic validation for verified catalog candidates."""

from __future__ import annotations

from typing import Any

from ..models import SUPPORTED_LEVELS, Candidate, Verification
from ..state import CatalogState


def _validate_one(
    candidate: Candidate, verification: Verification, known_ids: set[str]
) -> tuple[Candidate | None, dict[str, Any] | None]:
    reasons: list[str] = []
    if candidate.level not in SUPPORTED_LEVELS:
        reasons.append("unsupported_level")
    if not candidate.id or not candidate.name:
        reasons.append("missing_required_field")
    if candidate.parent_id and candidate.parent_id not in known_ids:
        reasons.append("unresolved_parent")
    if verification.verdict == "include" and not verification.evidence:
        reasons.append("insufficient_evidence")
    if verification.verdict == "include" and verification.confidence < 0.5:
        reasons.append("low_confidence")
    if reasons or verification.verdict != "include":
        return None, {
            "candidate": candidate.model_dump(),
            "verification": verification.model_dump(),
            "reason": ",".join(reasons) or verification.verdict,
        }
    return candidate, None


def validate_candidate(state: CatalogState) -> dict[str, Any]:
    """Validate every verification by its embedded candidate, never by index."""
    direct_verification = state.get("verification")
    if direct_verification is not None:
        verification = (
            direct_verification
            if isinstance(direct_verification, Verification)
            else Verification.model_validate(direct_verification)
        )
        candidate = state.get("candidate") or verification.candidate
        if candidate is None:
            return {
                "rejected": [
                    {
                        "candidate": {},
                        "verification": verification.model_dump(),
                        "reason": "missing_candidate",
                    }
                ]
            }
        known_ids = {
            item.id if isinstance(item, Candidate) else str(item.get("id", ""))
            for item in state.get("candidates") or []
        }
        accepted_one, failure = _validate_one(candidate, verification, known_ids)
        return {
            "validated": [accepted_one] if accepted_one is not None else [],
            "rejected": [failure] if failure is not None else [],
        }
    verifications = [
        item if isinstance(item, Verification) else Verification.model_validate(item)
        for item in state.get("verifications") or []
    ]
    known_ids = {
        item.id if isinstance(item, Candidate) else str(item.get("id", ""))
        for item in state.get("candidates") or []
    }
    accepted: list[Candidate] = []
    rejected: list[dict[str, Any]] = []
    for verification in verifications:
        if verification.candidate is None:
            rejected.append(
                {
                    "candidate": {},
                    "verification": verification.model_dump(),
                    "reason": "missing_candidate",
                }
            )
            continue
        item, failure = _validate_one(verification.candidate, verification, known_ids)
        if item is not None:
            accepted.append(item)
        if failure is not None:
            rejected.append(failure)
    return {"validated": accepted, "rejected": rejected}

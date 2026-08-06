"""Graph state for the jurisdiction resolver pipeline."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class JurisdictionState(TypedDict):
    """State that flows through the jurisdiction resolver graph."""

    subject: NotRequired[str]
    requested: NotRequired[list[str]]
    levels: NotRequired[list[str]]
    strict: NotRequired[bool]

    resolved: NotRequired[list[str]]
    unresolved: NotRequired[list[str]]
    jurisdiction_ids: NotRequired[list[str]]
    jurisdictions: NotRequired[list[str]]

    run_id: NotRequired[str]
    error: NotRequired[str | None]

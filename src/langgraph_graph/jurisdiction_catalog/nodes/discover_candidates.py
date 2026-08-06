from __future__ import annotations

from typing import Any


def discover_candidates(state: dict[str, Any]) -> dict[str, Any]:
    """Optional discovery hook. Proposals remain candidates requiring verification."""
    # Discovery is intentionally conservative when no configured model exists.
    # Candidate planning is deterministic; an optional model may be added here
    # later, but it must return only additional Candidate objects.
    return {}

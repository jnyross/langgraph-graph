"""Fan-in node for verification reducers."""

from __future__ import annotations

from ..state import CatalogState


def aggregate(state: CatalogState) -> dict[str, object]:
    """Reducer fan-in is already complete; do not append lists again."""
    return {}

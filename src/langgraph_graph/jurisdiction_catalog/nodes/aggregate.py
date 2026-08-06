from __future__ import annotations

from typing import Any


def aggregate(state: dict[str, Any]) -> dict[str, Any]:
    """Reducer fan-in is already complete; do not append lists again."""
    return {}

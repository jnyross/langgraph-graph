"""Runtime helpers for meta_legal CLI / full-grid runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping


# Stable starter order (not frozenset iteration order).
DEFAULT_STARTER_DOMAINS: tuple[str, ...] = (
    "privacy",
    "competition",
    "youth_safety",
    "ip",
    "accessibility",
)

DEFAULT_MAX_CONCURRENCY = 12
_ENV_MAX_CONCURRENCY = "META_LEGAL_MAX_CONCURRENCY"


def max_concurrency(default: int = DEFAULT_MAX_CONCURRENCY) -> int:
    """Resolve invoke ``max_concurrency`` from env, falling back to *default*.

    Reads ``META_LEGAL_MAX_CONCURRENCY``. Invalid / non-positive values fall back
    to *default* (itself clamped to at least 1).
    """
    fallback = max(1, int(default))
    raw = os.getenv(_ENV_MAX_CONCURRENCY)
    if raw is None or not str(raw).strip():
        return fallback
    try:
        value = int(str(raw).strip())
    except ValueError:
        return fallback
    return value if value >= 1 else fallback


def write_run_metrics(
    destination: str | Path,
    metrics: Mapping[str, Any],
    *,
    filename: str = "run_metrics.json",
) -> Path:
    """Write run metrics JSON under *destination* (dir or file path).

    If *destination* is an existing directory (or has no suffix), write
    ``destination / filename``. Otherwise treat *destination* as the file path.
    Parent directories are created as needed.
    """
    path = Path(destination)
    if path.exists() and path.is_dir():
        out = path / filename
    elif path.suffix:
        out = path
    else:
        out = path / filename

    out.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(metrics)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out
